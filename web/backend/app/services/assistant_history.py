"""Private, version-bound assistant requests with durable no-replay decisions."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import select, update

from ..models import AssistantTurn
from ..security import _create_token, decode_token
from .task_sources import fields_digest

INTERRUPTED = "上次请求在工作站重启前未确认完成，可能已发送模型；系统不会自动重发。请核对历史后明确重新提问。"
FAILED = "本次对话未能完成，未自动重复调用模型，请稍后明确重新提问。"


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def scope(task, user):
    return (AssistantTurn.org_id == user.org_id, AssistantTurn.user_id == user.id,
            AssistantTurn.case_id == task.case_id, AssistantTurn.task_id == task.id)


def request_digest(body):
    # Caller history is neither trusted context nor part of a request's identity.
    value = [body.message, body.expected_revision, body.source_version]
    # Keep old no-draft request identities replayable; an explicit draft version
    # is part of this request's consumption intent and cannot be swapped later.
    if getattr(body, "draft_version", None) is not None:
        value.append({"draft_version": body.draft_version})
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


async def find_request(db, task, user, request_id):
    return await db.scalar(select(AssistantTurn).where(*scope(task, user), AssistantTurn.request_id == request_id))


async def recover_pending(conn):
    """Startup-only: an interrupted external request must never be replayed."""
    await conn.execute(update(AssistantTurn).where(AssistantTurn.status == "pending").values(
        status="unknown", safe_error=INTERRUPTED, error_status=409,
        updated_at=datetime.now(timezone.utc)))


async def model_context(db, task, user):
    rows = list((await db.scalars(select(AssistantTurn).where(*scope(task, user),
        AssistantTurn.status == "completed", AssistantTurn.revision == task.revision,
        AssistantTurn.source_version == task.source_version).order_by(
            AssistantTurn.created_at.desc(), AssistantTurn.id.desc()).limit(3))).all())
    messages = []
    for row in reversed(rows):
        messages.append({"role": "user", "content": row.user_message[:1500]})
        message = (row.response or {}).get("message")
        if isinstance(message, str) and message:
            messages.append({"role": "assistant", "content": message[:1500]})
    return messages[-6:]


def complete(turn, response):
    saved = deepcopy(response)
    proposal = saved.get("proposal")
    if proposal:
        payload = decode_token(proposal.pop("proposal_token"))
        if not payload:
            raise ValueError("proposal could not be persisted")
        turn.proposal_id = proposal["id"]
        turn.proposal_payload = {key: value for key, value in payload.items() if key not in ("sub", "type", "exp", "iat")}
        turn.proposal_expires_at = datetime.fromisoformat(proposal["expires_at"])
        turn.proposal_state = "pending"
    turn.response, turn.status = saved, "completed"
    turn.updated_at = datetime.now(timezone.utc)


def refresh_proposal(turn, task, source_changed=False):
    if turn.proposal_state != "pending":
        return
    payload = turn.proposal_payload or {}
    if (source_changed or turn.revision != task.revision or turn.source_version != task.source_version
            or payload.get("fields_digest") != fields_digest(task.fields, task.order_mode)):
        turn.proposal_state = "stale"
    elif not turn.proposal_expires_at or utc(turn.proposal_expires_at) <= datetime.now(timezone.utc):
        turn.proposal_state = "expired"


def response_for(turn, task, *, source_changed=False, allow_token=True):
    refresh_proposal(turn, task, source_changed)
    response = deepcopy(turn.response or {})
    response.update(request_id=turn.request_id, user_message_id=turn.id + ":u", assistant_message_id=turn.id + ":a")
    if turn.proposal_id:
        response["proposal_state"] = turn.proposal_state
        if turn.safe_error:
            response["proposal_notice"] = turn.safe_error
        proposal = response.get("proposal") or {}
        proposal.pop("proposal_token", None)
        if turn.proposal_state == "pending" and allow_token:
            proposal["proposal_token"] = _create_token(turn.user_id, utc(turn.proposal_expires_at),
                                                       "assistant_proposal", turn.proposal_payload)
        response["proposal"] = proposal
    return response


def history_messages(turn, task, *, source_changed=False, allow_token=True):
    common = {"request_id": turn.request_id, "revision": turn.revision,
              "source_version": turn.source_version, "status": turn.status,
              "created_at": utc(turn.created_at).isoformat()}
    messages = [{**common, "id": turn.id + ":u", "role": "user", "content": turn.user_message}]
    if turn.status == "completed":
        response = response_for(turn, task, source_changed=source_changed, allow_token=allow_token)
        messages.append({**common, **{key: value for key, value in response.items()
                         if key in ("tool", "items", "action", "proposal", "proposal_state", "proposal_notice")},
                         "id": turn.id + ":a", "role": "assistant", "content": response.get("message", "")})
    elif turn.status in ("failed", "unknown"):
        messages.append({**common, "id": turn.id + ":a", "role": "assistant",
                         "content": turn.safe_error or FAILED})
    return messages
