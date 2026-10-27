"""Private resumable upload metadata, never source bytes."""
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..case_access import case_access_filter
from ..database import get_db
from ..deps import get_current_user
from ..models import Case, UploadIntent
from ..services import upload_intents as store
from ..services.doc_type_service import list_upload_doc_types
from ..services.file_import_service import ImportFailure, check_extension, display_filename
from ..services.task_manager import task_manager

router = APIRouter(prefix="/api/cases", tags=["upload-intents"])


class IntentPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(strict=True, min_length=1, max_length=250)
    file_size: int = Field(strict=True, gt=0)
    sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    doc_type: str = Field(default="default", strict=True, max_length=50)


async def authorized(db, case_id, user):
    row = await db.scalar(select(Case).where(Case.id == case_id, case_access_filter(user)))
    if row is None:
        raise HTTPException(404, "案件不存在")
    return row


def request_key(key):
    import re
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
        raise HTTPException(400, "上传标识无效，请重新选择文件。")


def case_dir(scope):
    from .cases import ORGS_DIR
    return Path(ORGS_DIR) / scope.org_id / "cases" / scope.case_id


@router.get("/{case_id}/upload-intents")
async def list_intents(case_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    await authorized(db, case_id, user)
    scope = store.Scope(user.org_id, user.id, case_id)
    async with task_manager.case_lock(case_id):
        await authorized(db, case_id, user)
        rows = list(await db.scalars(select(UploadIntent).where(*store.filters(scope))
            .order_by(UploadIntent.created_at, UploadIntent.id)))
        items = [await store.project(db, scope, row, case_dir(scope)) for row in rows]
        writable = not await store.busy(db, case_id)
        return {"items":items, "writable":writable, "notice":"" if writable else store.BUSY}


@router.put("/{case_id}/upload-intents/{request_id}")
async def put_intent(case_id: str, request_id: str, body: IntentPut, user=Depends(get_current_user), db=Depends(get_db)):
    scope = store.Scope(user.org_id, user.id, case_id)
    async with task_manager.case_lock(case_id):
        case = await authorized(db, case_id, user)
        request_key(request_id)
        from .cases import _settings
        if body.file_size > _settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, "文件超出上传大小限制，请拆分后重新选择。")
        if body.doc_type not in {item["value"] for item in list_upload_doc_types(case.case_type)}:
            raise HTTPException(400, "材料类型无效，请重新选择。")
        try:
            if display_filename(body.filename) != body.filename:
                raise ImportFailure("请使用不含路径或控制字符的文件名重新选择。")
            check_extension(body.filename)
        except ImportFailure as exc:
            raise HTTPException(exc.status_code, str(exc)) from None
        return await store.register(db, scope, request_id, body.model_dump(), case_dir(scope))


@router.delete("/{case_id}/upload-intents/{request_id}")
async def cancel_intent(case_id: str, request_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    scope = store.Scope(user.org_id, user.id, case_id)
    async with task_manager.case_lock(case_id):
        await authorized(db, case_id, user)
        request_key(request_id)
        return await store.cancel(db, scope, request_id, case_dir(scope))
