"""Archive task endpoints: generate, status, download, WebSocket progress."""
from __future__ import annotations
from ..services.source_forms import original_form_sources, form_fields_preserved
import asyncio
import hashlib
import logging
import os
import uuid
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from ..config import ORGS_DIR
from ..config import get_settings
from ..database import AsyncSessionLocal, get_db
from ..case_access import case_access_filter
from ..deps import get_current_user
from ..models import ArchiveTask, Case, CaseFile, Org, TaskStatus, User
from ..schemas import AssembleRequest, DraftRequest, DocumentClassificationPatch, FieldDecisionRequest, FieldUpdate, FieldsPatch, GenerateRequest, ResumeRequest, PreviewFieldsUpdate, RegenerateRequest, TaskOut
from ..security import decode_token
from ..services.analysis_snapshot import SYSTEM_TEMPLATE_NAMES, load_analysis, task_work_dir
from ..services.archive_service import (
    get_template_docx_path,
    preview_template_pdf,
    refill_templates,
    save_template_docx,
    regenerate_templates,
    run_archive,
    run_assemble,
    update_task_fields,
    invalidate_output,
)
from ..services.output_cleanup import remove_task_outputs
from ..services.preview_fields import (
    build_preview,
    sanitize_preview_custom_values,
    sanitize_preview_styles,
    sanitize_preview_updates,
    TEMPLATE_FIELD_SPECS,
)
from ..services.task_manager import task_manager, filtered_log_lines
from ..services.readiness import check_readiness
from ..services.task_sources import build_source_manifest, source_version, snapshot_exists, fields_digest
from ..services.task_workflow import unresolved_issues, enrich_classification_issues
from ..services import document_classification as classification
from ..core.config_adapter import load_user_settings
from ..services.execution_profile import make_profile, public_profile, frozen_mode, profile_overrides, validate_task_authorization
from ..services.safe_errors import SafeTaskError, public_error
from ..services.delivery_state import has_delivery, is_draft
from ..services.assistant_journal import require_consistent, has_unresolved, RECOVERY_REQUIRED
from ..services.upload_intents import require_no_pending_uploads

router = APIRouter(tags=["tasks"])


async def _classification_edit(operation):
    try:
        return await operation
    except classification.ClassificationError:
        raise HTTPException(409, "分类草稿保存未完成，请先打开文书分类重新保存，再编辑表格") from None


async def _require_current_editable(db, task):
    await require_consistent(db, case_id=task.case_id)
    if task_manager.is_running(task.id) or task.status not in (TaskStatus.awaiting_review, TaskStatus.done):
        raise HTTPException(409, "任务正在处理或不可编辑，请待整理完成后再修改")
    if await _source_changed(db, task):
        raise HTTPException(409, "材料已变化，请先继续整理后再修改")
    if await db.scalar(select(ArchiveTask.id).where(ArchiveTask.case_id == task.case_id, ArchiveTask.id > task.id).limit(1)):
        raise HTTPException(409, "这是历史任务，请在最新任务中修改")
    case = await db.get(Case, task.case_id)
    await _recover_field_snapshot(db, task, case.org_id)


async def _recover_field_snapshot(db, task, org_id, *, strict=True):
    """Caller holds the case lock; the refreshed DB row is authoritative."""
    if (task.status in (TaskStatus.pending, TaskStatus.running)
            or not snapshot_exists(task, org_id)
            or await has_unresolved(db, case_id=task.case_id)):
        return False
    from ..services.field_snapshot_state import reconcile_field_snapshot, FieldSnapshotError, RECOVERY_FAILED
    try:
        return await asyncio.to_thread(reconcile_field_snapshot, task, task_work_dir(org_id, task.case_id, task.id))
    except FieldSnapshotError as exc:
        # Status/history reads expose only committed DB values. Preserve the
        # dedicated classification/source recovery entrance on identity mismatch.
        if not strict and exc.reason == "identity":
            return False
        raise HTTPException(409, RECOVERY_FAILED) from None
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(409, RECOVERY_FAILED) from None


async def _commit_field_update(db, task, org_id):
    """A lost ACK is not proof of rollback: reload before any file recovery."""
    try:
        await db.commit()
        await db.refresh(task)
    except Exception:
        try:
            await db.rollback()
            await db.refresh(task)
            await _recover_field_snapshot(db, task, org_id)
        except Exception:
            # Keep the file for a later authorized read/retry. Never guess the
            # committed state from the in-memory object or disclose DB errors.
            pass
        raise HTTPException(503, "保存结果暂未确认，输入仍可保留；请刷新任务后重试，工作站将按已提交内容恢复。") from None


async def _documents_response(task, db):
    changed = await _source_changed(db, task)
    editable = (task.status in (TaskStatus.awaiting_review, TaskStatus.done)
                or task.status == TaskStatus.failed and task.phase == "artifacts_invalid")
    editable = editable and not task_manager.is_running(task.id) and not changed
    reason = "材料已变化，请先继续整理" if changed else "任务正在处理或尚无可编辑的分析草稿" if not editable else ""
    if await has_unresolved(db, case_id=task.case_id):
        editable, reason = False, RECOVERY_REQUIRED
    result = {"revision": task.revision, "source_changed": changed, "editable": editable,
              "blocked_reason": reason, "documents": [], "options": []}
    case = await db.get(Case, task.case_id)
    try:
        analysis, snapshot = load_analysis(task_work_dir(case.org_id, case.id, task.id))
        classification.project_database_decisions(task, analysis, snapshot, case.stage)
        result["documents"] = classification.document_rows(analysis, task.source_manifest)
        result["options"] = classification.classification_options(analysis.case_type)
    except (OSError, ValueError, KeyError, TypeError):
        result.update(editable=False, blocked_reason="分析快照不可读取，请先继续整理材料")
    return result


