"""Persist / restore ArchiveAnalysis between analyze and assemble (V6 review gate)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Dict, List, Optional

SNAPSHOT_FILENAME = "analysis_snapshot.json"

SYSTEM_TEMPLATE_NAMES = (
    "立案审批表",
    "送达材料清单",
    "档案卷宗",
    "结案报告表",
    "质量监督卡",
)


def task_work_dir(org_id: str, case_id: str, task_id: int) -> str:
    from ..config import ORGS_DIR

    return os.path.join(str(ORGS_DIR), org_id, "cases", case_id, "tasks", str(task_id))


def snapshot_path(work_dir: str) -> str:
    return os.path.join(work_dir, SNAPSHOT_FILENAME)


def docx_dir(work_dir: str) -> str:
    return os.path.join(work_dir, "docx")


def preview_dir(work_dir: str) -> str:
    return os.path.join(work_dir, "preview")


def _unit_to_dict(u) -> dict:
    confidence = getattr(u, "confidence", None)
    return {
        "doc_id": getattr(u, "doc_id", 0),
        "doc_type": getattr(u, "doc_type", ""),
        "start_page": getattr(u, "start_page", 0),
        "end_page": getattr(u, "end_page", 0),
        "title": getattr(u, "title", "") or "",
        "catalog_seq": getattr(u, "catalog_seq", None),
        "source_path": getattr(u, "source_path", "") or "",
        "score": float(getattr(u, "score", 0.0) or 0.0),
        "confidence": 1.0 if confidence is None else float(confidence),
        "manual_catalog_seq": getattr(u, "manual_catalog_seq", None),
    }


def _unit_from_dict(d: dict):
    from pdf_doc_locator import DocumentUnit

    confidence = d.get("confidence")
    return DocumentUnit(
        doc_id=int(d.get("doc_id", 0)),
        doc_type=str(d.get("doc_type", "")),
        start_page=int(d.get("start_page", 0)),
        end_page=int(d.get("end_page", 0)),
        title=str(d.get("title", "") or ""),
        catalog_seq=d.get("catalog_seq"),
        source_path=str(d.get("source_path", "") or ""),
        score=float(d.get("score", 0.0) or 0.0),
        confidence=1.0 if confidence is None else float(confidence),
        manual_catalog_seq=d.get("manual_catalog_seq"),
    )


def stabilize_templates(analysis, work_dir: str, log=print) -> Dict[str, str]:
    dest_root = docx_dir(work_dir)
    os.makedirs(dest_root, exist_ok=True)
    stable: Dict[str, str] = {}
    for name, src in (analysis.generated_templates or {}).items():
        if not src or not os.path.isfile(src):
            continue
        dest = os.path.join(dest_root, f"{name}.docx")
        shutil.copy2(src, dest)
        stable[name] = dest
        log(f"       模板落盘: {name}")
    analysis.generated_templates = stable
    return stable


def save_snapshot(work_dir: str, analysis, *, base_name: str, order_mode: str = "catalog", skipped: Optional[List[int]] = None, processing_mode: Optional[str] = None, metadata: Optional[dict] = None) -> str:
    os.makedirs(work_dir, exist_ok=True)
    fields = dict(analysis.fields or {})
    from ..core.v4_bridge import load
    load('agent_trace').validate_trace_fields(fields)
    outcome_warnings = list(getattr(analysis, "outcome_warnings", None) or [])
    if outcome_warnings and "_outcome_warnings" not in fields:
        fields["_outcome_warnings"] = outcome_warnings
    previous = load_snapshot_data(work_dir) if os.path.isfile(snapshot_path(work_dir)) else {}
    payload = {
        "workflow": dict(previous.get("workflow") or {}),
        "processing_mode": processing_mode or previous.get("processing_mode", "unknown"),
        "case_type": analysis.case_type,
        "original_pdf": analysis.original_pdf,
        "source_paths": list(getattr(analysis, "source_paths", None) or []),
        "base_name": base_name,
        "order_mode": order_mode,
        "fields": fields,
        "generated_templates": dict(analysis.generated_templates or {}),
        "doc_spans": [_unit_to_dict(u) for u in (analysis.doc_spans or [])],
        "found_seqs": sorted(analysis.found_seqs or []),
        "missing_items": list(analysis.missing_items or []),
        "low_confidence_items": list(getattr(analysis, "low_confidence_items", None) or []),
        "template_issues": list(getattr(analysis, "template_issues", None) or []),
        "outcome_warnings": outcome_warnings,
        "skipped": list(skipped if skipped is not None else previous.get("skipped", [])),
    }
    if metadata:
        payload["workflow"].update(metadata)
    path = snapshot_path(work_dir)
    _atomic_write(path, payload)
    return path


def load_snapshot_data(work_dir: str) -> dict:
    path = snapshot_path(work_dir)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"snapshot not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_analysis(work_dir: str):
    from ..core.v4_bridge import archive_pipeline
    ArchiveAnalysis = archive_pipeline().ArchiveAnalysis

    data = load_snapshot_data(work_dir)
    from ..core.v4_bridge import load
    load('agent_trace').validate_trace_fields(data.get('fields') or {})
    doc_spans = [_unit_from_dict(d) for d in data.get("doc_spans", [])]
    analysis = ArchiveAnalysis(
        case_type=data["case_type"],
        original_pdf=data.get("original_pdf"),
        fields=dict(data.get("fields") or {}),
        generated_templates=dict(data.get("generated_templates") or {}),
        doc_spans=doc_spans,
        found_seqs=set(data.get("found_seqs") or []),
        missing_items=list(data.get("missing_items") or []),
        low_confidence_items=list(data.get("low_confidence_items") or []),
        template_issues=list(data.get("template_issues") or []),
        outcome_warnings=list(data.get("outcome_warnings") or []),
        source_paths=list(data.get("source_paths") or []),
    )
    return analysis, data


def update_snapshot_fields(work_dir: str, fields: dict, generated_templates: Optional[dict] = None,
                           *, workflow_metadata: Optional[dict] = None) -> None:
    data = load_snapshot_data(work_dir)
    merged = dict(data.get("fields") or {})
    merged.update(fields or {})
    data["fields"] = merged
    from ..core.v4_bridge import load
    load('agent_trace').validate_trace_fields(merged)
    if fields is not None and isinstance(fields.get("_outcome_warnings"), list):
        data["outcome_warnings"] = list(fields["_outcome_warnings"])
    if generated_templates is not None:
        data["generated_templates"] = dict(generated_templates)
    if workflow_metadata is not None:
        data["workflow"] = dict(data.get("workflow") or {})
        data["workflow"].update(workflow_metadata)
    _atomic_write(snapshot_path(work_dir), data)


def _atomic_write(path: str, data: dict):
    fd, temporary = tempfile.mkstemp(prefix="snapshot-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
