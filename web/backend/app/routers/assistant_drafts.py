"""Private draft persistence independent from assistant/model execution."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..case_access import case_access_filter
from ..database import get_db
from ..deps import get_current_user
from ..models import ArchiveTask, Case
from ..services import assistant_draft as store
from ..services.task_manager import task_manager
from .tasks import _source_changed

router = APIRouter(tags=["assistant-drafts"])


class DraftPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(strict=True, max_length=1500)
    expected_version: int = Field(strict=True, ge=0, le=9007199254740990)
    expected_revision: int = Field(strict=True, ge=1, le=9007199254740991)
    source_version: str = Field(strict=True, max_length=64)


async def _authorized_task(db, task_id, user):
    task = await db.scalar(select(ArchiveTask).join(Case, ArchiveTask.case_id == Case.id)
        .where(ArchiveTask.id == task_id, case_access_filter(user)).execution_options(populate_existing=True))
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


async def _availability(db, task):
    newer = await db.scalar(select(ArchiveTask.id).where(ArchiveTask.case_id == task.case_id,
                                                      ArchiveTask.id > task.id).limit(1))
    if newer is not None:
        return False, "这是历史任务，未发送文字仍可查看；请在最新任务中继续。"
    if await _source_changed(db, task):
        return False, "材料已变化，未发送文字仍保留；请继续整理后在当前任务中核对。"
    return True, ""


@router.get("/api/tasks/{task_id}/assistant/draft")
async def get_draft(task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _authorized_task(db, task_id, user)
    scope = store.DraftScope(user.org_id, user.id, task.case_id, task.id)
    async with task_manager.case_lock(task.case_id):
        task = await _authorized_task(db, task_id, user)
        writable, notice = await _availability(db, task)
        row = await store.read_draft(db, scope)
        return store.response(row, task_revision=task.revision or 1,
            task_source_version=task.source_version or "", writable=writable, notice=notice)


@router.put("/api/tasks/{task_id}/assistant/draft")
async def put_draft(body: DraftPut, task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await _authorized_task(db, task_id, user)
    scope = store.DraftScope(user.org_id, user.id, task.case_id, task.id)
    async with task_manager.case_lock(task.case_id):
        task = await _authorized_task(db, task_id, user)
        writable, notice = await _availability(db, task)
        revision, source_version = task.revision or 1, task.source_version or ""
        if not writable:
            raise HTTPException(409, notice)
        if body.expected_revision != revision or body.source_version != source_version:
            raise HTTPException(409, store.CONTEXT_CHANGED)
        try:
            row = await store.write_draft(db, scope, content=body.content,
                expected_version=body.expected_version, revision=revision, source_version=source_version)
        except store.DraftConflict as exc:
            raise HTTPException(409, str(exc)) from None
        return store.response(row, task_revision=revision, task_source_version=source_version,
                              writable=True)
