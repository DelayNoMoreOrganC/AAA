"""Organization-scoped experience lifecycle. Caller owns commit/rollback.

Only approved frozen records can guide recognition. Validation receipts can only
be installed by a future trusted real-case evaluator, never by an HTTP 'pass'
checkbox. An experience is immutable: amendments create a new draft.
"""
from sqlalchemy import select, update

from ..case_access import can_access_case
from ..models import (ArchiveTask, Case, User, Role, ExperienceVersion,
                      ExperienceEvaluation, ExperienceEvent, ExperienceOrigin)
from .experience_rules import VERSION, ExperienceError, normalize, digest, conflicts, freeze
from .experience_sources import correction, origin_digest


async def actor(db, user_id, *, admin=False):
    user = await db.scalar(select(User).where(User.id == user_id).execution_options(populate_existing=True))
    if not user or not user.is_active or (admin and user.role != Role.admin):
        raise ExperienceError("EXPERIENCE_FORBIDDEN")
    return user


async def visible(db, user, identity):
    row = await db.scalar(select(ExperienceVersion).where(
        ExperienceVersion.id == identity, ExperienceVersion.org_id == user.org_id
    ).execution_options(populate_existing=True))
    if not row or (user.role != Role.admin and row.author_id != user.id):
        raise ExperienceError("EXPERIENCE_NOT_FOUND")
    if digest(normalize(row.payload)) != row.payload_digest:
        raise ExperienceError("EXPERIENCE_INTEGRITY_INVALID")
    return row


async def create_draft(db, user_id, *, task_id, task_revision, decision_key, payload,
                       scope="case", supersedes_id=None, source_kind="catalog"):
    user = await actor(db, user_id, admin=scope != "case")
    if scope not in {"case", "firm", "general"}:
        raise ExperienceError("EXPERIENCE_SCOPE_INVALID")
    task = await db.get(ArchiveTask, task_id)
    case = await db.get(Case, task.case_id) if task else None
    if not can_access_case(user, case):
        raise ExperienceError("EXPERIENCE_NOT_FOUND")
    if type(task_revision) is not int or task.revision != task_revision:
        raise ExperienceError("EXPERIENCE_STALE_SOURCE")
    source = correction(task, case, source_kind, decision_key)
    if supersedes_id:
        await visible(db, user, supersedes_id)
    rule = normalize(payload)
    decision_digest = origin_digest(source_kind, decision_key, source["record"])
    identity = digest([user.org_id, user.id, task.id, task.revision, decision_digest,
                       scope, rule, supersedes_id])[:32]
    existing = await db.get(ExperienceVersion, identity)
    if existing:
        return await visible(db, user, identity)
    row = ExperienceVersion(id=identity, org_id=user.org_id, author_id=user.id, case_id=case.id,
                            source_task_id=task.id, source_revision=task.revision,
                            source_decision_digest=decision_digest,
                            supersedes_id=supersedes_id, scope=scope, payload=rule,
                            payload_digest=digest(rule), state="draft", revision=1)
    db.add(row)
    await db.flush()
    db.add(ExperienceOrigin(experience_id=row.id, org_id=user.org_id, source_kind=source_kind,
                            decision_key=decision_key, source_version=task.source_version or "",
                            record=source["record"], record_digest=decision_digest,
                            verified_binding=source["verified_binding"]))
    db.add(ExperienceEvent(org_id=user.org_id, experience_id=row.id, actor_id=user.id,
                           action="draft", revision=1))
    await db.flush()
    return row


async def require_origin(db, row):
    origin = await db.get(ExperienceOrigin, row.id)
    if (not origin or origin.org_id != row.org_id or not origin.verified_binding
            or origin.record_digest != row.source_decision_digest
            or origin_digest(origin.source_kind, origin.decision_key, origin.record) != origin.record_digest):
        raise ExperienceError("EXPERIENCE_SOURCE_REVIEW_REQUIRED")
    task = await db.get(ArchiveTask, row.source_task_id)
    case = await db.get(Case, row.case_id)
    if (not case or case.org_id != row.org_id or not task or task.case_id != case.id
            or task.revision < row.source_revision or task.source_version != origin.source_version):
        raise ExperienceError("EXPERIENCE_STALE_SOURCE")
    current = correction(task, case, origin.source_kind, origin.decision_key)
    if not current["verified_binding"] or origin_digest(origin.source_kind, origin.decision_key, current["record"]) != origin.record_digest:
        raise ExperienceError("EXPERIENCE_STALE_SOURCE")
    return origin


