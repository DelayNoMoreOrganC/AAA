"""Candidate experience administration. Never accepts validation receipts."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from typing import Literal

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import ExperienceVersion, Role, ArchiveTask, Case
from ..case_access import can_access_case
from ..services import experience_store as store
from ..services.experience_rules import ExperienceError

router = APIRouter(prefix="/api/experiences", tags=["experiences"])


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: int = Field(gt=0)
    task_revision: int = Field(gt=0)
    decision_key: str = Field(min_length=1, max_length=100)
    source_kind: Literal["catalog", "classification", "field"] = "catalog"
    payload: dict
    scope: str = Field(default="case", max_length=20)
    supersedes_id: str | None = Field(default=None, max_length=32)


class Move(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target: str = Field(max_length=20)
    revision: int = Field(gt=0)


class RoutingPrecheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(gt=0)
    references: list[dict] = Field(min_length=2, max_length=12)


def public(row):
    return {key: getattr(row, key) for key in ("id", "scope", "payload", "payload_digest", "state", "revision")}


def failure(exc):
    code = str(exc)
    status = 403 if code == "EXPERIENCE_FORBIDDEN" else 404 if code == "EXPERIENCE_NOT_FOUND" else 409
    return HTTPException(status, code)


@router.get("")
async def listing(offset: int = Query(0, ge=0), user=Depends(get_current_user), db=Depends(get_db)):
    query = select(ExperienceVersion).where(ExperienceVersion.org_id == user.org_id)
    if user.role != Role.admin:
        query = query.where(ExperienceVersion.author_id == user.id)
    rows = (await db.scalars(query.order_by(ExperienceVersion.created_at, ExperienceVersion.id).offset(offset).limit(100))).all()
    return [public(row) for row in rows]


@router.get("/sources/{task_id}")
async def sources(task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    from ..services.experience_sources import available_corrections
    task = await db.get(ArchiveTask, task_id)
    case = await db.get(Case, task.case_id) if task else None
    if not can_access_case(user, case):
        raise HTTPException(404, "EXPERIENCE_NOT_FOUND")
    return {"task_id":task.id, "task_revision":task.revision,
            "sources":available_corrections(task,case)}


@router.post("", status_code=201)
async def draft(body: Draft, user=Depends(get_current_user), db=Depends(get_db)):
    try:
        row = await store.create_draft(db, user.id, **body.model_dump())
        await db.commit()
        return public(row)
    except ExperienceError as exc:
        await db.rollback()
        raise failure(exc) from None
    except IntegrityError:
        # A simultaneous duplicate has the same deterministic ID. A repeat
        # reads that receipt; no duplicate draft or lifecycle event is created.
        await db.rollback()
        raise HTTPException(409, "EXPERIENCE_CONCURRENT_WRITE_RETRY") from None


@router.post("/{identity}/transition")
async def move(identity: str, body: Move, user=Depends(require_admin), db=Depends(get_db)):
    try:
        row = await store.transition(db, user.id, identity, **body.model_dump())
        await db.commit()
        return public(row)
    except ExperienceError as exc:
        await db.rollback()
        raise failure(exc) from None


@router.post("/{identity}/routing-precheck")
async def routing_precheck(identity: str, body: RoutingPrecheck, user=Depends(require_admin), db=Depends(get_db)):
    from ..services.experience_precheck import run_precheck
    try:
        receipt = await run_precheck(db,user.id,identity,**body.model_dump())
        await db.commit()
        return {"id":receipt.id,"evaluator_version":receipt.evaluator_version,"result":receipt.result}
    except ExperienceError as exc:
        await db.rollback()
        raise failure(exc) from None
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409,"EXPERIENCE_CONCURRENT_WRITE_RETRY") from None


@router.post("/{identity}/boundary-comparison")
async def boundary_comparison(identity: str, body: RoutingPrecheck, user=Depends(require_admin), db=Depends(get_db)):
    from ..services.experience_boundary_comparison import run_comparison
    try:
        receipt = await run_comparison(db, user.id, identity, **body.model_dump())
        await db.commit()
        return {"id": receipt.id, "evaluator_version": receipt.evaluator_version, "result": receipt.result}
    except ExperienceError as exc:
        await db.rollback()
        raise failure(exc) from None
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "EXPERIENCE_CONCURRENT_WRITE_RETRY") from None


@router.post("/{identity}/field-comparison")
async def field_comparison(identity: str, body: RoutingPrecheck, user=Depends(require_admin), db=Depends(get_db)):
    from ..services.experience_boundary_comparison import run_comparison
    try:
        receipt = await run_comparison(db, user.id, identity, comparison='fields', **body.model_dump())
        await db.commit()
        return {"id": receipt.id, "evaluator_version": receipt.evaluator_version, "result": receipt.result}
    except ExperienceError as exc:
        await db.rollback()
        raise failure(exc) from None
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "EXPERIENCE_CONCURRENT_WRITE_RETRY") from None
