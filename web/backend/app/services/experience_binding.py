"""Freeze at task creation; later publication never changes an existing task."""
from copy import deepcopy
from ..core.v4_bridge import load
from .experience_store import frozen_snapshot

PROFILE_KEY = "experience_snapshot"
CONFIG_KEY = "_experience_context"


def snapshot_for_task(task, org_id):
    contract = load("agent_experience")
    profile = getattr(task, "execution_profile", None) or {}
    if not isinstance(profile, dict):
        raise contract.ExperienceError("EXPERIENCE_SNAPSHOT_INVALID")
    raw = profile.get(PROFILE_KEY)
    # Old tasks deliberately use no experiences, never the current live set.
    if PROFILE_KEY not in profile:
        return contract.freeze([], org_id=org_id, case_id=task.case_id)
    return contract.validate_snapshot(raw, org_id=org_id, case_id=task.case_id)


async def attach_snapshot(db, user_id, case_id, org_id, profile, *, parent=None):
    contract = load("agent_experience")
    from .experience_store import actor
    from ..models import Case
    from ..case_access import can_access_case
    user = await actor(db, user_id)
    case = await db.get(Case, case_id)
    if user.org_id != org_id or not can_access_case(user, case):
        raise contract.ExperienceError("EXPERIENCE_NOT_FOUND")
    if PROFILE_KEY in profile:
        raise contract.ExperienceError("EXPERIENCE_PROFILE_ALREADY_BOUND")
    if parent is not None:
        if parent.case_id != case_id:
            raise contract.ExperienceError("EXPERIENCE_SCOPE_INVALID")
        raw = snapshot_for_task(parent, org_id)
    else:
        raw = await frozen_snapshot(db, user_id, case_id)
    return {**deepcopy(profile), PROFILE_KEY: contract.validate_snapshot(raw, org_id=org_id, case_id=case_id)}


def bind_config(task, org_id, config):
    contract = load("agent_experience")
    context = contract.ExperienceContext.from_snapshot(snapshot_for_task(task, org_id),
                                                      org_id=org_id, case_id=task.case_id)
    if CONFIG_KEY in config:
        old = contract.require_context(config[CONFIG_KEY])
        if old is None or old.snapshot_json != context.snapshot_json:
            raise contract.ExperienceError("EXPERIENCE_CONTEXT_INVALID")
    return {**config, CONFIG_KEY: context}
