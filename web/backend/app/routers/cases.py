"""Case + case-file CRUD with org isolation."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import ORGS_DIR, get_settings
from ..database import get_db
from ..case_access import case_access_filter
from ..deps import get_current_user
from ..models import ArchiveTask, Case, CaseFile, TaskStatus, Role, CaseType
from ..schemas import CaseCreate, CaseDetail, CaseFileOut, CaseFileUpdate, CaseOut, DocTypeOption
from ..services.doc_type_service import list_upload_doc_types
from ..services.task_manager import task_manager
from ..services import case_deletion
from ..services import upload_intents
from ..services.file_import_service import (
    ImportFailure,
    check_extension,
    display_filename,
    import_capabilities,
    normalize_import,
    original_file,
    owned_import_directory,
)

router = APIRouter(prefix="/api/cases", tags=["cases"])

_settings = get_settings()


async def _latest_task_summary(task, user, db):
    if not task:
        return None
    # Reuse the task endpoint's ownership, current-source and artifact checks.
    # All three screens must agree even after an output file is lost.
    from .tasks import get_task
    from ..schemas import CaseTaskSummary
    current = await get_task(task.id, user=user, db=db)
    return CaseTaskSummary(**{name: getattr(current, name) for name in CaseTaskSummary.model_fields})


def _org_case_dir(org_id, case_id):
    d = os.path.join(str(ORGS_DIR), org_id, "cases", case_id)
    os.makedirs(d, exist_ok=True)
    return d


@router.get("/meta/doc-types", response_model=list[DocTypeOption])
async def get_doc_types(case_type: CaseType = CaseType.civil, user=Depends(get_current_user)):
    return list_upload_doc_types(case_type.value)


@router.get("/meta/import-capabilities")
async def get_import_capabilities(user=Depends(get_current_user)):
    return import_capabilities(_settings.max_upload_mb)


@router.get("", response_model=list[CaseOut])
async def list_cases(user=Depends(get_current_user), db=Depends(get_db)):
    res = await db.execute(select(Case).where(case_access_filter(user)).order_by(Case.created_at.desc()))
    cases = res.scalars().all()
    out = []
    for c in cases:
        files = await db.execute(select(CaseFile).where(CaseFile.case_id == c.id))
        file_count = len(files.scalars().all())
        task_res = await db.execute(select(ArchiveTask).where(ArchiveTask.case_id == c.id).order_by(ArchiveTask.created_at.desc()).limit(1))
        last_task = task_res.scalars().first()
        summary = await _latest_task_summary(last_task, user, db)
        out.append(CaseOut(id=c.id, title=c.title, case_type=c.case_type, stage=c.stage, created_at=c.created_at.isoformat(), file_count=file_count, last_task_status=summary.status if summary else None, last_task_id=last_task.id if last_task else None, last_task_summary=summary))
    return out


@router.post("", response_model=CaseOut, status_code=201)
async def create_case(body: CaseCreate, user=Depends(get_current_user), db=Depends(get_db)):
    case = Case(title=body.title, case_type=body.case_type.value, stage=body.stage, org_id=user.org_id, created_by=user.id)
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return CaseOut(id=case.id, title=case.title, case_type=case.case_type, stage=case.stage, created_at=case.created_at.isoformat(), file_count=0, last_task_status=None)


@router.get("/{case_id}", response_model=CaseDetail)
async def get_case(case_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    res = await db.execute(select(Case).where(Case.id == case_id, case_access_filter(user)))
    case = res.scalar_one_or_none()
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    fres = await db.execute(select(CaseFile).where(CaseFile.case_id == case_id).order_by(CaseFile.created_at))
    files = fres.scalars().all()
    task_res = await db.execute(select(ArchiveTask).where(ArchiveTask.case_id == case_id).order_by(ArchiveTask.created_at.desc()).limit(1))
    last_task = task_res.scalars().first()
    summary = await _latest_task_summary(last_task, user, db)
    file_list = [CaseFileOut(id=f.id, filename=f.filename, doc_type=f.doc_type, file_size=f.file_size, created_at=f.created_at.isoformat()) for f in files]
    all_tasks = await db.execute(
        select(ArchiveTask).where(ArchiveTask.case_id == case_id).order_by(ArchiveTask.created_at.desc())
    )
    done_task_list = []
    for t in all_tasks.scalars().all():
        from ..services.delivery_state import has_delivery
        if has_delivery(t):
            from ..schemas import TaskBriefOut
            from .tasks import get_task
            current = await get_task(t.id, user=user, db=db)
            if not current.has_archive:
                continue
            done_task_list.append(TaskBriefOut(
                id=t.id,
                status=current.status,
                finished_at=t.finished_at.isoformat() if t.finished_at else None,
                output_pdf=t.output_pdf or "",
                preview_only=_settings.preview_only,
                has_docx=current.has_docx,
                delivery_kind=current.delivery_kind,
                revision=t.revision or 1,
            ))
    return CaseDetail(
        id=case.id, title=case.title, case_type=case.case_type, stage=case.stage,
        created_at=case.created_at.isoformat(), file_count=len(files),
        last_task_status=summary.status if summary else None,
        last_task_id=last_task.id if last_task else None,
        last_task_summary=summary,
        files=file_list, done_tasks=done_task_list,
    )


@router.delete("/{case_id}", status_code=204)
async def delete_case(case_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    lock = task_manager.case_lock(case_id)
    if lock.locked():
        raise HTTPException(409, "案件正在处理或保存，请稍后再删除。")
    async with lock:
        case = await db.scalar(select(Case).where(Case.id == case_id, case_access_filter(user)))
        try:
            case_dir, stage = case_deletion.checked_paths(ORGS_DIR, user.org_id, case_id)
            if not case:
                record = case_deletion.read_record(stage, user.org_id, case_id)
                # Cleanup retries carry exactly the original case ownership.
                if not record or not (user.role == Role.admin or record["created_by"] == user.id):
                    raise HTTPException(404, "case not found")
                # Never treat a currently existing but inaccessible case as a retry.
                if await db.get(Case, case_id) is not None:
                    raise HTTPException(404, "case not found")
            else:
                tasks = list((await db.scalars(select(ArchiveTask).where(ArchiveTask.case_id == case_id))).all())
                if any(t.status in (TaskStatus.pending, TaskStatus.running) or task_manager.is_running(t.id) for t in tasks):
                    raise HTTPException(409, "案件仍有排队、处理或恢复中的任务，请任务结束后再删除。")
                for task in tasks:
                    saved = (task.fields or {}).get("_saved_to")
                    if saved and Path(saved).resolve().is_relative_to(case_dir.resolve()):
                        raise HTTPException(409, "指定成果保存目录与案件工作目录重叠，暂不能安全删除。")
                await asyncio.to_thread(case_deletion.stage_case, case_dir, stage,
                                        org_id=user.org_id, case_id=case_id, created_by=case.created_by)
                try:
                    from ..models import AssistantDraft, AssistantTurn, UploadIntent
                    await db.execute(delete(UploadIntent).where(UploadIntent.case_id == case_id))
                    await db.execute(delete(AssistantDraft).where(AssistantDraft.case_id == case_id))
                    await db.execute(delete(AssistantTurn).where(AssistantTurn.case_id == case_id))
                    await db.execute(delete(CaseFile).where(CaseFile.case_id == case_id))
                    await db.execute(delete(ArchiveTask).where(ArchiveTask.case_id == case_id))
                    await db.execute(delete(Case).where(Case.id == case_id))
                    await db.commit()
                except Exception:
                    await db.rollback()
                    await asyncio.to_thread(case_deletion.restore_staged, case_dir, stage)
                    raise HTTPException(503, "删除未完成，案件记录和材料已保留，请稍后重试。") from None
            try:
                await asyncio.to_thread(case_deletion.finish_cleanup, stage)
            except (OSError, case_deletion.DeletionStorageError):
                return JSONResponse(status_code=202, content={"deleted": True, "cleanup_pending": True,
                    "message": "案件已从列表删除，但本机暂存副本尚未清理完成；请重试清理。外部原始来源和指定保存目录副本未删除。"})
        except (OSError, case_deletion.DeletionStorageError):
            raise HTTPException(409, "案件文件正在使用或目录状态异常，删除未完成；已保存资料保留，请稍后重试。") from None
    return None


@router.post("/{case_id}/files", response_model=CaseFileOut)
async def upload_file(case_id: str, doc_type: str = Form("default"), file: UploadFile = File(...),
                      idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
                      user=Depends(get_current_user), db=Depends(get_db)):
    async with task_manager.case_lock(case_id):
        return await _upload_file_locked(case_id, doc_type, file, user, db, idempotency_key)


def _file_out(cf):
    return CaseFileOut(id=cf.id, filename=cf.filename, doc_type=cf.doc_type,
                       file_size=cf.file_size, created_at=cf.created_at.isoformat())


async def _upload_receipt(db, case_id, owner_id, request_id):
    return await db.scalar(select(CaseFile).where(CaseFile.case_id == case_id,
        CaseFile.upload_owner_id == owner_id, CaseFile.upload_request_id == request_id))


def _verify_upload_replay(cf, fingerprint, case_dir, raw_sha256):
    if cf.upload_fingerprint != fingerprint:
        raise HTTPException(409, "此上传标识已用于另一份材料，请保留原任务并重新选择文件。")
    try:
        normalized = Path(ORGS_DIR) / cf.stored_name
        if not normalized.resolve().is_relative_to(case_dir.resolve()) or not normalized.is_file():
            raise ValueError("unavailable receipt")
        with normalized.open("rb") as stream:
            pdf_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if not cf.upload_pdf_sha256 or pdf_digest != cf.upload_pdf_sha256:
            raise ValueError("changed normalized receipt")
        original = original_file(case_dir, normalized)
        with original.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != raw_sha256:
            raise ValueError("changed receipt")
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(409, "此前导入的材料已缺失或改变，请检查材料列表后重新导入。") from None


def _cleanup_owned_upload(case_dir, original):
    owned = owned_import_directory(case_dir, original)
    if owned is not None:
        shutil.rmtree(owned, ignore_errors=True)


async def _upload_file_locked(case_id, doc_type, file, user, db, request_id=None):
    # Rollback expires ORM-loaded user attributes. Keep trusted scalar identity
    # before a transaction failure so receipt recovery never triggers lazy IO.
    owner_id, org_id = user.id, user.org_id
    res = await db.execute(select(Case).where(Case.id == case_id, case_access_filter(user)))
    case = res.scalar_one_or_none()
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if request_id is not None and not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request_id):
        raise HTTPException(400, "上传标识无效，请重新选择文件。")
    if doc_type not in {item["value"] for item in list_upload_doc_types(case.case_type)}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "材料类型无效，请重新选择。")
    try:
        safe = display_filename(file.filename)
        extension = check_extension(safe)
    except ImportFailure as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    intent_scope = upload_intents.Scope(org_id, owner_id, case_id)
    intent = await upload_intents.get_intent(db, intent_scope, request_id)
    if intent is not None and intent.status == "cancelled":
        raise HTTPException(409, upload_intents.CANCELLED)
    prior = await _upload_receipt(db, case_id, owner_id, request_id) if request_id else None
    if intent is not None and intent.status == "completed" and (prior is None or prior.id != intent.file_id):
        raise HTTPException(409, upload_intents.UNAVAILABLE)
    if prior is None:
        await upload_intents.require_upload_idle(db, case_id)
    case_dir = Path(_org_case_dir(org_id, case_id))
    import_dir = case_dir / "imports" / uuid.uuid4().hex
    import_dir.mkdir(parents=True, exist_ok=False)
    original = import_dir / ("original" + extension)
    size = 0
    raw_digest = hashlib.sha256()
    fingerprint = None
    stored_name = None
    commit_started = False
    try:
        # Bound memory use and stop reading when the configured limit is reached.
        with original.open("xb") as destination:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > _settings.max_upload_mb * 1024 * 1024:
                    raise ImportFailure(f"文件超过 {_settings.max_upload_mb} MB，请拆分后上传。", 413)
                destination.write(chunk)
                raw_digest.update(chunk)
        if not size:
            raise ImportFailure("文件为空，请检查后重新上传。")
        upload_intents.check_payload(intent, safe, size, raw_digest.hexdigest(), doc_type)
        if request_id:
            fingerprint = hashlib.sha256(json.dumps(
                [safe, doc_type, size, raw_digest.hexdigest()], ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            existing = await _upload_receipt(db, case_id, owner_id, request_id)
            if existing is not None:
                await asyncio.to_thread(_verify_upload_replay, existing, fingerprint, case_dir, raw_digest.hexdigest())
                if await upload_intents.mark_complete(db, intent_scope, request_id, existing.id,
                        safe, size, raw_digest.hexdigest(), doc_type):
                    await db.commit()
                _cleanup_owned_upload(case_dir, original)
                return _file_out(existing)
        pdf = await asyncio.to_thread(normalize_import, original, safe)
        stored_name = str(pdf.relative_to(Path(ORGS_DIR)))
        with pdf.open("rb") as stream:
            pdf_sha256 = hashlib.file_digest(stream, "sha256").hexdigest() if request_id else None
        cf = CaseFile(case_id=case_id, filename=safe, stored_name=stored_name, doc_type=doc_type, file_size=size,
                      upload_owner_id=owner_id if request_id else None,
                      upload_request_id=request_id, upload_fingerprint=fingerprint, upload_pdf_sha256=pdf_sha256)
        db.add(cf)
        commit_started = True
        # A DB write lock now serializes final completion against another
        # worker's cancel. Both records commit or neither is accepted.
        await db.flush()
        await upload_intents.require_upload_idle(db, case_id)
        await upload_intents.mark_complete(db, intent_scope, request_id, cf.id,
            safe, size, raw_digest.hexdigest(), doc_type)
        await db.commit()
    except BaseException as exc:
        await db.rollback()
        # A different worker may have committed the same receipt while this
        # worker normalized the file. Also handle commit success followed by a
        # lost acknowledgement: do not delete the committed original.
        cleanup = not commit_started
        if commit_started:
            try:
                existing = (await _upload_receipt(db, case_id, owner_id, request_id) if request_id else
                            await db.scalar(select(CaseFile).where(CaseFile.case_id == case_id, CaseFile.stored_name == stored_name)))
                cleanup = existing is None or existing.stored_name != stored_name
                if existing is not None and request_id:
                    latest_intent = await upload_intents.get_intent(db, intent_scope, request_id)
                    upload_intents.check_payload(latest_intent, safe, size, raw_digest.hexdigest(), doc_type)
                    if latest_intent is not None and latest_intent.status == "completed" and latest_intent.file_id != existing.id:
                        raise HTTPException(409, upload_intents.UNAVAILABLE)
                    await asyncio.to_thread(_verify_upload_replay, existing, fingerprint, case_dir, raw_digest.hexdigest())
                    if cleanup:
                        _cleanup_owned_upload(case_dir, original)
                    return _file_out(existing)
            except HTTPException:
                if cleanup:
                    _cleanup_owned_upload(case_dir, original)
                raise
            except Exception:
                # Unknown commit state: retain the owned directory, never risk
                # deleting bytes that a committed database row may reference.
                cleanup = False
        # The path is a generated direct child of this case's imports directory.
        if cleanup:
            _cleanup_owned_upload(case_dir, original)
        if isinstance(exc, ImportFailure):
            raise HTTPException(exc.status_code, str(exc)) from exc
        raise
    finally:
        await file.close()
    await db.refresh(cf)
    return _file_out(cf)


@router.get("/{case_id}/files/{file_id}/original")
async def download_original(case_id: str, file_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    result = await db.execute(
        select(CaseFile).join(Case).where(
            CaseFile.id == file_id, CaseFile.case_id == case_id, case_access_filter(user),
        )
    )
    cf = result.scalar_one_or_none()
    if not cf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    case_dir = Path(ORGS_DIR) / user.org_id / "cases" / case_id
    try:
        path = original_file(case_dir, Path(ORGS_DIR) / cf.stored_name)
    except (FileNotFoundError, ValueError, KeyError, OSError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "原件不可用")
    return FileResponse(str(path), filename=cf.filename, media_type="application/octet-stream")


@router.patch("/{case_id}/files/{file_id}", response_model=CaseFileOut)
async def update_file(case_id: str, file_id: str, body: CaseFileUpdate, user=Depends(get_current_user), db=Depends(get_db)):
    async with task_manager.case_lock(case_id):
        return await _update_file_locked(case_id, file_id, body, user, db)


async def _update_file_locked(case_id, file_id, body, user, db):
    res = await db.execute(select(Case).where(Case.id == case_id, case_access_filter(user)))
    case = res.scalar_one_or_none()
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if body.doc_type not in {item["value"] for item in list_upload_doc_types(case.case_type)}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "材料类型无效，请重新选择。")
    fres = await db.execute(select(CaseFile).where(CaseFile.id == file_id, CaseFile.case_id == case_id))
    cf = fres.scalar_one_or_none()
    if not cf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    cf.doc_type = body.doc_type
    await db.commit()
    await db.refresh(cf)
    return CaseFileOut(id=cf.id, filename=cf.filename, doc_type=cf.doc_type, file_size=cf.file_size, created_at=cf.created_at.isoformat())


@router.delete("/{case_id}/files/{file_id}", status_code=204)
async def delete_file(case_id: str, file_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    async with task_manager.case_lock(case_id):
        return await _delete_file_locked(case_id, file_id, user, db)


async def _delete_file_locked(case_id, file_id, user, db):
    res = await db.execute(
        select(CaseFile).join(Case).where(
            CaseFile.id == file_id, CaseFile.case_id == case_id, case_access_filter(user),
        )
    )
    cf = res.scalar_one_or_none()
    if not cf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    retained_task = await db.scalar(
        select(ArchiveTask.id).where(
            ArchiveTask.case_id == case_id,
            ArchiveTask.status.in_((TaskStatus.pending, TaskStatus.running, TaskStatus.awaiting_review, TaskStatus.done, TaskStatus.failed)),
        ).limit(1)
    )
    if retained_task is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "此材料仍被归档任务使用。请先处理或删除相关归档任务，再删除材料。")
    case_dir = Path(ORGS_DIR) / user.org_id / "cases" / case_id
    stored_path = Path(ORGS_DIR) / cf.stored_name
    owned = owned_import_directory(case_dir, stored_path)
    try:
        if owned:
            shutil.rmtree(owned)
        elif stored_path.resolve().is_relative_to(case_dir.resolve()):
            stored_path.unlink(missing_ok=True)
        else:
            raise HTTPException(status.HTTP_409_CONFLICT, "材料路径异常，无法删除。")
    except OSError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "材料正在使用或无法删除，请稍后重试。") from exc
    await db.delete(cf)
    await db.commit()
    return None
