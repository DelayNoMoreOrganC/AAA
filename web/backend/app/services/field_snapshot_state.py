"""Recover interrupted field-only saves from the committed task row.

Callers own the case lock and provide an authorized task and its work directory.
No database writes, model work, classification edits or artifact publication.
"""
from copy import deepcopy
import hashlib
import json

from .analysis_snapshot import load_analysis, snapshot_path, _atomic_write
from .document_classification import verify_classification
from .task_sources import fields_digest, source_version


class FieldSnapshotError(RuntimeError):
    def __init__(self, reason="identity"):
        self.reason = reason
        super().__init__(RECOVERY_FAILED)


RECOVERY_FAILED = "填写快照与已保存任务暂不能安全同步，请保留输入并检查工作站存储后重试；未生成新成果。"
SAVE_MARKER = "field_save_origin"


def _manual_digest(value):
    return hashlib.sha256(json.dumps(value or {}, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def field_save_baseline(task):
    return {"revision": getattr(task, "revision", None) or 1,
            "fields_digest": fields_digest(task.fields, getattr(task, "order_mode", None) or "catalog"),
            "manual_digest": _manual_digest(getattr(task, "manual_fields", None))}


def field_save_marker(task, fields, baseline):
    """Bind a field-only file write to both possible committed DB states."""
    return {"task_id": task.id, "source_version": getattr(task, "source_version", None),
            "base": deepcopy(baseline),
            "target": {"revision": (getattr(task, "revision", None) or 1) + 1,
                       "fields_digest": fields_digest(fields, getattr(task, "order_mode", None) or "catalog"),
                       "manual_digest": _manual_digest(getattr(task, "manual_fields", None))}}


def reconcile_field_snapshot(task, work):
    """Restore only fields/field metadata, never adopt uncommitted file data.

    A committed request whose response was lost already matches the new row and
    is not rolled back. Legacy snapshots that need recovery but cannot prove
    source/classification identity are refused rather than guessed.
    """
    analysis, data = load_analysis(work)
    fields = deepcopy(getattr(task, "fields", None) or {})
    manual = deepcopy(getattr(task, "manual_fields", None) or {})
    revision = getattr(task, "revision", None) or 1
    workflow = data.get("workflow") or {}
    order = getattr(task, "order_mode", None) or "catalog"
    mismatch = (fields_digest(analysis.fields, order) != fields_digest(fields, order)
                or ("revision" in workflow and workflow["revision"] != revision)
                or ("manual_fields" in workflow and workflow["manual_fields"] != manual))
    if not mismatch:
        return False
    task_status = getattr(getattr(task, "status", None), "value", getattr(task, "status", None))
    if task_status not in ("awaiting_review", "done"):
        # A machine analysis checkpoint is written before its DB fields commit.
        # Preserve it for run_archive, including when the old row is nonempty.
        return False
    manifest = getattr(task, "source_manifest", None)
    version = getattr(task, "source_version", None)
    try:
        if (not isinstance(manifest, list) or not manifest or not version
                or workflow.get("source_version") != version
                or workflow.get("source_manifest") != manifest
                or source_version(manifest, data["case_type"], workflow.get("case_stage", "")) != version):
            raise ValueError("source identity does not match")
        verify_classification(task, analysis)
        saved_revision = workflow.get("revision")
        if not isinstance(saved_revision, int) or isinstance(saved_revision, bool):
            raise ValueError("missing revision")
        marker = workflow.get(SAVE_MARKER)
        if marker is not None:
            target = marker.get("target") if isinstance(marker, dict) else None
            snapshot_state = {"revision": saved_revision,
                              "fields_digest": fields_digest(analysis.fields, order),
                              "manual_digest": _manual_digest(workflow.get("manual_fields"))}
            if (not isinstance(target, dict) or marker.get("task_id") != task.id
                    or marker.get("source_version") != version or target != snapshot_state
                    or field_save_baseline(task) not in (marker.get("base"), target)):
                raise ValueError("field-save origin does not match")
        elif saved_revision == revision:
            # Same-revision data can also be a fresh machine analysis. It is
            # not safe to infer an interrupted edit without a bound marker.
            raise ValueError("ambiguous same-revision state")
    except (ValueError, KeyError, TypeError, RuntimeError):
        raise FieldSnapshotError() from None
    restored = deepcopy(data)
    restored["fields"] = fields
    restored["workflow"] = dict(workflow, revision=revision, manual_fields=manual)
    restored["workflow"].pop(SAVE_MARKER, None)
    # Task fields persist machine outcome warnings. For a legacy row without
    # that key, only its committed outcome issues can supply the warning list.
    warnings = fields.get("_outcome_warnings")
    if not isinstance(warnings, list):
        warnings = [row["message"] for row in getattr(task, "issues", None) or []
                    if isinstance(row, dict) and row.get("kind") == "outcome"
                    and isinstance(row.get("message"), str)]
    restored["outcome_warnings"] = deepcopy(warnings)
    try:
        _atomic_write(snapshot_path(work), restored)
    except (OSError, ValueError, TypeError):
        raise FieldSnapshotError("storage") from None
    return True
