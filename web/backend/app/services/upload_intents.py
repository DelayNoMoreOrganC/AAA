"""Persistent private upload receipts; no document bytes or automatic retries."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..models import ArchiveTask, CaseFile, TaskStatus, UploadIntent
from .task_manager import task_manager

BUSY = "本案正在整理材料，请处理结束后再导入；已有导入回执仍可查看。"
PENDING = "本案有未完成的导入，请由发起导入的账号补齐或取消后继续。"
CANCELLED = "此待导入项已取消，旧上传请求不能恢复；如需新增请重新选择文件。"
MISMATCH = "重选文件与登记的名称、大小、内容或类型不一致，本次未导入。"
UNAVAILABLE = "已导入材料的回执或文件已缺失、改变，请核对材料列表；旧上传标识不能重新导入。"


@dataclass(frozen=True)
class Scope:
    org_id: str
    user_id: str
    case_id: str


def filters(scope, request_id=None):
    clauses = [UploadIntent.org_id == scope.org_id, UploadIntent.user_id == scope.user_id,
               UploadIntent.case_id == scope.case_id]
    return clauses if request_id is None else [*clauses, UploadIntent.request_id == request_id]


async def get_intent(db, scope, request_id):
    if not request_id:
        return None
    return await db.scalar(select(UploadIntent).where(*filters(scope, request_id)).execution_options(populate_existing=True))


def payload_matches(row, filename, file_size, sha256, doc_type):
    return (row.filename == filename and row.file_size == file_size and row.sha256 == sha256 and row.doc_type == doc_type)


def fingerprint(filename, file_size, sha256, doc_type):
    return hashlib.sha256(json.dumps([filename, doc_type, file_size, sha256], ensure_ascii=False,
                                   separators=(",", ":")).encode("utf-8")).hexdigest()


def check_payload(row, filename, file_size, sha256, doc_type):
    if row is None:
        return
    if row.status == "cancelled":
        raise HTTPException(409, CANCELLED)
    if not payload_matches(row, filename, file_size, sha256, doc_type):
        raise HTTPException(409, MISMATCH)


async def busy(db, case_id):
    rows = list(await db.scalars(select(ArchiveTask).where(ArchiveTask.case_id == case_id)))
    return any(t.status in (TaskStatus.pending, TaskStatus.running) or task_manager.is_running(t.id) for t in rows)


async def require_upload_idle(db, case_id):
    if await busy(db, case_id):
        raise HTTPException(409, BUSY)


async def require_no_pending_uploads(db, case_id):
    # The message deliberately identifies neither another account nor its files.
    if await db.scalar(select(UploadIntent.id).where(UploadIntent.case_id == case_id,
                                                  UploadIntent.status == "pending").limit(1)):
        raise HTTPException(409, PENDING)


async def receipt(db, scope, request_id):
    return await db.scalar(select(CaseFile).where(CaseFile.case_id == scope.case_id,
        CaseFile.upload_owner_id == scope.user_id, CaseFile.upload_request_id == request_id))


async def verified_receipt(db, scope, row, case_dir):
    from ..routers.cases import _verify_upload_replay
    cf = await receipt(db, scope, row.request_id)
    if cf is None or (row.file_id is not None and cf.id != row.file_id):
        raise HTTPException(409, UNAVAILABLE)
    try:
        await asyncio.to_thread(_verify_upload_replay, cf,
            fingerprint(row.filename, row.file_size, row.sha256, row.doc_type), case_dir, row.sha256)
    except HTTPException:
        raise HTTPException(409, UNAVAILABLE) from None
    return cf


def output(row, *, projected_status=None):
    def iso(value):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return {"request_id": row.request_id, "filename": row.filename, "file_size": row.file_size,
        "sha256": row.sha256, "doc_type": row.doc_type, "status": projected_status or row.status,
        "file_id": row.file_id, "created_at": iso(row.created_at), "updated_at": iso(row.updated_at)}


async def project(db, scope, row, case_dir):
    if row.status == "completed":
        try:
            await verified_receipt(db, scope, row, case_dir)
        except HTTPException:
            return output(row, projected_status="unavailable")
    return output(row)


async def mark_complete(db, scope, request_id, file_id, filename, file_size, sha256, doc_type):
    """No commit: the source receipt and state transition must commit together."""
    row = await get_intent(db, scope, request_id)
    if row is None:
        return False  # Backwards-compatible unregistered upload.
    check_payload(row, filename, file_size, sha256, doc_type)
    if row.status == "completed":
        if row.file_id != file_id:
            raise HTTPException(409, UNAVAILABLE)
        return False
    result = await db.execute(update(UploadIntent).where(*filters(scope, request_id), UploadIntent.status == "pending")
        .values(status="completed", file_id=file_id, updated_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(409, CANCELLED)
    return True


async def register(db, scope, request_id, payload, case_dir):
    existing = await get_intent(db, scope, request_id)
    if existing is not None:
        if not payload_matches(existing, **payload):
            raise HTTPException(409, MISMATCH)
        return await project(db, scope, existing, case_dir)
    await require_upload_idle(db, scope.case_id)
    row = UploadIntent(org_id=scope.org_id, user_id=scope.user_id, case_id=scope.case_id,
                       request_id=request_id, **payload)
    db.add(row)
    try:
        # Acquiring the DB write lock before checking legacy receipts serializes
        # this registration against another worker committing the same upload.
        await db.flush()
        await require_upload_idle(db, scope.case_id)
        cf = await receipt(db, scope, request_id)
        if cf is not None:
            row.file_id = cf.id
            await verified_receipt(db, scope, row, case_dir)
            row.status = "completed"
        await db.commit()
    except IntegrityError:
        await db.rollback()
        winner = await get_intent(db, scope, request_id)
        if winner is None or not payload_matches(winner, **payload):
            raise HTTPException(409, MISMATCH) from None
        return await project(db, scope, winner, case_dir)
    return await project(db, scope, row, case_dir)


async def cancel(db, scope, request_id, case_dir):
    row = await get_intent(db, scope, request_id)
    if row is None:
        raise HTTPException(404, "待导入项不存在")
    if row.status == "cancelled":
        return output(row)
    if row.status != "pending":
        raise HTTPException(409, "此项已导入，取消待办不会删除材料；请在材料列表核对。")
    changed = await db.execute(update(UploadIntent).where(*filters(scope, request_id), UploadIntent.status == "pending")
        .values(status="cancelled", updated_at=datetime.now(timezone.utc)).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        await db.rollback()
        latest = await get_intent(db, scope, request_id)
        if latest is not None and latest.status == "cancelled":
            return output(latest)
        raise HTTPException(409, "此项状态已变化，请刷新待导入清单。")
    await db.commit()
    return output(await get_intent(db, scope, request_id))