@router.get("/api/tasks/{task_id}/documents")
async def get_documents(task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(404, "task not found")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        return await _documents_response(task, db)


@router.patch("/api/tasks/{task_id}/documents/{unit_key}/classification")
async def patch_document_classification(body: DocumentClassificationPatch, task_id: int, unit_key: str,
                                        user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(404, "task not found")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        await require_consistent(db, case_id=task.case_id)
        repairing = task.status == TaskStatus.failed and task.phase == "artifacts_invalid"
        if task_manager.is_running(task.id) or task.status not in (TaskStatus.awaiting_review, TaskStatus.done) and not repairing:
            raise HTTPException(409, "任务正在处理或不可编辑，请待整理完成后再核对")
        if await _source_changed(db, task):
            raise HTTPException(409, "材料已变化，请先继续整理后再修改文书分类")
        if not body.reason.strip():
            raise HTTPException(400, "请填写分类核对说明")
        work = task_work_dir(user.org_id, task.case_id, task.id)
        case = await db.get(Case, task.case_id)
        try:
            analysis, snapshot = load_analysis(work)
            consistent = True
            try:
                classification.verify_classification(task, analysis)
            except classification.ClassificationError:
                consistent = False
            workflow = snapshot.get("workflow") or {}
            consistent = consistent and workflow.get("manual_fields") == (task.manual_fields or {})
            classification.project_database_decisions(task, analysis, snapshot, case.stage)
            old = (task.fields or {}).get(classification.DECISIONS, {}).get(unit_key) or {}
            projected = classification.indexed_units(analysis, task.source_manifest).get(unit_key)
            effective = bool(projected and projected[0].manual_catalog_seq == body.catalog_seq
                             and projected[0].doc_type == body.doc_type)
            same = (old.get("doc_type") == body.doc_type and old.get("catalog_seq") == body.catalog_seq
                    and old.get("reason") == body.reason.strip() and effective)
            replay = old.get("revision") == task.revision and body.expected_revision == task.revision - 1
            if same and consistent and (body.expected_revision == task.revision or replay):
                result = await _documents_response(task, db)
                result["task"] = _task_out(task)
                return result
            if body.expected_revision != task.revision:
                raise HTTPException(409, "草稿版本已改变，请刷新后重新核对分类")
            records = classification.change_classification(task, analysis, snapshot, unit_key, body, user.id, case.stage)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            detail = str(exc) if type(exc) is classification.ClassificationError else "文书快照无效，请刷新后重试"
            raise HTTPException(409, detail) from None
        from ..services.archive_service import _build_catalog_status, refresh_form_drafts
        from ..services.analysis_snapshot import save_snapshot
        from ..services.task_workflow import analysis_issues
        # Preserve independent issues; regenerate classification decisions only.
        preserved = [item for item in task.issues or [] if item.get("kind") not in ("classification", "classification_stale")]
        refreshed = [item for item in analysis_issues(analysis, task.source_manifest)
                     if item.get("kind") in ("classification", "classification_stale")]
        task.issues = preserved + refreshed
        old_missing = {item.get("seq") for item in task.catalog_status or [] if not item.get("found")}
        task.catalog_status = _build_catalog_status(analysis, stage=case.stage, source_manifest=task.source_manifest)
        new_missing = {item.get("seq") for item in task.catalog_status if not item.get("found")}
        decisions = dict(analysis.fields.get("_review_decisions") or {})
        for seq in old_missing ^ new_missing:
            decisions.pop(str(seq), None)
        analysis.fields["_review_decisions"] = decisions
        manual = dict(task.manual_fields or {})
        manual[classification.DECISIONS] = records
        manual["_review_decisions"] = decisions
        task.manual_fields = manual
        refresh_form_drafts(analysis, manual, task.source_manifest, task.issues, task=task)
        task.fields = dict(analysis.fields)
        task.issues = [item for item in task.issues if item.get("kind") != "form_draft"] + [
            item for item in analysis_issues(analysis, task.source_manifest) if item.get("kind") == "form_draft"]
        from ..services.outcome_state import sync_missing_outcome_issue
        task.issues = sync_missing_outcome_issue(task.issues, analysis)
        if task.artifacts:
            history = list(snapshot.setdefault("workflow", {}).get("classification_output_history") or [])
            history.append({"revision": task.revision, "artifacts": task.artifacts, "output_pdf": task.output_pdf})
            snapshot["workflow"]["classification_output_history"] = history
        invalidate_output(task)
        task.stage = "文书分类与表格草稿已更新，可重新生成档案"
        analysis.generated_templates = {}
        try:
            # A failed DB commit leaves a recoverable projection: the retained
            # base plus DB decisions remain the authority for the edit endpoint.
            metadata = {**snapshot.get("workflow", {}), "revision": task.revision,
                        "manual_fields": dict(task.manual_fields or {})}
            # A classification save supersedes a previous field-only transaction.
            # Explicit None clears its marker while retaining the snapshot base.
            metadata["field_save_origin"] = None
            save_snapshot(work, analysis, base_name=snapshot.get("base_name", "archive"), order_mode=task.order_mode,
                          metadata=metadata)
            await db.commit()
        except Exception:
            await db.rollback()
            raise HTTPException(409, "分类保存未完成，原确认不会用于新分类；请刷新分类面板后重新保存") from None
        result = await _documents_response(task, db)
        result["task"] = _task_out(task)
        return result


def _validate_field_patch(fields, *, decisions=True):
    allowed = {key for specs in TEMPLATE_FIELD_SPECS.values() for spec in specs for key in [spec["key"], *spec["aliases"]]}
    internal = {"_review_decisions", "_issue_decisions"} if decisions else set()
    for key, value in fields.items():
        if key not in allowed | internal:
            raise HTTPException(400, "提交内容包含不可编辑字段，请刷新表格后重试")
        if key in internal:
            if not isinstance(value, dict) or len(value) > 500:
                raise HTTPException(400, "核对记录必须为逐项处理对象")
            for item in value.values():
                if not isinstance(item, dict) or set(item) - {"action", "reason"}:
                    raise HTTPException(400, "核对记录包含无效字段")
                if item.get("action") not in ("pending", "skip", "not_applicable", "acknowledged"):
                    raise HTTPException(400, "核对处理方式无效")
                if not isinstance(item.get("reason", ""), str) or len(item.get("reason", "")) > 2000:
                    raise HTTPException(400, "核对说明无效或过长")
        elif value is not None and (not isinstance(value, (str, int, float)) or isinstance(value, bool) or len(str(value)) > 20000):
            raise HTTPException(400, f"字段值无效或过长：{key}")
    return fields


async def _load_task_for_user(db, task_id, user, *, recover_fields=True):
    res = await db.execute(select(ArchiveTask).join(Case, ArchiveTask.case_id == Case.id).where(ArchiveTask.id == task_id, case_access_filter(user)))
    task = res.scalar_one_or_none()
    if task and task.status not in (TaskStatus.pending, TaskStatus.running):
        async with task_manager.case_lock(task.case_id):
            await db.refresh(task)
            if recover_fields:
                await _recover_field_snapshot(db, task, user.org_id, strict=False)
            await _validate_done_artifacts(db, task)
    return task


def _artifact_integrity_errors(task):
    """Check already-verified bytes; parsing PDFs/Word again is unnecessary."""
    from ..services.artifact_manifest import required_artifact_keys
    manifest = task.artifacts or {}
    entries = manifest.get("artifacts") or []
    if (not manifest.get("valid") or manifest.get("revision") != task.revision
            or manifest.get("source_version") != task.source_version or not manifest.get("result_dir")
            or not all(isinstance(item, dict) for item in entries)):
        return ["成果校验记录缺失或与当前修订不一致"]
    registered = {item.get("key"): item for item in entries}
    if set(registered) != required_artifact_keys(registered) or len(entries) != len(registered):
        return ["九件必需成果登记不完整"]
    errors = []
    root = Path(manifest["result_dir"]).resolve()
    for key, item in registered.items():
        try:
            path = Path(item.get("path") or "").resolve()
            if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size != item.get("size"):
                raise ValueError("文件缺失、大小改变或路径异常")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != item.get("sha256"):
                raise ValueError("文件内容已改变")
        except (OSError, ValueError, TypeError):
            # key is from REQUIRED_ARTIFACT_KEYS; OS errors can contain paths.
            errors.append(f"{key}：文件不可读取、缺失或校验不一致")
    if registered["archive_pdf"].get("path") != task.output_pdf:
        errors.append("整卷输出路径与登记不一致")
    return errors


async def _validate_done_artifacts(db, task):
    # Caller holds the case lock. Preserve the confirmation and analyzed
    # snapshot so recovery can rebuild this exact task/revision without LLMs.
    if not has_delivery(task):
        return
    errors = await asyncio.to_thread(_artifact_integrity_errors, task)
    if not errors:
        return
    task.status, task.phase = TaskStatus.failed, "artifacts_invalid"
    task.error = "归档成果缺失或已改变，请点击继续归档按原确认重新生成：" + "；".join(errors)
    task.stage, task.progress = "成果完整性检查未通过，可恢复重新生成", 60.0
    task.finished_at, task.output_pdf = None, ""
    task.requested_operation = "draft" if (task.artifacts or {}).get("delivery_kind") == "draft" else "assemble"
    manifest = dict(task.artifacts or {})
    manifest.update(valid=False, errors=errors)
    task.artifacts = manifest
    await db.commit()


def _task_out(task, source_changed=False, issue_overrides=None, form_policy_update=None):
    from ..services.review_queue import build_review_queue
    from ..services.safe_errors import task_recovery_target
    from ..services.field_decisions import project_issues
    projected_issues = project_issues(task, issue_overrides)
    finished = task.finished_at.isoformat() if task.finished_at else None
    preview_only = get_settings().preview_only
    has_docx = bool(
        task.output_docx_dir
        and os.path.isdir(task.output_docx_dir)
        and all(os.path.isfile(os.path.join(task.output_docx_dir, name + ".docx")) for name in SYSTEM_TEMPLATE_NAMES
                if not (original_form_sources(task.fields,name)))
        and has_delivery(task)
    )
    has_archive = bool(has_delivery(task) and task.output_pdf and os.path.isfile(task.output_pdf))
    return TaskOut(
        id=task.id,
        case_id=task.case_id,
        status=task.status.value,
        progress=task.progress,
        stage=task.stage,
        error=task.error,
        recovery_target=task_recovery_target(task),
        fields=task.fields,
        catalog_status=task.catalog_status,
        output_pdf=task.output_pdf,
        order_mode=task.order_mode,
        preview_only=preview_only,
        can_assemble=bool(get_settings().capabilities["archive_assembly"]),
        has_docx=has_docx,
        has_archive=has_archive,
        delivery_kind="draft" if is_draft(task) and has_archive else "reviewed" if has_archive else "",
        created_at=task.created_at.isoformat(),
        finished_at=finished,
        revision=task.revision or 1, source_version=task.source_version or "",
        source_changed=source_changed, parent_task_id=task.parent_task_id,
        phase=task.phase or "queued", issues=projected_issues,
        review_queue=build_review_queue(task, projected_issues),
        rule_readiness=task.rule_readiness or {}, formal_ready=bool(task.status == TaskStatus.done and (task.rule_readiness or {}).get("formal_ready")),
        artifacts=(task.artifacts or {}).get("artifacts", []) if has_delivery(task) and (task.artifacts or {}).get("valid") else [],
        can_resume=task.status == TaskStatus.failed or source_changed or bool(form_policy_update),
        execution_profile=public_profile(task),
        form_policy_update=form_policy_update,
    )


async def _source_changed(db, task):
    if not task.source_version:
        # A pre-versioning task cannot prove which bytes/classification it used.
        return True
    case = await db.get(Case, task.case_id)
    files = (await db.scalars(select(CaseFile).where(CaseFile.case_id == task.case_id).order_by(CaseFile.created_at))).all()
    try:
        current = await asyncio.to_thread(build_source_manifest, files)
        return source_version(current, case.case_type, getattr(case, "stage", "")) != task.source_version
    except (OSError, ValueError, RuntimeError):
        return True


def _completed_artifacts_unchanged(task):
    """A repeated confirmation reuses only the exact previously verified bytes."""
    from ..services.artifact_manifest import required_artifact_keys, verify_artifact_manifest
    manifest = task.artifacts or {}
    from ..services.output_derivation import RENDERER_VERSION, visible_derivation, verify_cover_count
    if (not manifest.get("valid") or manifest.get("revision") != task.revision
            or manifest.get("source_version") != task.source_version
            or manifest.get("renderer_version") != RENDERER_VERSION):
        return False
    entries = manifest.get("artifacts") or []
    if not all(isinstance(item, dict) for item in entries):
        return False
    registered = {item.get("key"): item for item in entries}
    if set(registered) != required_artifact_keys(registered) or len(entries) != len(registered):
        return False
    if registered["archive_pdf"].get("path") != task.output_pdf or not manifest.get("result_dir"):
        return False
    derived = visible_derivation(task)
    try:
        verify_cover_count(task.output_pdf, registered["docx:档案卷宗"]["path"],
                           derived["volume_page_count"], derived["cover_pages"])
    except (KeyError, ValueError, RuntimeError, OSError):
        return False
    verified = verify_artifact_manifest(
        manifest["result_dir"], {key: item.get("path") for key, item in registered.items()},
        expected_source_pages=manifest.get("expected_source_pages"),
        source_pages_included=manifest.get("source_pages_included"), require_pagination=True,
        pagination=manifest.get("pagination"),
    )
    return bool(verified.get("valid") and all(
        item.get("sha256") == registered[item["key"]].get("sha256") for item in verified["artifacts"]
    ))


@router.post("/api/cases/{case_id}/generate", response_model=TaskOut, status_code=201)
async def generate(body: GenerateRequest, case_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    async with task_manager.case_lock(case_id):
        return await _generate_locked(body, case_id, user, db)


async def _generate_locked(body, case_id, user, db, *, inherited_task=None):
    res = await db.execute(select(Case).where(Case.id == case_id, case_access_filter(user)))
    case = res.scalar_one_or_none()
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    await require_consistent(db, case_id=case.id)
    await require_no_pending_uploads(db, case.id)
    from ..services.archive_rules import get_rule_readiness
    template_ready = get_rule_readiness(case.case_type, getattr(case, "stage", None))
    if not template_ready.get("template_ready", False):
        raise HTTPException(409, "该业务尚无已接入的律所原目录，暂不能生成完整档案；请补充原目录后再启动。材料已保留，未调用模型。")
    fres = await db.execute(select(CaseFile).where(CaseFile.case_id == case_id).order_by(CaseFile.created_at))
    files = fres.scalars().all()
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no files uploaded")
    manifest = await asyncio.to_thread(build_source_manifest, files)
    version = source_version(manifest, case.case_type, getattr(case, "stage", ""))
    try:
        selected_mode = frozen_mode(inherited_task) if inherited_task is not None else (await load_user_settings(db, user.id)).get("processing_mode", "local")
    except SafeTaskError as exc:
        raise HTTPException(409, public_error(exc)) from None
    if body.expected_processing_mode is not None and body.expected_processing_mode != selected_mode:
        raise HTTPException(409, "处理模式已变化，请重新核对模式与云端授权后启动")
    prior = (await db.scalars(select(ArchiveTask).where(ArchiveTask.case_id == case_id).order_by(ArchiveTask.id.desc()))).all()
    for previous in prior:
        await _validate_done_artifacts(db, previous)
    if body.idempotency_key:
        existing = next((task for task in prior if task.idempotency_key == body.idempotency_key), None)
        if existing:
            if existing.source_version != version or existing.order_mode != body.order_mode or frozen_mode(existing) != selected_mode:
                raise HTTPException(409, "本次启动请求的材料已改变，请重新启动新的归档修订")
            return _task_out(existing)
    active = next((task for task in prior if task.status in (TaskStatus.pending, TaskStatus.running)), None)
    if active:
        if frozen_mode(active) != selected_mode:
            raise HTTPException(409, "本案已有不同处理模式的任务正在运行，请等待完成")
        return _task_out(active, active.source_version != version)
    if prior and frozen_mode(prior[0]) == selected_mode and prior[0].source_version == version and prior[0].phase == "artifacts_invalid":
        await _recover_field_snapshot(db, prior[0], user.org_id)
        return _task_out(prior[0])
    from ..services.form_policy_repair import OPERATION as FORM_REPAIR_OPERATION
    if (prior and prior[0].requested_operation == FORM_REPAIR_OPERATION
            and frozen_mode(prior[0]) == selected_mode and prior[0].source_version == version
            and prior[0].order_mode == body.order_mode and prior[0].status == TaskStatus.failed):
        # Resume the original journal explicitly; never turn a failed bounded
        # form repair into a new whole-volume recognition job on repeated start.
        return _task_out(prior[0])
    repair_parent = None
    if prior and frozen_mode(prior[0]) == selected_mode and prior[0].source_version == version and prior[0].order_mode == body.order_mode and prior[0].status != TaskStatus.failed:
        await _recover_field_snapshot(db, prior[0], user.org_id)
        from ..services.form_policy_repair import load_repair_parent
        try:
            candidate = await asyncio.to_thread(load_repair_parent, prior[0], user.org_id,
                case_type=case.case_type, stage=getattr(case, 'stage', '') or '')
        except (OSError, ValueError, TypeError, KeyError, classification.ClassificationError):
            raise HTTPException(409, "表单依据快照无法核验，请先恢复已保存的任务；未启动新的识别") from None
        if candidate is None:
            if body.form_policy_token:
                raise HTTPException(409, "可更新的栏目已变化，请刷新后重新确认；未调用模型")
            return _task_out(prior[0])
        from ..services.form_policy_repair import public_repair_plan
        plan = public_repair_plan(prior[0], candidate)
        if body.form_policy_token != plan['token']:
            raise HTTPException(409, "填写规则或内容已有更新，请刷新后确认本次栏目更新；未调用模型")
        repair_parent = prior[0]
        if body.parent_task_id and body.parent_task_id != repair_parent.id:
            raise HTTPException(409, "请在最新任务上更新表单规则")
        inherited_task = repair_parent  # Keep provider/model frozen; require new consent below.
    parent = repair_parent or (next((task for task in prior if task.id == body.parent_task_id), None) if body.parent_task_id else next((task for task in prior if snapshot_exists(task, user.org_id)), None))
    if body.form_policy_token and repair_parent is None:
        raise HTTPException(409, "本次栏目更新已失效，请刷新后重新确认；未启动整卷识别")
    if body.parent_task_id and not parent:
        raise HTTPException(404, "parent task not found")
    if parent:
        # Only the selected source snapshot can affect this new task. An
        # unrelated historical mismatch must not block a valid current parent.
        await _recover_field_snapshot(db, parent, user.org_id)
    try:
        profile = await make_profile(db, user.id, version, cloud_consent=body.cloud_consent,
                                     expected_mode=body.expected_processing_mode, inherited_task=inherited_task)
    except SafeTaskError as exc:
        raise HTTPException(409, public_error(exc)) from None
    from types import SimpleNamespace
    from ..services.experience_binding import attach_snapshot
    from ..services.experience_rules import ExperienceError
    try:
        profile = await attach_snapshot(db, user.id, case.id, user.org_id, profile, parent=parent)
    except ExperienceError as exc:
        raise HTTPException(409, str(exc)) from None
    if repair_parent:
        profile['_form_policy_plan'] = {'token':plan['token'],'fields':list(plan['fields'])}
    ready = await check_readiness(db, user.id, overrides=profile_overrides(SimpleNamespace(execution_profile=profile)))
    if not ready["ready"]:
        raise HTTPException(409, "；".join(ready["issues"]))
    task = ArchiveTask(case_id=case_id, status=TaskStatus.pending, order_mode=body.order_mode,
                       source_manifest=manifest, source_version=version, created_by=user.id,
                       execution_profile=profile,
                       parent_task_id=parent.id if parent else None, idempotency_key=body.idempotency_key,
                       revision=1, phase="queued", requested_operation=FORM_REPAIR_OPERATION if repair_parent else "analyze_and_draft",
                       manual_fields=dict(parent.manual_fields or {}) if parent else {})
    db.add(task)
    # Serialize the final start decision against an upload registration made by
    # another worker while readiness/source checks were awaiting IO.
    await db.flush()
    await require_no_pending_uploads(db, case.id)
    await db.commit()
    await db.refresh(task)
    task_manager.start(
        task.id,
        run_archive(task.id, case_id, user.org_id, user.id, body.order_mode),
    )
    return _task_out(task)


@router.get("/api/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    issues = task.issues or []
    if any(item.get("kind") in ("classification", "ocr") and isinstance(item.get("detail"), dict)
           and not item["detail"].get("file_id") for item in issues):
        try:
            analysis, _ = await asyncio.to_thread(load_analysis, task_work_dir(user.org_id, task.case_id, task.id))
            issues = enrich_classification_issues(issues, analysis.doc_spans, task.source_manifest)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    source_changed = await _source_changed(db, task)
    plan = None
    # Read-only availability projection: no reconciliation, source parsing,
    # model request, task creation or output change is performed here.
    if not source_changed and task.status in (TaskStatus.awaiting_review, TaskStatus.done) and task.phase != 'artifacts_invalid':
        latest_id = await db.scalar(select(ArchiveTask.id).where(ArchiveTask.case_id == task.case_id).order_by(ArchiveTask.id.desc()).limit(1))
        if latest_id == task.id:
            from ..services.form_policy_repair import load_repair_parent, public_repair_plan
            case = await db.get(Case, task.case_id)
            try:
                saved = await asyncio.to_thread(load_repair_parent, task, user.org_id,
                    case_type=case.case_type, stage=getattr(case, 'stage', '') or '')
                if saved is not None:
                    plan = public_repair_plan(task, saved)
            except (OSError, ValueError, TypeError, KeyError, SafeTaskError, classification.ClassificationError):
                pass  # Unverified snapshots never offer a model action.
    return _task_out(task, source_changed, issue_overrides=issues, form_policy_update=plan)


@router.post("/api/tasks/{task_id}/resume", response_model=TaskOut)
async def resume(task_id: int, body: ResumeRequest | None = None, user=Depends(get_current_user), db=Depends(get_db)):
    body = body or ResumeRequest()
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(404, "task not found")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        await require_consistent(db, case_id=task.case_id)
        try:
            mode = frozen_mode(task)
        except SafeTaskError as exc:
            raise HTTPException(409, public_error(exc)) from None
        if body.expected_processing_mode is not None and body.expected_processing_mode != mode:
            raise HTTPException(409, "续跑使用原任务冻结的处理模式，请刷新后重新核对")
        if task_manager.is_running(task.id):
            return _task_out(task)
        await require_no_pending_uploads(db, task.case_id)
        if await _source_changed(db, task):
            if body.form_policy_token:
                raise HTTPException(409, "材料已有变化，请重新核对补件处理方式；未调用模型")
            return await _generate_locked(GenerateRequest(order_mode=task.order_mode, parent_task_id=task.id,
                cloud_consent=body.cloud_consent, expected_processing_mode=body.expected_processing_mode,
                form_policy_token=body.form_policy_token), task.case_id, user, db, inherited_task=task)
        await _recover_field_snapshot(db, task, user.org_id)
        if task.status != TaskStatus.failed:
            latest_id = await db.scalar(select(ArchiveTask.id).where(ArchiveTask.case_id == task.case_id).order_by(ArchiveTask.id.desc()).limit(1))
            if latest_id != task.id:
                latest = await db.get(ArchiveTask, latest_id)
                plan = (latest.execution_profile or {}).get('_form_policy_plan') or {}
                if (body.form_policy_token and latest.parent_task_id == task.id
                        and latest.source_version == task.source_version
                        and frozen_mode(latest) == mode and plan.get('token') == body.form_policy_token):
                    # A lost response is not a failed start. Return this exact
                    # previously authorized child, even when it already finished.
                    return _task_out(latest)
                return _task_out(task)  # A historical resume cannot become a new repair.
            return await _generate_locked(GenerateRequest(order_mode=task.order_mode, parent_task_id=task.id,
                cloud_consent=body.cloud_consent, expected_processing_mode=body.expected_processing_mode,
                form_policy_token=body.form_policy_token), task.case_id, user, db, inherited_task=task)
        if not task.created_by or not task.source_manifest:
            return await _generate_locked(GenerateRequest(order_mode=task.order_mode, parent_task_id=task.id,
                cloud_consent=body.cloud_consent, expected_processing_mode=body.expected_processing_mode), task.case_id, user, db, inherited_task=task)
        try:
            validate_task_authorization(task, task.source_version)
        except SafeTaskError as exc:
            raise HTTPException(409, public_error(exc)) from None
        if mode in ("deepseek_cloud", "ollama_local") and task.requested_operation in ("analyze", "analyze_and_draft"):
            # Only an explicit, authorized resume of a failed analysis permits
            # another bounded attempt at a previously exhausted segment. This
            # private token is committed before scheduling, is not material or
            # an authority grant, and does not change the journal's base scope.
            task.execution_profile = {**task.execution_profile, "_recognition_retry_token": uuid.uuid4().hex}
        task.status = TaskStatus.pending
        task.phase, task.error, task.finished_at = "queued", "", None
        await db.flush()
        await require_no_pending_uploads(db, task.case_id)
        await db.commit()
        if task.requested_operation == "draft":
            task_manager.start(task.id, run_assemble(task.id, task.case_id, user.org_id, task.created_by, draft=True))
        elif task.requested_operation == "assemble" and (task.confirmation or {}).get("revision") == task.revision:
            task_manager.start(task.id, run_assemble(task.id, task.case_id, user.org_id, task.created_by))
        else:
            task_manager.start(task.id, run_archive(task.id, task.case_id, user.org_id, task.created_by, task.order_mode))
        return _task_out(task)


@router.get("/api/tasks/{task_id}/templates")
async def list_templates(task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return {"templates": list(SYSTEM_TEMPLATE_NAMES)}


@router.patch("/api/tasks/{task_id}/fields", response_model=TaskOut)
async def patch_fields(body: FieldsPatch, task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    _validate_field_patch(body.fields)
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        await _require_current_editable(db, task)
        task.fields = await _classification_edit(update_task_fields(task, user.org_id, body.fields, actor_id=user.id))
        await _commit_field_update(db, task, user.org_id)
        return _task_out(task)


@router.post("/api/tasks/{task_id}/field-decisions", response_model=TaskOut)
async def decide_field(body: FieldDecisionRequest, task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    from ..services.field_decisions import prepare_accept_current, validate_decision_snapshot, FieldDecisionError
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(404, "task not found")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        # Replays also require current materials/latest task/recovered snapshot.
        await _require_current_editable(db, task)
        try:
            analysis, snapshot = load_analysis(task_work_dir(user.org_id, task.case_id, task.id))
            validate_decision_snapshot(task, snapshot)
            classification.verify_classification(task, analysis)
            receipt, replay = prepare_accept_current(task, body, actor_id=user.id, org_id=user.org_id)
        except FieldDecisionError as exc:
            raise HTTPException(409, str(exc)) from None
        except classification.ClassificationError:
            raise HTTPException(409, "分类草稿保存未完成，请先恢复分类后重新核对") from None
        if not replay:
            try:
                task.fields = await _classification_edit(update_task_fields(task, user.org_id,
                    {body.field: body.selected_value if body.action == 'accept_candidate' else body.current_value}, actor_id=user.id, accept_current=receipt))
            except FieldDecisionError as exc:
                raise HTTPException(409, str(exc)) from None
            await _commit_field_update(db, task, user.org_id)
        return _task_out(task)


@router.post("/api/tasks/{task_id}/regenerate-templates", response_model=TaskOut)
async def regenerate(body: RegenerateRequest, task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    _validate_field_patch(body.fields, decisions=False)
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        await _require_current_editable(db, task)
        if task.status != TaskStatus.awaiting_review:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "task not in review")
        await _classification_edit(regenerate_templates(
            task, user.org_id, user.id, body.fields, body.outcome_type
        ))
        invalidate_output(task)
        task.stage = "表格已更新，请预览后合并"
        await _commit_field_update(db, task, user.org_id)
        return _task_out(task)


@router.post("/api/tasks/{task_id}/draft", response_model=TaskOut)
async def generate_draft(body: DraftRequest, task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    """Generate the usable draft without claiming a human has reviewed it."""
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(404, "任务不存在")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        await require_consistent(db, case_id=task.case_id)
        await _recover_field_snapshot(db, task, user.org_id)
        if body.expected_revision != task.revision:
            raise HTTPException(409, "草稿版本已变化，请刷新后生成当前版本")
        if task.status in (TaskStatus.pending, TaskStatus.running) or task_manager.is_running(task.id):
            return _task_out(task)
        await require_no_pending_uploads(db, task.case_id)
        if await _source_changed(db, task):
            raise HTTPException(409, "材料或办理阶段已变化，请继续整理后自动生成新档案")
        if has_delivery(task) and _completed_artifacts_unchanged(task):
            return _task_out(task)
        if not snapshot_exists(task, user.org_id):
            raise HTTPException(409, "尚无已完成的材料分析，请先开始整理")
        try:
            analysis, snap = load_analysis(task_work_dir(user.org_id, task.case_id, task.id))
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(409, "分析快照暂不可用，请继续整理恢复后再生成档案") from None
        if (snap.get("workflow", {}).get("source_version") != task.source_version
                or fields_digest(analysis.fields, task.order_mode) != fields_digest(task.fields, task.order_mode)):
            raise HTTPException(409, "已保存字段与分析版本不一致，请刷新并继续整理")
        await _classification_edit(asyncio.to_thread(classification.verify_classification, task, analysis))
        # A first draft can upgrade legacy analyzed fields. Rebuilding an
        # existing delivery (including a renderer upgrade) must use its saved
        # inputs exactly: an output repair is not an instruction to rederive
        # business values or discard the previous-generation link.
        from ..services.archive_service import refresh_form_drafts
        from ..services.analysis_snapshot import update_snapshot_fields, snapshot_path, _atomic_write
        from ..services.task_workflow import analysis_issues
        work = task_work_dir(user.org_id, task.case_id, task.id)
        saved_drafts = (analysis.fields or {}).get("_form_drafts") or {}
        has_saved_drafts = isinstance(saved_drafts, dict) and isinstance(saved_drafts.get("fields"), dict) and bool(saved_drafts["fields"])
        # Field saves already update dependent drafts. Rendering that committed
        # revision must not run a newer generator over unrelated saved wording.
        refreshed = (analysis.fields if task.phase == "artifacts_invalid" or has_delivery(task) or has_saved_drafts else
                     refresh_form_drafts(analysis, task.manual_fields or {}, task.source_manifest, task.issues, task=task))
        snapshot_changed = fields_digest(refreshed, task.order_mode) != fields_digest(task.fields, task.order_mode)
        if snapshot_changed:
            update_snapshot_fields(work, refreshed, generated_templates={})
            task.fields = refreshed
            task.issues = [item for item in task.issues or [] if item.get("kind") != "form_draft"] + [
                item for item in analysis_issues(analysis, task.source_manifest) if item.get("kind") == "form_draft"]
            from ..services.outcome_state import sync_missing_outcome_issue
            task.issues = sync_missing_outcome_issue(task.issues, analysis)
            invalidate_output(task)
        task.requested_operation = "draft"
        task.confirmation = None
        task.status, task.phase = TaskStatus.running, "rendering"
        task.stage, task.error, task.finished_at = "正在生成整卷档案草稿", "", None
        try:
            await db.flush()
            await require_no_pending_uploads(db, task.case_id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            if snapshot_changed:
                _atomic_write(snapshot_path(work), snap)
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(503, "草稿生成请求未保存，请稍后重试；原材料仍然保留") from None
        task_manager.start(task.id, run_assemble(task.id, task.case_id, user.org_id, user.id, task.order_mode, draft=True))
        return _task_out(task)


@router.post("/api/tasks/{task_id}/assemble", response_model=TaskOut)
async def assemble(body: AssembleRequest, task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        await require_consistent(db, case_id=task.case_id)
        await _recover_field_snapshot(db, task, user.org_id)
        repairing = task.status == TaskStatus.failed and task.phase == "artifacts_invalid"
        if task.status not in (TaskStatus.awaiting_review, TaskStatus.done) and not repairing:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "task not ready for assembly")
        await require_no_pending_uploads(db, task.case_id)
        if await _source_changed(db, task):
            raise HTTPException(409, "材料或分类已变化，请先补件继续分析，再确认本次修订")
        if snapshot_exists(task, user.org_id):
            try:
                analyzed, _ = load_analysis(task_work_dir(user.org_id, task.case_id, task.id))
                classification.verify_classification(task, analyzed)
            except classification.ClassificationError:
                raise HTTPException(409, "分类草稿与快照不一致，请打开文书分类重新保存后确认") from None
        confirmation = task.confirmation or {}
        same_confirmation = (body.confirmation and body.confirmed_revision == task.revision
                             and confirmation.get("revision") == task.revision
                             and confirmation.get("source_version") == task.source_version
                             and confirmation.get("fields_digest") == fields_digest(task.fields, body.order_mode)
                             and confirmation.get("order_mode") == body.order_mode
                             and sorted(confirmation.get("skipped") or []) == sorted(body.skipped))
        if task.status == TaskStatus.done and same_confirmation and await asyncio.to_thread(_completed_artifacts_unchanged, task):
            return _task_out(task)
        if ((task.fields or {}).get('_request_budget_stop') or {}).get('status')=='incomplete':
            raise HTTPException(409,'任务额度用尽，识别或填写仍未完成；草稿已保留，暂不能确认定稿。')
        if not get_settings().capabilities["archive_assembly"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "未找到可用的 PDF 生成器")
        if task_manager.is_running(task_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "task already running")
        missing = {item["seq"] for item in (task.catalog_status or []) if not item.get("found") and item.get("seq") is not None}
        verified_required = [item for item in (task.catalog_status or []) if not item.get("found")
                             and item.get("legal_requirement_verified") is True and item.get("requirement") == "required"]
        from ..services.archive_rules import unresolved_material_requirements
        verified_required += unresolved_material_requirements(task.catalog_status)
        if verified_required:
            task.status = TaskStatus.awaiting_review
            task.phase = "draft_ready" if is_draft(task) else "needs_input"
            task.confirmation = None
            task.stage = "草稿已保留，仍有已核验必需材料待补充"
            rules = dict(task.rule_readiness or {})
            rules["formal_ready"] = False
            rules["unresolved_required_items"] = [{"seq": item.get("seq"), "name": item.get("name", "")} for item in verified_required]
            task.rule_readiness = rules
            await db.commit()
            raise HTTPException(409, "草稿已保留；已核验必需材料不能通过暂缺或不适用跳过，请补充后继续归档")
        if set(body.skipped) != missing or len(body.skipped) != len(set(body.skipped)):
            raise HTTPException(409, "请逐项核对缺失材料并明确选择补充或暂缺；补充后需重新分析")
        decisions = (task.fields or {}).get("_review_decisions", {})
        if missing and not isinstance(decisions, dict):
            raise HTTPException(409, "缺项核对记录无效，请逐项重新核对并保存。")
        for seq in sorted(missing):
            decision = decisions.get(str(seq))
            if not isinstance(decision, dict) or decision.get("action") not in ("not_applicable", "skip"):
                raise HTTPException(409, f"目录项 {seq} 尚未明确处理，请核对并保存后再生成归档。")
            if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
                raise HTTPException(409, f"请填写目录项 {seq} 暂缺或不适用的原因并保存。")
        if unresolved_issues(task.issues, task.fields, task=task):
            raise HTTPException(409, "请处理并保存所有材料异常的核对说明")
        if not body.confirmation or body.confirmed_revision != (task.revision or 1):
            raise HTTPException(409, "草稿版本已改变或尚未最终确认，请刷新后确认当前修订出卷")
        task.confirmation = {"revision": task.revision or 1, "source_version": task.source_version or "",
                             "fields_digest": fields_digest(task.fields, body.order_mode),
                             "user_id": user.id, "confirmed_at": datetime.now(timezone.utc).isoformat(),
                             "skipped": body.skipped, "order_mode": body.order_mode}
        task.requested_operation = "assemble"
        task.status = TaskStatus.running
        task.phase = "rendering"
        task.error = ""
        task.order_mode = body.order_mode
        task.stage = "正在合并归档"
        await db.flush()
        await require_no_pending_uploads(db, task.case_id)
        await db.commit()
        task_manager.start(
            task.id,
            run_assemble(
                task.id,
                task.case_id,
                user.org_id,
                user.id,
                body.order_mode,
                body.skipped,
            ),
        )
        await db.refresh(task)
        return _task_out(task)


@router.post("/api/tasks/{task_id}/complete-review", response_model=TaskOut)
async def complete_review(task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if not get_settings().preview_only:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "DOCX 模式请使用归档合并流程")
    if task.status != TaskStatus.awaiting_review:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "task not in review")
    task.status = TaskStatus.awaiting_review
    task.progress = 60.0
    task.stage = "核对已保存，尚未生成归档 PDF"
    task.error = ""
    task.finished_at = None
    await db.commit()
    await db.refresh(task)
    return _task_out(task)


@router.get("/api/tasks/{task_id}/preview-fields/{template_name}")
async def get_preview_fields(task_id: int, template_name: str, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if form_fields_preserved(task.fields,template_name):
        raise HTTPException(409, "已保留原始表单，请查看原件；不重复补填")
    try:
        from ..services.output_derivation import visible_derivation
        preview = build_preview(template_name, task.fields, derived_output=visible_derivation(task),
                                source_manifest=task.source_manifest, issues=task.issues)
        preview["revision"] = task.revision or 1
        changed = await _source_changed(db, task)
        newer = await db.scalar(select(ArchiveTask.id).where(ArchiveTask.case_id == task.case_id, ArchiveTask.id > task.id).limit(1))
        preview["editable"] = (not changed and not newer and not task_manager.is_running(task.id)
                               and task.status in (TaskStatus.awaiting_review, TaskStatus.done)
                               and not await has_unresolved(db, case_id=task.case_id))
        preview["source_changed"] = changed
        # Kept for older preview clients; account settings are not case facts.
        preview["organization_name"] = str((task.fields or {}).get("律师事务所") or "")
        preview_styles = (task.fields or {}).get("_preview_styles") or {}
        preview["styles"] = sanitize_preview_styles(
            template_name, preview_styles.get(template_name) or {}
        )
        preview_custom_values = (task.fields or {}).get("_preview_custom_values") or {}
        preview["custom_values"] = sanitize_preview_custom_values(
            template_name, preview_custom_values.get(template_name) or {}
        )
        return preview
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "系统表类型或内容无效，请刷新表格后重试") from None


@router.put("/api/tasks/{task_id}/preview-fields/{template_name}", response_model=TaskOut)
async def put_preview_fields(body: PreviewFieldsUpdate, task_id: int, template_name: str, user=Depends(get_current_user), db=Depends(get_db)):
    _validate_field_patch(body.values, decisions=False)
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        if form_fields_preserved(task.fields,template_name):
            raise HTTPException(409, "已保留原始表单，请查看原件；不重复补填")
        await require_consistent(db, case_id=task.case_id)
        if task_manager.is_running(task.id) or task.status not in (TaskStatus.awaiting_review, TaskStatus.done):
            raise HTTPException(409, "任务正在处理或不可编辑，请待整理完成后再修改表格")
        if body.expected_revision is not None and body.expected_revision != (task.revision or 1):
            raise HTTPException(409, "表格内容已变化，请刷新后核对；未保存的内容请先保留")
        if await _source_changed(db, task):
            raise HTTPException(409, "材料已变化，请先继续整理后再修改表格")
        if await db.scalar(select(ArchiveTask.id).where(ArchiveTask.case_id == task.case_id, ArchiveTask.id > task.id).limit(1)):
            raise HTTPException(409, "这是历史任务，请在最新任务中修改表格")
        await _recover_field_snapshot(db, task, user.org_id)
        try:
            updates = sanitize_preview_updates(template_name, body.values)
            styles = sanitize_preview_styles(template_name, body.styles)
            custom_values = sanitize_preview_custom_values(template_name, body.custom_values)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "系统表类型或内容无效，请刷新表格后重试") from None
        preview_styles = dict((task.fields or {}).get("_preview_styles") or {})
        if "styles" in body.model_fields_set:
            preview_styles[template_name] = styles
            updates["_preview_styles"] = preview_styles
        preview_custom_values = dict((task.fields or {}).get("_preview_custom_values") or {})
        if "custom_values" in body.model_fields_set:
            preview_custom_values[template_name] = custom_values
            updates["_preview_custom_values"] = preview_custom_values
        task.fields = await _classification_edit(update_task_fields(task, user.org_id, updates, actor_id=user.id))
        await _commit_field_update(db, task, user.org_id)
        return _task_out(task)


@router.get("/api/tasks/{task_id}/preview/{template_name}")
async def preview(task_id: int, template_name: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db), page: int | None = Query(default=None, ge=1)):
    org_id = user.org_id
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if template_name not in SYSTEM_TEMPLATE_NAMES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown template")
    try:
        async with task_manager.case_lock(task.case_id):
            await db.refresh(task)
            await require_consistent(db, case_id=task.case_id)
            revision = getattr(task, "revision", None) or 1
            pdf_path = await preview_template_pdf(task, org_id, template_name)
            if page is not None:
                from ..services.template_raster import raster_template_page
                try:
                    image, page_count = await asyncio.to_thread(raster_template_page, pdf_path, page)
                except IndexError:
                    raise HTTPException(404, '预览页不存在') from None
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "template not ready")
    except Exception as exc:
        from ..services.original_template_service import OriginalTemplateError
        if isinstance(exc, OriginalTemplateError):
            from ..services.safe_errors import ErrorCode, original_template_hint
            code = ErrorCode.ORIGINAL_TEMPLATE_OVERFLOW if exc.code in ("overflow", "page_count", "frame") else ErrorCode.ORIGINAL_TEMPLATE_FAILED
            raise HTTPException(422, public_error(SafeTaskError(code)) + original_template_hint(exc)) from None
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "系统表预览生成失败，请检查本机 PDF 生成器后重试。 [GD_PREVIEW_FAILED]") from None
    await db.refresh(task)
    if revision != (task.revision or 1):
        raise HTTPException(409, "表格内容已变化，请刷新当前预览")
    if page is not None:
        return Response(image, media_type='image/png', headers={
            'X-Task-Revision':str(revision), 'X-Template-Fidelity':'original',
            'X-Template-Page':str(page), 'X-Template-Pages':str(page_count), 'Cache-Control':'no-store'})
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{template_name}.pdf",
                        headers={"X-Task-Revision": str(revision), "X-Template-Fidelity": "original", "Cache-Control": "no-store"})




@router.get("/api/tasks/{task_id}/docx/{template_name}")
async def get_docx(task_id: int, template_name: str, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if original_form_sources(task.fields,template_name):
        raise HTTPException(409, "本案保留原始表单，请从成果包获取原件PDF")
    if template_name not in SYSTEM_TEMPLATE_NAMES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown template")
    try:
        async with task_manager.case_lock(task.case_id):
            await db.refresh(task)
            await require_consistent(db, case_id=task.case_id)
            if task.phase == "artifacts_invalid":
                raise HTTPException(409, task.error)
            if get_settings().preview_only and not has_delivery(task):
                raise HTTPException(409, "请先生成当前修订的完整归档成果，再下载 Word")
            path = get_template_docx_path(task, user.org_id, template_name)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "docx not ready")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{template_name}.docx",
        content_disposition_type="inline",
    )


@router.put("/api/tasks/{task_id}/docx/{template_name}")
async def put_docx(task_id: int, template_name: str, file: UploadFile = File(...), user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if get_settings().preview_only:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "preview-only 模式不保存 docx")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        if original_form_sources(task.fields,template_name):
            raise HTTPException(409, "本案保留原始表单；更换原件请补充上传材料")
        await _require_current_editable(db, task)
        if template_name not in SYSTEM_TEMPLATE_NAMES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown template")
        data = await file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(413, "系统表文件不能超过 20 MB")
        if not data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
        try:
            await _classification_edit(save_template_docx(task, user.org_id, template_name, data))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "系统表文件无法保存，请检查文件格式、大小及是否含外部内容") from None
        await db.commit()
        return {"ok": True, "template": template_name}

@router.post("/api/tasks/{task_id}/refill", response_model=TaskOut)
async def refill(body: FieldUpdate, task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    _validate_field_patch(body.fields, decisions=False)
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    async with task_manager.case_lock(task.case_id):
        await db.refresh(task)
        await _require_current_editable(db, task)
        await _classification_edit(regenerate_templates(task, user.org_id, user.id, body.fields, body.outcome_type))
        invalidate_output(task)
        await _commit_field_update(db, task, user.org_id)
        return _task_out(task)


@router.get("/api/tasks/{task_id}/download/{kind}")
async def download(task_id: int, kind: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = user.org_id
    # Verified historical artifacts remain downloadable even when the editable
    # snapshot needs storage repair. They are validated independently below.
    task = await _load_task_for_user(db, task_id, user, recover_fields=False)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if not has_delivery(task):
        raise HTTPException(409, task.error if task.phase == "artifacts_invalid" else "请先生成最新的完整归档成果")
    if kind == "archive":
        if not task.output_pdf or not os.path.exists(task.output_pdf):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "archive not ready")
        return FileResponse(task.output_pdf, media_type="application/pdf", filename=os.path.basename(task.output_pdf))
    if kind == "docx":
        d = task.output_docx_dir
        if not d or not os.path.isdir(d):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "docx not ready")
        docs = [f for f in os.listdir(d) if f.lower().endswith(".docx")]
        if not docs:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no docx")
        return FileResponse(os.path.join(d, docs[0]), filename=docs[0])
    if kind == "zip":
        package = next((item for item in (task.artifacts or {}).get("artifacts", []) if item.get("key") == "package_zip"), None)
        if not package or not os.path.isfile(package["path"]):
            raise HTTPException(409, "完整归档包缺失，请点击继续归档重新生成")
        return FileResponse(package["path"], filename="档案草稿包.zip" if is_draft(task) else "归档包.zip")
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad kind")


@router.websocket("/api/ws/tasks/{task_id}")
async def task_ws(websocket: WebSocket, task_id: int):
    try:
        await _task_ws(websocket, task_id)
    except WebSocketDisconnect:
        pass
    except Exception:
        logging.getLogger("v6.task").error("error_code=GD_PROGRESS_STREAM_FAILED")
        try:
            if websocket.application_state == WebSocketState.CONNECTED:
                await websocket.send_json({"type": "error", "error": "进度连接暂不可用，请刷新查看已保存状态。 [GD_PROGRESS_STREAM_FAILED]"})
            if websocket.application_state != WebSocketState.DISCONNECTED:
                await websocket.close(code=1011)
        except Exception:
            pass


async def _task_ws(websocket: WebSocket, task_id: int):
    protocols = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",") if item.strip()]
    credentials = [item[len("gd-token."):] for item in protocols if item.startswith("gd-token.")]
    token = credentials[0] if len(credentials) == 1 and "gd-workstation" in protocols else ""
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=4401)
        return
    org = payload.get("org")
    # Select only the public protocol marker; never echo the credential as the
    # negotiated subprotocol or accept credentials from a logged URL query.
    await websocket.accept(subprotocol="gd-workstation")
    async with AsyncSessionLocal() as db:
        active_user = await db.get(User, payload.get("sub"))
        if not active_user or not active_user.is_active or active_user.org_id != org:
            await websocket.close(code=4401)
            return
        task = await _load_task_for_user(db, task_id, active_user)
    if not task:
        await websocket.send_json({"type": "error", "error": "task not found"})
        await websocket.close()
        return
    tracker = task_manager.get_tracker(task_id)
    if not tracker.log_lines and task.log_text:
        tracker.log_lines = filtered_log_lines(task.log_text.splitlines())
    if not task_manager.is_running(task_id):
        tracker.progress, tracker.stage = task.progress, task.stage
    q = await tracker.subscribe()
    try:
        for line in filtered_log_lines(tracker.log_lines)[-200:]:
            await websocket.send_json({"type": "log", "text": line})
        await websocket.send_json({"type": "progress", "progress": tracker.progress, "stage": tracker.stage})
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=25.0)
            except asyncio.TimeoutError:
                msg = {"type": "ping"}
            # A connected account may have been disabled or demoted since the
            # handshake. Do not keep streaming private case logs after that.
            async with AsyncSessionLocal() as db:
                active_user = await db.get(User, payload.get("sub"))
                allowed = (active_user and active_user.is_active and active_user.org_id == org
                           and await _load_task_for_user(db, task_id, active_user))
            if not allowed:
                await websocket.close(code=4403)
                return
            await websocket.send_json(msg)
            mtype = msg.get("type")
            if mtype == "done" or mtype == "error":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await tracker.unsubscribe(q)
        if websocket.application_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except RuntimeError:
                # The peer may disconnect between the state check and close.
                pass


@router.delete("/api/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _load_task_for_user(db, task_id, user)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if task.status not in (TaskStatus.done, TaskStatus.awaiting_review, TaskStatus.failed):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "only completed or review tasks can be deleted")
    remove_task_outputs(task)
    await db.delete(task)
    await db.commit()
    return None
