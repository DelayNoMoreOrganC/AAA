"""Authenticated, isolated synthetic cases use the regular import and model pipeline."""
import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import ORGS_DIR, DATA_DIR
from ..database import get_db
from ..deps import get_current_user
from ..models import Case, CaseFile
from ..services.demo_materials import create_demo_inputs
from ..services.file_import_service import ImportFailure, normalize_import

router = APIRouter(prefix="/api/demo", tags=["demo"])


class DemoRequest(BaseModel):
    kind: Literal["mixed", "scan"] = "mixed"


@router.post("/cases", status_code=201)
async def demo_case(body: DemoRequest | None = None, user=Depends(get_current_user), db=Depends(get_db)):
    kind = body.kind if body else "mixed"
    case = Case(title="虚构体验案件 · " + ("整份扫描卷" if kind == "scan" else "混合材料"), case_type="civil", org_id=user.org_id, created_by=user.id)
    db.add(case)
    await db.flush()
    root = ORGS_DIR / user.org_id / "cases" / case.id
    root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="synthetic-", dir=DATA_DIR) as temporary:
            inputs = await asyncio.to_thread(create_demo_inputs, Path(temporary), kind)
            for source in inputs:
                import_dir = root / "imports" / uuid.uuid4().hex
                import_dir.mkdir(parents=True)
                original = import_dir / ("original" + source.suffix)
                shutil.copyfile(source, original)
                pdf = await asyncio.to_thread(normalize_import, original, source.name)
                db.add(CaseFile(case_id=case.id, filename=source.name, stored_name=str(pdf.relative_to(ORGS_DIR)), doc_type="default", file_size=source.stat().st_size))
        await db.commit()
    except BaseException as exc:
        await db.rollback()
        if root.resolve().is_relative_to(ORGS_DIR.resolve()):
            shutil.rmtree(root, ignore_errors=True)
        if isinstance(exc, ImportFailure):
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        raise
    return {"case_id": case.id, "title": case.title, "synthetic": True}
