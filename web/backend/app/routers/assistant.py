"""Bounded queries and field proposals saved only by explicit human adoption."""
import asyncio
from datetime import datetime, timezone
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..database import get_db
from ..deps import get_current_user
from ..models import ArchiveTask, AssistantTurn, CaseFile, TaskStatus
from ..core.config_adapter import build_v4_config
from ..services import case_assistant
from ..services import assistant_proposal
from ..services import assistant_history as history
from ..services.assistant_journal import require_consistent
from ..security import decode_token
from ..services.task_manager import task_manager
from ..services.execution_profile import frozen_mode, profile_overrides, task_config, validate_task_authorization
from ..services.safe_errors import SafeTaskError, public_error
from .tasks import _load_task_for_user, _source_changed, _task_out

router = APIRouter(tags=["assistant"])


async def _has_newer_task(db, task):
    return await db.scalar(select(ArchiveTask.id).where(
        ArchiveTask.case_id == task.case_id, ArchiveTask.id > task.id).limit(1)) is not None


async def _require_latest_task(db, task):
    """Call while holding the case lock; historical conversations stay readable."""
    if await _has_newer_task(db, task):
        raise HTTPException(409, "这是历史任务，请在最新任务中修改或继续对话；原会话记录仍可查看。")


class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1500)


class AssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=1500)
    history: list[HistoryItem] = Field(default_factory=list, max_length=6)
    request_id: str | None = Field(default=None, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    expected_revision: int | None = Field(default=None, ge=1, strict=True)
    source_version: str | None = Field(default=None, max_length=64)
    draft_version: int | None = Field(default=None, ge=0, le=9007199254740990, strict=True)

    @field_validator("message")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("请输入归档问题")
        return value.strip()


@router.get("/api/tasks/{task_id}/assistant/history")
async def assistant_history(task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(404, "任务不存在")
    # Expiry/staleness refresh writes proposal_state. Serialize its read/commit
    # with adoption so a stale pending row cannot overwrite applying/applied and
    # hide the durable preimage from startup recovery. Model calls hold no case
    # lock, so ordinary pending requests remain visible while inference runs.
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        changed = await _source_changed(db, task)
        superseded = await _has_newer_task(db, task)
        rows = list((await db.scalars(select(AssistantTurn).where(*history.scope(task, user)).order_by(
            AssistantTurn.created_at.desc(), AssistantTurn.id.desc()).limit(101))).all())
        has_more = len(rows) > 100
        allow_token = task.status in (TaskStatus.awaiting_review, TaskStatus.done) and not task_manager.is_running(task.id)
        messages = [message for row in reversed(rows[:100]) for message in history.history_messages(
            row, task, source_changed=changed or superseded, allow_token=allow_token)]
        await db.commit()
    return {"revision": task.revision, "source_version": task.source_version, "source_changed": changed,
            "messages": messages, "has_more": has_more, "limit": 100}


async def _failure(db, turn_id, message, status):
    if not turn_id:
        return
    try:
        await db.rollback()
        turn = await db.get(AssistantTurn, turn_id)
        if turn and turn.status == "pending":
            turn.status, turn.safe_error, turn.error_status = "failed", message, status
            await db.commit()
    except Exception:
        # Persisted pending is deliberately not retryable. Startup will label
        # its external outcome unknown, without resending the user's message.
        await db.rollback()


@router.post("/api/tasks/{task_id}/assistant")
async def assistant(body: AssistantRequest, task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(404, "任务不存在")
    request_id, turn_id = body.request_id or uuid.uuid4().hex, None
    try:
        async with task_manager.case_lock(task.case_id):
            await db.refresh(task)
            old = await history.find_request(db, task, user, request_id)
            if old:
                if old.request_digest != history.request_digest(body):
                    raise HTTPException(409, "同一请求编号对应的内容不同，请刷新对话后重新提问。")
                if old.status == "completed":
                    response = history.response_for(old, task,
                        source_changed=await _source_changed(db, task) or await _has_newer_task(db, task),
                        allow_token=task.status in (TaskStatus.awaiting_review, TaskStatus.done))
                    await db.commit()
                    return response
                raise HTTPException(old.error_status if old.status != "pending" else 409,
                    old.safe_error or "该请求仍在处理中，请查看会话记录；系统不会重复发送。")
            await require_consistent(db, case_id=task.case_id)
            await _require_latest_task(db, task)
            if ((body.expected_revision is not None and body.expected_revision != task.revision)
                    or (body.source_version is not None and body.source_version != task.source_version)):
                raise HTTPException(409, "任务修订或材料版本已变化，请刷新对话后重新提问。")
            mode = frozen_mode(task)
            if mode not in ("local", "ollama_local", "deepseek_cloud"):
                raise HTTPException(409, "本轮云端模式尚未开放辅助对话；可继续使用字段、分类和原文核对界面")
            if await _source_changed(db, task):
                raise HTTPException(409, "材料、分类或办理阶段已变化，请先继续归档更新分析，再使用辅助对话")
            busy = await db.scalar(select(ArchiveTask.id).where(ArchiveTask.status.in_([TaskStatus.pending, TaskStatus.running])).limit(1))
            if busy is not None or task_manager.semaphore.locked():
                raise HTTPException(409, "工作站正在整理材料，请完成后再使用辅助对话")
            files = (await db.scalars(select(CaseFile).where(CaseFile.case_id == task.case_id))).all()
            try:
                snapshot, sources = await asyncio.to_thread(case_assistant.load_context, task, files, user.org_id)
            except (OSError, ValueError, case_assistant.SourceUnavailable):
                raise HTTPException(409, "尚无可用的当前任务分析快照，请先完成整理或继续归档") from None
            config = (await task_config(db, task, actual_source_version=task.source_version)) if mode in ("deepseek_cloud", "ollama_local") else await build_v4_config(db, user.id, overrides=profile_overrides(task))
            context = await history.model_context(db, task, user)
            context_revision, context_source = task.revision, task.source_version
            turn = AssistantTurn(id=uuid.uuid4().hex, org_id=user.org_id, user_id=user.id, case_id=task.case_id,
                task_id=task.id, request_id=request_id, request_digest=history.request_digest(body),
                revision=task.revision, source_version=task.source_version, user_message=body.message, status="pending")
            db.add(turn)
            try:
                from ..services.assistant_draft import DraftScope, consume_draft
                await consume_draft(db, DraftScope(user.org_id, user.id, task.case_id, task.id),
                    draft_version=body.draft_version, revision=task.revision,
                    source_version=task.source_version, message=body.message, request_id=request_id)
                await db.commit()  # Durable reservation precedes every paid request.
            except IntegrityError:
                await db.rollback()
                raise HTTPException(409, "该请求已登记，请刷新会话查看结果；系统不会重复发送。") from None
            turn_id = turn.id
        if task_manager.semaphore.locked():
            raise HTTPException(409, "工作站正在整理材料，请稍后再问")
        async with task_manager.semaphore:
            await db.refresh(task)
            await require_consistent(db, case_id=task.case_id)
            if task.revision != context_revision or task.source_version != context_source or await _source_changed(db, task):
                raise HTTPException(409, "资料或核对内容已变化，请刷新后再使用辅助对话")
            if mode in ("deepseek_cloud", "ollama_local"):
                validate_task_authorization(task, task.source_version)
            command = await asyncio.to_thread(case_assistant.select_tool, config, body.message, context, task.fields or {})
            await db.refresh(task)
            await require_consistent(db, case_id=task.case_id)
            if task.revision != context_revision or task.source_version != context_source or await _source_changed(db, task):
                raise HTTPException(409, "查询期间材料或核对内容已变化，请刷新并更新分析后重新提问")
            if mode in ("deepseek_cloud", "ollama_local"):
                validate_task_authorization(task, task.source_version)
            if command.get("tool") == assistant_proposal.PROPOSAL_TOOL:
                if task.status not in (TaskStatus.awaiting_review, TaskStatus.done) or task_manager.is_running(task.id):
                    raise HTTPException(409, "当前任务不能修改，请等待处理完成后再提出建议。")
                response = assistant_proposal.make_proposal(task, user.id, command, body.message)
            else:
                response = await asyncio.to_thread(case_assistant.execute_tool, command, task, snapshot, sources)
            async with task_manager.case_lock(task.case_id):
                await db.refresh(task)
                await require_consistent(db, case_id=task.case_id)
                await _require_latest_task(db, task)
                if task.revision != context_revision or task.source_version != context_source or await _source_changed(db, task):
                    raise HTTPException(409, "查询期间材料或核对内容已变化，请刷新并更新分析后重新提问")
                history.complete(turn, response)
                await db.commit()
                return history.response_for(turn, task)
    except HTTPException as exc:
        await _failure(db, turn_id, str(exc.detail), exc.status_code)
        raise
    except SafeTaskError as exc:
        await _failure(db, turn_id, public_error(exc), 409)
        raise HTTPException(409, public_error(exc)) from None
    except assistant_proposal.ProposalError as exc:
        await _failure(db, turn_id, str(exc), 409)
        raise HTTPException(409, str(exc)) from None
    except case_assistant.SourceUnavailable as exc:
        await _failure(db, turn_id, str(exc), 409)
        raise HTTPException(409, str(exc)) from None
    except (case_assistant.AssistantUnavailable, ValueError) as exc:
        message = str(exc) if isinstance(exc, case_assistant.AssistantUnavailable) else "本机模型暂未就绪，请联系管理员检查设置"
        await _failure(db, turn_id, message, 503)
        raise HTTPException(503, message) from None
    except Exception:
        await _failure(db, turn_id, history.FAILED, 503)
        raise HTTPException(503, history.FAILED) from None


class ApplyProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_token: str | None = Field(default=None, min_length=1, max_length=15000)
    proposal_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    expected_revision: int = Field(ge=1, strict=True)
    recover_only: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def identifier(self):
        if not self.proposal_token and not self.proposal_id:
            raise ValueError("需要建议编号")
        return self


@router.post("/api/tasks/{task_id}/assistant/proposals/apply")
async def apply_proposal(body: ApplyProposalRequest, task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(404, "任务不存在")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        ident = body.proposal_id
        if body.proposal_token:
            payload = decode_token(body.proposal_token)
            if (not payload or payload.get("type") != "assistant_proposal" or payload.get("sub") != user.id
                    or payload.get("task_id") != task.id or ident and ident != payload.get("proposal_id")):
                raise HTTPException(409, "建议无效、过期或不属于当前账号和任务，请重新提出修改。")
            ident = payload.get("proposal_id")
        turn = await db.scalar(select(AssistantTurn).where(*history.scope(task, user), AssistantTurn.proposal_id == ident))
        if not turn:
            raise HTTPException(409, "建议不存在或不属于当前会话，请刷新后重新提出修改。")
        if turn.proposal_state == "applied":
            return {"applied": True, "already_applied": True, "proposal_id": ident, "task": _task_out(task)}
        if task.status not in (TaskStatus.awaiting_review, TaskStatus.done) or task_manager.is_running(task.id):
            raise HTTPException(409, "任务正在处理或暂不可修改，请完成后重新核对建议。")
        from ..services.assistant_journal import recover_application, RESTORE_FAILED, RESTORED
        if turn.proposal_state == "applying":
            try:
                outcome = await recover_application(db, turn.id)
                await db.commit()
            except Exception:
                await db.rollback()
                raise HTTPException(503, RESTORE_FAILED) from None
            # Recovery never constitutes renewed human authorization to adopt.
            raise HTTPException(409 if outcome == "restored" else 503,
                                RESTORED if outcome == "restored" else RESTORE_FAILED)
        if body.recover_only:
            raise HTTPException(409, "当前建议无需恢复；本次没有采用。请刷新后重新核对建议。")
        await require_consistent(db, case_id=task.case_id)
        await _require_latest_task(db, task)
        if await _source_changed(db, task):
            raise HTTPException(409, "材料、分类或办理阶段已变化，请先继续归档后重新提出修改。")
        history.refresh_proposal(turn, task)
        if turn.proposal_state != "pending" or body.expected_revision != task.revision:
            await db.commit()
            raise HTTPException(409, "建议已过期或修订已变化，请刷新后重新提出修改。")
        try:
            token = history.response_for(turn, task)["proposal"]["proposal_token"]
            proposal = assistant_proposal.decode_proposal(token, task, user.id, body.expected_revision)
        except assistant_proposal.ProposalError as exc:
            raise HTTPException(409, str(exc)) from None
        from ..services.archive_service import update_task_fields
        from ..services.analysis_snapshot import load_snapshot_data, task_work_dir
        from ..services.document_classification import ClassificationError
        from ..services.task_sources import fields_digest
        work = task_work_dir(user.org_id, task.case_id, task.id)
        journal_possible = False
        turn_id = turn.id
        try:
            original = load_snapshot_data(work)
            if fields_digest(original.get("fields"), task.order_mode) != proposal["fields_digest"]:
                raise HTTPException(409, "字段草稿与保存记录不一致，请刷新并核对表格后重新提出修改。")
            # Commit the preimage before the first filesystem mutation. The
            # second commit makes task changes and adoption status atomic in DB.
            turn.snapshot_before, turn.target_revision = original, task.revision + 1
            turn.proposal_state, turn.safe_error = "applying", ""
            journal_possible = True
            await db.commit()
            await update_task_fields(task, user.org_id, {proposal["field"]:proposal["after"]}, actor_id=user.id)
            turn.proposal_state, turn.applied_revision = "applied", task.revision
            turn.snapshot_before, turn.target_revision = None, None
            turn.updated_at = datetime.now(timezone.utc)
            await db.commit()
        except HTTPException:
            raise
        except Exception as exc:
            await db.rollback()
            if journal_possible:
                try:
                    outcome = await recover_application(db, turn_id)
                    await db.commit()
                    if outcome == "applied":
                        await db.refresh(task)
                        return {"applied": True, "already_applied": True, "proposal_id": ident, "task": _task_out(task)}
                except Exception:
                    await db.rollback()
                    raise HTTPException(503, RESTORE_FAILED) from None
                raise HTTPException(503, RESTORED if outcome in ("restored", "unchanged") else RESTORE_FAILED) from None
            if isinstance(exc, ClassificationError):
                raise HTTPException(409, "分类草稿尚未完整保存，请先核对分类后再采用建议。") from None
            raise HTTPException(409, "修改未完整保存，请检查工作站存储并刷新核对后重试。") from None
        return {"applied": True, "already_applied": False, "proposal_id": proposal["proposal_id"], "task": _task_out(task)}