async def _move(db, row, user, target, revision):
    if type(revision) is not int or revision != row.revision:
        raise ExperienceError("EXPERIENCE_STALE_VERSION")
    result = await db.execute(update(ExperienceVersion).where(
        ExperienceVersion.id == row.id, ExperienceVersion.org_id == user.org_id,
        ExperienceVersion.revision == revision, ExperienceVersion.state == row.state
    ).values(state=target, revision=revision + 1).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise ExperienceError("EXPERIENCE_STALE_VERSION")
    db.add(ExperienceEvent(org_id=user.org_id, experience_id=row.id, actor_id=user.id,
                           action=target, revision=revision + 1))
    await db.flush()
    await db.refresh(row)
    return row


def _receipt_passes(receipt, row):
    """Reject partial/stale/technical-only receipts; never count these as accuracy."""
    if (receipt.org_id != row.org_id or receipt.payload_digest != row.payload_digest
            or receipt.evaluator_version != VERSION):
        return False
    report = receipt.result
    if (not isinstance(report, dict) or report.get("kind") != "real_case_holdout"
            or report.get("passed") is not True or report.get("cloud_authorization_checked") is not True):
        return False
    samples = report.get("samples")
    if not isinstance(samples, list) or len(samples) < 2:
        return False
    seen, outcomes = set(), set()
    for sample in samples:
        if not isinstance(sample, dict):
            return False
        identity, outcome = sample.get("case_id"), sample.get("expected_applicable")
        fingerprints = [sample.get("source_sha256"), sample.get("annotation_sha256"), sample.get("result_sha256")]
        if (type(identity) is not str or not identity or identity == row.case_id or identity in seen
                or type(outcome) is not bool or sample.get("passed") is not True
                or any(type(x) is not str or len(x) != 64 or any(c not in "0123456789abcdef" for c in x)
                       for x in fingerprints)):
            return False
        seen.add(identity)
        outcomes.add(outcome)
    return outcomes == {True, False}


async def transition(db, user_id, identity, *, target, revision):
    user = await actor(db, user_id, admin=True)
    row = await visible(db, user, identity)
    allowed = {"draft": {"validated", "retired"}, "validated": {"approved", "retired"},
               "approved": {"active", "retired"}, "active": {"retired"}, "retired": set()}
    if target not in allowed.get(row.state, set()):
        raise ExperienceError("EXPERIENCE_TRANSITION_INVALID")
    if target in {"validated", "approved", "active"}:
        await require_origin(db, row)
        receipts = (await db.scalars(select(ExperienceEvaluation).where(
            ExperienceEvaluation.experience_id == row.id, ExperienceEvaluation.org_id == user.org_id))).all()
        if not any(_receipt_passes(receipt, row) for receipt in receipts):
            raise ExperienceError("EXPERIENCE_HELDOUT_VALIDATION_REQUIRED")
    if target == "active":
        others = (await db.scalars(select(ExperienceVersion).where(
            ExperienceVersion.org_id == user.org_id, ExperienceVersion.state == "active"))).all()
        for other in others:
            if row.scope == other.scope == "case" and row.case_id != other.case_id:
                continue
            if conflicts(row.payload, other.payload):
                raise ExperienceError("EXPERIENCE_CONFLICT")
    return await _move(db, row, user, target, revision)


async def frozen_snapshot(db, user_id, case_id):
    user = await actor(db, user_id)
    case = await db.get(Case, case_id)
    if not can_access_case(user, case):
        raise ExperienceError("EXPERIENCE_NOT_FOUND")
    rows = (await db.scalars(select(ExperienceVersion).where(
        ExperienceVersion.org_id == user.org_id, ExperienceVersion.state == "active"))).all()
    return freeze(rows, org_id=user.org_id, case_id=case_id)
