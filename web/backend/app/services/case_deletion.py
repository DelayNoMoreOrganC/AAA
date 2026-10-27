"""Reversible staging of one owned case directory; no arbitrary output paths."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat


class DeletionStorageError(ValueError):
    pass


def _no_links(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise DeletionStorageError("案件目录含链接，暂不能安全删除")


def checked_paths(root, org_id, case_id):
    if not all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value or "") for value in (org_id, case_id)):
        raise DeletionStorageError("案件目录标识无效")
    root = Path(root).absolute()
    case = root / org_id / "cases" / case_id
    stage = root / org_id / ".case-deletions" / case_id
    for target in (case, stage):
        for ancestor in (target, *target.parents):
            _no_links(ancestor)
        if not target.resolve().is_relative_to(root.resolve()):
            raise DeletionStorageError("案件目录超出工作站范围")
    return case, stage


def checked_tree(path):
    _no_links(path)
    if not path.exists():
        return
    if not path.is_dir():
        raise DeletionStorageError("案件目录无效")
    for parent, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            _no_links(Path(parent) / name)


def read_record(stage, org_id, case_id):
    path = stage / "record.json"
    _no_links(path)
    try:
        with path.open("rb") as stream:
            record = json.loads(stream.read(4097))
    except FileNotFoundError:
        return None
    except (ValueError, UnicodeError) as exc:
        raise DeletionStorageError("删除记录无效，请联系管理员检查") from exc
    if (not isinstance(record, dict) or record.get("version") != 1
            or record.get("org_id") != org_id or record.get("case_id") != case_id
            or not (record.get("created_by") is None or isinstance(record.get("created_by"), str))):
        raise DeletionStorageError("删除记录不匹配，请联系管理员检查")
    return record


def restore_staged(case, stage):
    payload = stage / "case"
    checked_tree(payload)
    if payload.exists():
        if case.exists():
            raise DeletionStorageError("案件目录与删除暂存同时存在，请重试或联系管理员")
        case.parent.mkdir(parents=True, exist_ok=True)
        os.replace(payload, case)
    # Remove only the journal after complete restoration.
    (stage / "record.json").unlink(missing_ok=True)
    if stage.exists():
        stage.rmdir()


def stage_case(case, stage, *, org_id, case_id, created_by):
    checked_tree(case)
    if stage.exists():
        record = read_record(stage, org_id, case_id)
        if record is None:
            raise DeletionStorageError("删除暂存记录缺失，请联系管理员检查")
        restore_staged(case, stage)
    stage.mkdir(parents=True, exist_ok=False)
    record = {"version": 1, "org_id": org_id, "case_id": case_id, "created_by": created_by}
    try:
        with (stage / "record.json").open("x", encoding="utf-8") as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        if case.exists():
            os.replace(case, stage / "case")
    except Exception:
        # A failed rename leaves the original directory intact.
        if not (stage / "case").exists():
            (stage / "record.json").unlink(missing_ok=True)
            stage.rmdir()
        raise


def finish_cleanup(stage):
    checked_tree(stage)
    payload = stage / "case"
    if payload.exists():
        shutil.rmtree(payload)
    (stage / "record.json").unlink(missing_ok=True)
    stage.rmdir()
