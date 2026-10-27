"""Versioned unsent text. No model, snapshot, business-field or log writes."""
from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

from sqlalchemy import insert, literal, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from ..models import ArchiveTask, AssistantDraft


CONFLICT = "未发送草稿已在另一处更新，请重新读取并选择保留的内容；本次没有覆盖。"
CONTEXT_CHANGED = "任务或材料版本已变化，请读取当前草稿并核对上下文后再保存。"


class DraftConflict(Exception):
    """Fixed safe notice; never include draft content or SQL diagnostics."""
    def __init__(self, *, context=False):
        super().__init__(CONTEXT_CHANGED if context else CONFLICT)


@dataclass(frozen=True)
class DraftScope:
    org_id: str
    user_id: str
    case_id: str
    task_id: int


def scope_filter(scope):
    return (AssistantDraft.org_id == scope.org_id, AssistantDraft.user_id == scope.user_id,
            AssistantDraft.case_id == scope.case_id, AssistantDraft.task_id == scope.task_id)


async def read_draft(db, scope):
    return await db.scalar(select(AssistantDraft).where(*scope_filter(scope)).execution_options(populate_existing=True))


def same_value(row, content, revision, source_version):
    return (row.content == content and row.revision == revision and row.source_version == source_version)


def replay_matches(row, expected_version, content, revision, source_version):
    # A later unrelated version must never be treated as this request's ACK.
    return (row is not None and row.version == expected_version + 1
            and same_value(row, content, revision, source_version))


def current_context(scope, revision, source_version):
    # Keep the CAS valid when another worker updates or supersedes the task.
    later_task = aliased(ArchiveTask)
    newer = select(later_task.id).where(later_task.case_id == scope.case_id,
                                       later_task.id > scope.task_id).exists()
    return select(ArchiveTask.id).where(ArchiveTask.id == scope.task_id,
        ArchiveTask.case_id == scope.case_id, ArchiveTask.revision == revision,
        ArchiveTask.source_version == source_version, ~newer).exists()


async def write_draft(db, scope, *, content, expected_version, revision, source_version):
    """Caller validates ownership/current source under the local case lock.

    SQL version predicates and the unique scope constraint also protect against
    independent server processes. The supplied scope contains trusted scalars.
    """
    row = await read_draft(db, scope)
    if not await db.scalar(select(current_context(scope, revision, source_version))):
        raise DraftConflict(context=True)
    if replay_matches(row, expected_version, content, revision, source_version):
        return row
    if (row is None and expected_version != 0) or (row is not None and row.version != expected_version):
        raise DraftConflict()
    now = datetime.now(timezone.utc)
    if row is None:
        # Empty first saves still create version 1, preventing version-0 tabs
        # from resurrecting an older value after a deliberate clear.
        try:
            result = await db.execute(insert(AssistantDraft).from_select(
                ["id", "org_id", "user_id", "case_id", "task_id", "content", "version", "revision", "source_version", "updated_at"],
                select(literal(uuid.uuid4().hex), literal(scope.org_id), literal(scope.user_id), literal(scope.case_id),
                       literal(scope.task_id), literal(content), literal(1), literal(revision), literal(source_version), literal(now))
                    .where(current_context(scope, revision, source_version))))
            if result.rowcount != 1:
                await db.rollback()
                raise DraftConflict(context=True)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            winner = await read_draft(db, scope)
            if await db.scalar(select(current_context(scope, revision, source_version))) and replay_matches(
                    winner, expected_version, content, revision, source_version):
                return winner
            raise DraftConflict() from None
        return await read_draft(db, scope)
    result = await db.execute(update(AssistantDraft).where(*scope_filter(scope),
        AssistantDraft.version == expected_version, current_context(scope, revision, source_version))
        .values(content=content, version=expected_version + 1, revision=revision,
                source_version=source_version, updated_at=now, consumed_request_id=None).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        winner = await read_draft(db, scope)
        if await db.scalar(select(current_context(scope, revision, source_version))) and replay_matches(
                winner, expected_version, content, revision, source_version):
            return winner
        raise DraftConflict()
    await db.commit()
    return await read_draft(db, scope)


async def consume_draft(db, scope, *, draft_version, revision, source_version, message, request_id):
    """Consume only the exact sent draft in the caller's pending-turn transaction.

    No commit here: reservation failure must roll back both the turn and the
    tombstone. A changed/missing draft never blocks an otherwise valid question.
    """
    if draft_version is None:
        return False
    row = await read_draft(db, scope)
    if (row is None or row.version != draft_version or row.revision != revision
            or row.source_version != source_version or row.content.strip() != message):
        return False
    result = await db.execute(update(AssistantDraft).where(*scope_filter(scope),
        AssistantDraft.version == draft_version, AssistantDraft.content == row.content,
        AssistantDraft.revision == revision, AssistantDraft.source_version == source_version)
        .values(content="", version=draft_version + 1, consumed_request_id=request_id,
                updated_at=datetime.now(timezone.utc)).execution_options(synchronize_session=False))
    return result.rowcount == 1


def response(row, *, task_revision, task_source_version, writable, notice=""):
    updated = row.updated_at if row is not None else None
    if updated is not None and updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    if (not notice and row is not None and
            (row.revision != task_revision or row.source_version != task_source_version)):
        notice = "这段未发送文字保存于较早的任务或材料版本，请核对上下文后再继续编辑。"
    return {"content": row.content if row is not None else "", "version": row.version if row is not None else 0,
        "revision": row.revision if row is not None else task_revision,
        "source_version": row.source_version if row is not None else task_source_version,
        "updated_at": updated.isoformat() if updated is not None else None,
        "consumed_request_id": row.consumed_request_id if row is not None else None,
        "task_revision": task_revision, "task_source_version": task_source_version,
        "writable": writable, "notice": notice}
