"""Permission checked evidence links and server-rendered source page previews."""
import asyncio
import os
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from ..database import get_db
from ..case_access import case_access_filter
from ..deps import get_current_user
from ..models import ArchiveTask, Case, CaseFile
from ..services.evidence_links import supporting_refs

router = APIRouter(tags=["evidence"])


@router.get("/api/tasks/{task_id}/evidence")
async def evidence(task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = await db.scalar(select(ArchiveTask).join(Case).where(ArchiveTask.id==task_id, case_access_filter(user)))
    if task is None:
        raise HTTPException(404, "任务不存在")
    files = (await db.execute(select(CaseFile).where(CaseFile.case_id==task.case_id))).scalars().all()
    mapping = {os.path.normcase(os.path.abspath(f.abs_path)): f for f in files}
    out = {}
    for field, refs in ((task.fields or {}).get("_provenance") or {}).items():
        if not isinstance(refs, list):
            continue
        refs = [x for x in refs if isinstance(x, dict)]
        latest_human = next((x for x in reversed(refs) if x.get("method") == "human"), None)
        if latest_human:
            out.setdefault(field, []).append({"method":"human","value":latest_human.get("value"),
                "edited_at":latest_human.get("edited_at"),"filename":"人工填写","page":None,"quote":"人工修改，以下原文仅供历史参考", "url":None})
        expanded = []
        for item in refs:
            supports = supporting_refs(item, task.fields or {}, task.source_manifest or [])
            expanded.append((item, supports is None, None))
            for support in supports or []:
                expanded.append((support, False, "client_identity"))
        seen = set()
        for item, stale_link, source_role in expanded:
            source = mapping.get(os.path.normcase(os.path.abspath(item.get("source_path", ""))))
            if source:
                identity = (source.id, item.get("page", 1), item.get("quote", ""), source_role)
                if identity in seen:
                    continue
                seen.add(identity)
                out.setdefault(field, []).append({"file_id":source.id, "filename":source.filename,
                    "page":item.get("page",1), "quote":item.get("quote", ""), "method":item.get("method",""),
                    "value":item.get("value"), "historical":bool(latest_human) or stale_link,
                    "source_role":source_role,
                    "url":f"/api/cases/{task.case_id}/files/{source.id}/page/{item.get('page',1)}"})
    return {"fields":out}


@router.get("/api/cases/{case_id}/files/{file_id}/page/{page_number}")
async def source_page(case_id: str, file_id: str, page_number: int, user=Depends(get_current_user), db=Depends(get_db)):
    source = await db.scalar(select(CaseFile).join(Case).where(CaseFile.id==file_id, CaseFile.case_id==case_id, case_access_filter(user)))
    if not source:
        raise HTTPException(404, "材料不存在")
    def render():
        import fitz
        with fitz.open(source.abs_path) as document:
            if not 1 <= page_number <= len(document):
                raise HTTPException(404, "页码不存在")
            return document[page_number-1].get_pixmap(matrix=fitz.Matrix(1.5,1.5), alpha=False).tobytes("png")
    return Response(await asyncio.to_thread(render), media_type="image/png", headers={"Cache-Control":"no-store"})
