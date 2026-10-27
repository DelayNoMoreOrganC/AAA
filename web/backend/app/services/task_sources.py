"""Immutable task input identity, including source bytes and user classification."""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import fitz


def file_digest(path):
    stat = os.stat(path)
    return _cached_digest(os.path.abspath(path), stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=1024)
def _cached_digest(path, size, mtime_ns):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_source_manifest(files):
    manifest = []
    for source in files:
        path = os.path.abspath(source.abs_path)
        with fitz.open(path) as document:
            pages = document.page_count
        manifest.append({"file_id": source.id, "filename": source.filename,
                         "path": path, "doc_type": source.doc_type,
                         "sha256": file_digest(path), "pages": pages})
    return manifest


def source_version(manifest, case_type, stage=""):
    canonical = [{key: row.get(key) for key in ("file_id", "sha256", "doc_type", "pages")} for row in manifest]
    payload = [case_type, canonical]
    if stage:
        payload.append(stage)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def fields_digest(fields, order_mode):
    content = {key: value for key, value in (fields or {}).items() if key != "_saved_to"}
    return hashlib.sha256(json.dumps([content, order_mode], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def changed_file_ids(previous, current):
    old = {row["file_id"]: row for row in previous or []}
    return {row["file_id"] for row in current if row["file_id"] not in old or any(
        row.get(key) != old[row["file_id"]].get(key) for key in ("sha256", "doc_type", "pages"))}


def snapshot_exists(task, org_id):
    from .analysis_snapshot import task_work_dir, snapshot_path
    return Path(snapshot_path(task_work_dir(org_id, task.case_id, task.id))).is_file()
