"""Installation-wide, non-secret cloud switch, checked at request boundaries."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone

from .. import config

_WRITE_LOCK = threading.RLock()


class CloudPolicyLocked(Exception):
    pass


_MESSAGE = (
    "作用于本工作站所有账号。开启后仍须逐次授权材料版本；不会改变旧任务的处理方式。"
    "关闭会阻止新任务、连接检查及后续 DeepSeek/GLM 视觉请求；已发出的请求不能撤回。"
    "旧版云端 OCR 已运行的内部步骤不保证即时停止。"
)


def _policy_path():
    return config.DATA_DIR / "cloud-policy.json"


def read_cloud_policy(settings=None):
    settings = settings or config.get_settings()
    result = {"allowed": False, "locked": bool(settings.external_ai_locked),
              "state": "default", "scope": "workstation", "message": _MESSAGE,
              "updated_at": None, "updated_by": None}
    try:
        path = _policy_path()
        if path.is_symlink():
            raise ValueError("policy must be a regular installation file")
        with path.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError("invalid policy")
        record = json.loads(raw)
        if (not isinstance(record, dict) or record.get("version") != 1
                or type(record.get("allowed")) is not bool
                or not isinstance(record.get("updated_by"), str)
                or not isinstance(record.get("updated_at"), str)):
            raise ValueError("invalid policy")
        result.update(allowed=record["allowed"], state="configured",
                      updated_by=record["updated_by"], updated_at=record["updated_at"])
    except FileNotFoundError:
        result["allowed"] = bool(settings.allow_external_ai)
    except (OSError, ValueError, TypeError):
        # Never fall back to an enabled legacy value after a corrupt/unreadable file.
        result.update(allowed=False, state="invalid")
    if result["locked"]:
        result.update(allowed=False, state="locked")
    return result


def external_ai_allowed(settings=None):
    return read_cloud_policy(settings)["allowed"]


def require_external_ai():
    from .safe_errors import ErrorCode, SafeTaskError
    if not external_ai_allowed():
        raise SafeTaskError(ErrorCode.CLOUD_DISABLED)


def write_cloud_policy(*, allowed: bool, actor_id: str):
    with _WRITE_LOCK:
        if allowed and config.get_settings().external_ai_locked:
            raise CloudPolicyLocked("deployment policy prohibits external AI")
        record = {"version": 1, "allowed": allowed, "updated_by": actor_id,
                  "updated_at": datetime.now(timezone.utc).isoformat()}
        path = _policy_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(".cloud-policy-" + uuid.uuid4().hex + ".tmp")
        try:
            with temp.open("x", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return read_cloud_policy()
