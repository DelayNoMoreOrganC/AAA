"""Server-owned scope for task-private model operation journals.

Only the analysis call receives this capability. No user path/config mapping is
accepted, no credentials enter its identity, and building it performs no writes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .analysis_snapshot import task_work_dir
from .task_sources import source_version


class RecognitionCheckpointError(RuntimeError):
    def __init__(self):
        super().__init__("RECOGNITION_CHECKPOINT_INVALID")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _path(value):
    if not isinstance(value, str) or not value or "\0" in value:
        raise RecognitionCheckpointError()
    return os.path.normcase(os.path.abspath(value))


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise RecognitionCheckpointError()
    return value


def _positive(value):
    if type(value) is not int or value < 1:
        raise RecognitionCheckpointError()
    return value


def _retry_token(value):
    if value is not None and (type(value) is not str or not re.fullmatch(r"[0-9a-f]{32}", value)):
        raise RecognitionCheckpointError()
    return value


def _validate_directory(directory, root):
    """Reject preexisting symlinks/junctions before the journal opens anything."""
    root, directory = Path(root).absolute(), Path(directory).absolute()
    try:
        relative = directory.relative_to(root)
    except ValueError:
        raise RecognitionCheckpointError() from None
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        try:
            status = current.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(status.st_mode)
                or getattr(status, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
                or not stat.S_ISDIR(status.st_mode)):
            raise RecognitionCheckpointError()


@dataclass(frozen=True, repr=False)
class RecognitionCheckpoint:
    directory: Path = field(repr=False)
    scope_json: str = field(repr=False)
    _root: Path = field(repr=False)
    retry_token: str | None = field(default=None, repr=False)

    def __post_init__(self):
        _retry_token(self.retry_token)

    @property
    def scope(self):
        # A journal implementation cannot mutate the next binding's scope.
        return json.loads(self.scope_json)

    @property
    def scope_sha256(self):
        return hashlib.sha256(self.scope_json.encode("utf-8")).hexdigest()

    def __deepcopy__(self, memo):
        # Config copies retain the trusted instance; it is never JSON settings.
        return self

    def __repr__(self):
        return f"RecognitionCheckpoint(scope_sha256={self.scope_sha256!r})"

    def bind(self, client):
        _validate_directory(self.directory, self._root)
        from recognition_journal import bind_client
        return bind_client(client, directory=self.directory, scope=self.scope, retry_token=self.retry_token)


def _code_and_prompts():
    # Paths are derived from this module, never API input or account settings.
    root = Path(__file__).resolve().parents[4]
    from recognition_identity import recognition_identity
    identity = recognition_identity(root)
    prompts = root / "prompts"
    if not prompts.is_dir() or prompts.is_symlink():
        raise RecognitionCheckpointError()
    hashes = {}
    for path in sorted(prompts.rglob("*")):
        if path.is_symlink() or (path.exists() and getattr(path.stat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)):
            raise RecognitionCheckpointError()
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {**identity, "prompt_hashes": hashes}


def _manifest(rows):
    if not isinstance(rows, list) or not rows:
        raise RecognitionCheckpointError()
    public, by_path, ids = [], {}, set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                or not isinstance(row.get("doc_type"), str) or not row["doc_type"]):
            raise RecognitionCheckpointError()
        identity = _identifier(row.get("file_id"))
        path = _path(row.get("path"))
        if identity in ids or path in by_path:
            raise RecognitionCheckpointError()
        ids.add(identity)
        item = {"file_id": identity, "sha256": row["sha256"], "pages": _positive(row.get("pages")),
                "doc_type": row["doc_type"], "path_sha256": _digest(path),
                "filename_sha256": _digest(row.get("filename"))}
        public.append(item)
        by_path[path] = item
    return public, by_path


def build_checkpoint(task, parent, org_id, config, *, case_type, stage, sources,
                     manual_fields, parent_snapshot, local_recall_context=None, analysis_kind):
    """Bind the actual full/delta source sequence and all prior local context.

    The caller already authorized the task and verified source bytes. Manifest
    identity is rechecked here; this helper does not open original documents.
    Unsupported workflows retain their existing non-journal behavior.
    """
    if "_recognition_checkpoint" in config:
        raise RecognitionCheckpointError()
    vision = config.get("vision") or {}
    if not (config.get("extraction", {}).get("mode") == "visual_agent"
            and vision.get("provider") in ("deepseek", "ollama") and vision.get("workflow") == "document_two_stage"):
        return None
    try:
        privacy = config.get("privacy") or {}
        local = vision.get("provider") == "ollama"
        from local_vision_catalog import ALLOWED_MODELS
        authorized = (privacy.get("mode") == "local" and privacy.get("cloud_authorized") is False
                      and callable(privacy.get("request_guard")) and vision.get("model") in ALLOWED_MODELS) if local else (
                      privacy.get("mode") == "cloud" and privacy.get("cloud_authorized") is True and vision.get("model") == "deepseek-flash")
        if (not authorized or analysis_kind not in ("full", "delta")
                or not isinstance(case_type, str) or not case_type or not isinstance(stage, str)):
            raise RecognitionCheckpointError()
        budget = vision.get("title_review_budget", 24)
        if type(budget) is not int or not 0 <= budget <= 128:
            raise RecognitionCheckpointError()
        profile = getattr(task, "execution_profile", None)
        if profile is not None and type(profile) is not dict:
            raise RecognitionCheckpointError()
        retry_token = _retry_token((profile or {}).get("_recognition_retry_token"))
        org_id, case_id = _identifier(org_id), _identifier(task.case_id)
        task_id, revision = _positive(task.id), _positive(task.revision)
        manifest, by_path = _manifest(task.source_manifest)
        if task.source_version != source_version(task.source_manifest, case_type, stage):
            raise RecognitionCheckpointError()
        selected, selected_ids = [], set()
        for source in sources:
            row = by_path.get(_path(source.path))
            if not row or row["doc_type"] != source.doc_type or row["file_id"] in selected_ids:
                raise RecognitionCheckpointError()
            selected.append(row)
            selected_ids.add(row["file_id"])
        if not selected or (analysis_kind == "full" and len(selected) != len(manifest)):
            raise RecognitionCheckpointError()
        parent_scope = None
        if parent is not None:
            if parent.case_id != case_id or getattr(task, "parent_task_id", None) != parent.id:
                raise RecognitionCheckpointError()
            parent_scope = {"task_id": _positive(parent.id), "revision": _positive(parent.revision),
                            "source_version": getattr(parent, "source_version", None),
                            "manifest_sha256": _digest(getattr(parent, "source_manifest", None)),
                            "snapshot_sha256": _digest(parent_snapshot),
                            "fields_sha256": _digest(getattr(parent, "fields", None)),
                            "manual_sha256": _digest(getattr(parent, "manual_fields", None)),
                            "issues_sha256": _digest(getattr(parent, "issues", None))}
        if analysis_kind == "delta" and parent_scope is None:
            raise RecognitionCheckpointError()
        scope = {"version": 1, "org_id": org_id, "case_id": case_id, "task_id": task_id, "revision": revision,
                 "actor_id": _identifier(task.created_by), "source_version": task.source_version,
                 "case_type": case_type, "stage": stage, "analysis_kind": analysis_kind,
                 "source_manifest_sha256": _digest(manifest), "source_count": len(manifest),
                 "analysis_sources_sha256": _digest(selected), "analysis_source_count": len(selected), "parent": parent_scope,
                 "task_fields_sha256": _digest(getattr(task, "fields", None)),
                 "task_manual_sha256": _digest(getattr(task, "manual_fields", None)),
                 "effective_manual_sha256": _digest(manual_fields),
                 "local_recall_context_sha256": _digest(local_recall_context),
                 "configuration": {"provider": vision["provider"], "model": vision["model"],
                                   "workflow": "document_two_stage", "title_review_budget": budget,
                                   "extraction_mode": "visual_agent", "order_mode": config.get("archive", {}).get("order_mode", "catalog")},
                 "code": _code_and_prompts()}
        if local:
            scope["configuration"].update(model_digest=(profile or {}).get("model_digest"), batch_pages=1)
        from ..config import ORGS_DIR
        directory = Path(task_work_dir(org_id, case_id, task_id)) / "recognition-journal"
        _validate_directory(directory, ORGS_DIR)
        return RecognitionCheckpoint(directory, _json(scope), Path(ORGS_DIR), retry_token=retry_token)
    except RecognitionCheckpointError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OSError):
        raise RecognitionCheckpointError() from None


def analysis_config(task, parent, org_id, config, **context):
    """Keep the private capability out of the caller's reusable config."""
    checkpoint = build_checkpoint(task, parent, org_id, config, **context)
    result = dict(config)
    if checkpoint is not None:
        result["_recognition_checkpoint"] = checkpoint
    return result
