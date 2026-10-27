"""Recover only an interrupted explicit proposal adoption; never replay a model."""
import asyncio
from pathlib import Path
import re
import stat

from sqlalchemy import select, update

from ..models import AssistantTurn, ArchiveTask, Case
from .task_sources import fields_digest

RESTORE_FAILED = "建议采用尚未完整恢复，原快照备份已保留；请检查工作站存储后重试恢复，暂不能采用。"
RESTORED = "上次建议采用未完成，已恢复原字段；未自动采用，请重新核对后决定。"
RECOVERY_REQUIRED = "本案有建议采用尚未恢复，请先在对话中恢复采用状态；原有完整成果仍可下载。"


async def has_unresolved(db, *, task_id=None, case_id=None):
    """Call only after case authorization; inspect state, never message bodies."""
    if task_id is None and case_id is None:
        raise ValueError("task or case identity required")
    query = select(AssistantTurn.id).where(AssistantTurn.proposal_state == "applying")
    if task_id is not None:
        query = query.where(AssistantTurn.task_id == task_id)
    if case_id is not None:
        query = query.where(AssistantTurn.case_id == case_id)
    return (await db.execute(query.limit(1))).scalar_one_or_none() is not None


async def require_consistent(db, *, task_id=None, case_id=None):
    from fastapi import HTTPException
    if await has_unresolved(db, task_id=task_id, case_id=case_id):
        raise HTTPException(409, RECOVERY_REQUIRED)


def _snapshot_path(org_id, case_id, task_id):
    """All identifiers come from the joined DB rows, never a proposal or path."""
    from ..config import ORGS_DIR
    if (not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) for value in (org_id, case_id))
            or type(task_id) is not int or task_id < 1):
        raise ValueError("invalid storage identity")
    root = Path(ORGS_DIR).absolute()
    target = root / org_id / "cases" / case_id / "tasks" / str(task_id) / "analysis_snapshot.json"
    if not target.parent.is_dir():
        raise OSError("snapshot directory unavailable")
    # Reject reparse points at every level, including the configured root and
    # ancestors. resolve() alone could otherwise silently follow a junction.
    for part in [*reversed(target.parents), target]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            if part == target:
                continue
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise OSError("reparse storage unavailable")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("snapshot outside storage")
    return target


def _restore_snapshot(row, task, case):
    from .analysis_snapshot import _atomic_write
    before = row["snapshot_before"]
    payload = row["proposal_payload"] or {}
    if (case["org_id"] != row["org_id"] or task["case_id"] != row["case_id"]
            or task["revision"] != row["revision"] or task["source_version"] != row["source_version"]
            or row["target_revision"] != row["revision"] + 1
            or not isinstance(before, dict) or not isinstance(before.get("fields"), dict)
            or (before.get("workflow") or {}).get("source_version") != row["source_version"]
            or fields_digest(task["fields"], task["order_mode"]) != payload.get("fields_digest")
            or fields_digest(before["fields"], task["order_mode"]) != payload.get("fields_digest")):
        raise ValueError("application identity changed")
    _atomic_write(str(_snapshot_path(case["org_id"], task["case_id"], task["id"])), before)


async def recover_application(db, turn_id):
    """Caller commits result and, outside startup, owns the case lock.

    Failed restoration keeps both applying and the preimage. Retrying this
    operation is safe: the DB's old task is authoritative until adoption commits.
    """
    turns, tasks, cases = AssistantTurn.__table__, ArchiveTask.__table__, Case.__table__
    row = (await db.execute(select(turns).where(turns.c.id == turn_id))).mappings().first()
    if not row:
        return "missing"
    if row["proposal_state"] == "applied":
        return "applied"  # A committed adoption must never be rolled back.
    if row["proposal_state"] != "applying":
        return "unchanged"
    task = (await db.execute(select(tasks).where(tasks.c.id == row["task_id"], tasks.c.case_id == row["case_id"]))).mappings().first()
    case = (await db.execute(select(cases).where(cases.c.id == row["case_id"], cases.c.org_id == row["org_id"]))).mappings().first()
    try:
        if not task or not case:
            raise ValueError("application owner missing")
        await asyncio.to_thread(_restore_snapshot, dict(row), dict(task), dict(case))
    except Exception:
        await db.execute(update(turns).where(turns.c.id == turn_id).values(safe_error=RESTORE_FAILED))
        return "failed"
    await db.execute(update(turns).where(turns.c.id == turn_id).values(
        proposal_state="pending", snapshot_before=None, target_revision=None, safe_error=RESTORED))
    return "restored"


async def recover_applications(db):
    turns = AssistantTurn.__table__
    ids = (await db.execute(select(turns.c.id).where(turns.c.proposal_state == "applying"))).scalars().all()
    return [await recover_application(db, ident) for ident in ids]
