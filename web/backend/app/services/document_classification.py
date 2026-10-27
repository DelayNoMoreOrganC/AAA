"""Human classification of immutable, whole snapshot DocumentUnits.

The database owns decisions. A snapshot projection may be rebuilt from its
retained base after an interrupted save; assembly never accepts mixed versions.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime, timezone

from .analysis_snapshot import _unit_from_dict, _unit_to_dict

DECISIONS = "_document_classifications"
DIGEST = "_classification_digest"
REVIEW = "_classification_review"
BASE = "classification_base_units"
BASE_ISSUES = "classification_base_low_confidence"


class ClassificationError(ValueError):
    pass


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _path(value):
    return os.path.normcase(os.path.abspath(value or ""))


def classification_options(case_type):
    import archive_catalog as ac
    import document_segmenter as ds
    options = []
    for item in ac.get_catalog(case_type):
        from source_form_policy import SOURCE_FORM_TYPES
        if item.source == "system" and not SOURCE_FORM_TYPES.intersection(item.doc_types):
            continue
        types = list(item.doc_types or ())
        manual = ac.MANUAL_KEY_DOC_TYPES.get(item.manual_key)
        if manual and manual not in types:
            types.append(manual)
        # Keep the existing uncertain destination for historical decisions.
        # Choosing unknown still does not recognize a work-record document.
        if case_type == "counsel" and item.manual_key == "work_record":
            types.insert(0, "unknown")
        for kind in types:
            options.append({"doc_type": kind, "catalog_seq": item.seq,
                            "label": f"{item.seq} {item.name} — {ds.DOC_TYPE_LABELS.get(kind, kind)}"})
    return options


def indexed_units(analysis, manifest):
    sources = {_path(row["path"]): row for row in manifest or []}
    result = {}
    for unit in analysis.doc_spans:
        source = sources.get(_path(unit.source_path or analysis.original_pdf))
        if not source or not (0 <= unit.start_page <= unit.end_page < source["pages"]):
            raise ClassificationError("文书页段与已登记材料不一致，请重新核对分析快照")
        identity = [analysis.case_type, source["file_id"], source["sha256"], unit.start_page, unit.end_page]
        key = _hash(identity)
        if key in result:
            raise ClassificationError("分析快照包含重复文书段，请重新核对")
        result[key] = (unit, source)
    return result


def classification_digest(analysis, manifest):
    return _hash([[key, u.doc_id, u.doc_type, u.catalog_seq, u.manual_catalog_seq]
                  for key, (u, _) in indexed_units(analysis, manifest).items()])


def refresh_catalog(analysis):
    import archive_catalog as ac
    import archive_pipeline as ap
    catalog = ac.get_catalog(analysis.case_type)
    virtual = {item.templates[0]: "pending-render" for item in catalog if item.source == "system" and item.templates}
    analysis.found_seqs = ap.compute_found_seqs(catalog, analysis.doc_spans, virtual)
    analysis.missing_items = ap.compute_missing_items(analysis.case_type, catalog, analysis.found_seqs)


def apply_decisions(analysis, manifest, records, stage=""):
    """Reapply only an exact immutable unit; changed identities become review items."""
    units = indexed_units(analysis, manifest)
    options = {(item["doc_type"], item["catalog_seq"]) for item in classification_options(analysis.case_type)}
    applied, stale = set(), []
    for key, (unit, _) in units.items():
        old = (records or {}).get(key) or {}
        if unit.manual_catalog_seq is not None and old:
            unit.doc_type = old.get("original_doc_type", unit.doc_type)
            unit.catalog_seq = old.get("original_catalog_seq", unit.catalog_seq)
            unit.manual_catalog_seq = None
    for key, record in (records or {}).items():
        match = units.get(key)
        valid = (isinstance(record, dict) and match is not None
                 and record.get("case_type") == analysis.case_type
                 and record.get("stage", "") == (stage or "")
                 and (record.get("doc_type"), record.get("catalog_seq")) in options)
        if valid:
            unit, source = match
            valid = source.get("doc_type") == record.get("source_doc_type")
        if not valid:
            stale.append({"unit_key": key, "source_version": _hash(manifest),
                          "reason": "原人工分类的材料、案型、阶段或页段已变化，请重新核对"})
            continue
        unit.doc_type, unit.catalog_seq = record["doc_type"], record["catalog_seq"]
        unit.manual_catalog_seq = record["catalog_seq"]
        applied.add(unit.doc_id)
    analysis.low_confidence_items = [entry for entry in analysis.low_confidence_items or []
                                    if entry.get("doc_id") not in applied]
    analysis.fields[DECISIONS] = copy.deepcopy(records)
    analysis.fields[REVIEW] = stale
    analysis.fields[DIGEST] = classification_digest(analysis, manifest)
    refresh_catalog(analysis)
    return analysis


def verify_classification(task, analysis):
    """Fail closed if DB, snapshot or effective unit classification disagree."""
    fields = getattr(task, "fields", None) or {}
    tracked = fields.get(DIGEST) or fields.get(DECISIONS) or analysis.fields.get(DIGEST) or analysis.fields.get(DECISIONS)
    if not tracked:
        return
    if (fields.get(DECISIONS) != analysis.fields.get(DECISIONS)
            or fields.get(DIGEST) != analysis.fields.get(DIGEST)
            or fields.get(DIGEST) != classification_digest(analysis, task.source_manifest)):
        raise ClassificationError("分类草稿保存未完成或快照已改变，请打开文书分类重新保存后确认")


def project_database_decisions(task, analysis, snapshot, stage=""):
    """Used by the edit screen only, so an interrupted snapshot write is recoverable."""
    if (snapshot.get("workflow") or {}).get("source_version") != task.source_version:
        raise ClassificationError("分析快照与任务材料版本不一致，请先恢复分析快照")
    base = (snapshot.get("workflow") or {}).get(BASE)
    if base is not None:
        analysis.doc_spans = [_unit_from_dict(row) for row in base]
        analysis.low_confidence_items = copy.deepcopy((snapshot.get("workflow") or {}).get(BASE_ISSUES, analysis.low_confidence_items))
    analysis.fields = copy.deepcopy(task.fields or {})
    records = analysis.fields.get(DECISIONS) or {}
    if records or base is not None:
        apply_decisions(analysis, task.source_manifest, records, stage)
    return analysis


def document_rows(analysis, manifest):
    import archive_catalog as ac
    from .classification_guidance import guidance
    labels = {item.seq: item.name for item in ac.get_catalog(analysis.case_type)}
    options = classification_options(analysis.case_type)
    records = analysis.fields.get(DECISIONS) or {}
    rows = []
    for key, (unit, source) in indexed_units(analysis, manifest).items():
        record = records.get(key) or {}
        human = unit.manual_catalog_seq is not None
        rows.append({"unit_key": key, "doc_id": unit.doc_id, "file_id": source["file_id"],
                     "filename": source["filename"], "page_start": unit.start_page + 1,
                     "page_end": unit.end_page + 1, "doc_type": unit.doc_type,
                     "catalog_seq": unit.catalog_seq, "catalog_name": labels.get(unit.catalog_seq, ""),
                     "classification_origin": "human" if human else "auto",
                     "reason": record.get("reason", "") if human else "",
                     **guidance(unit, analysis, options)})
    return rows


def change_classification(task, analysis, snapshot, unit_key, body, actor_id, stage=""):
    units = indexed_units(analysis, task.source_manifest)
    if unit_key not in units:
        raise ClassificationError("文书段已变化或不属于本任务，请刷新后重新选择")
    if (body.doc_type, body.catalog_seq) not in {(o["doc_type"], o["catalog_seq"]) for o in classification_options(analysis.case_type)}:
        raise ClassificationError("分类不属于本案可用的正文目录")
    unit, source = units[unit_key]
    snapshot.setdefault("workflow", {}).setdefault(BASE, [_unit_to_dict(u) for u in analysis.doc_spans])
    snapshot["workflow"].setdefault(BASE_ISSUES, copy.deepcopy(analysis.low_confidence_items or []))
    records = copy.deepcopy((task.fields or {}).get(DECISIONS) or {})
    old = records.get(unit_key) or {}
    previous_human = unit.manual_catalog_seq is not None
    records[unit_key] = {"case_type": analysis.case_type, "stage": stage or "",
                         "file_id": source["file_id"], "sha256": source["sha256"],
                         "source_doc_type": source["doc_type"],
                         "start_page": unit.start_page, "end_page": unit.end_page,
                         "original_doc_type": old.get("original_doc_type", unit.doc_type) if previous_human else unit.doc_type,
                         "original_catalog_seq": old.get("original_catalog_seq", unit.catalog_seq) if previous_human else unit.catalog_seq,
                         "doc_type": body.doc_type, "catalog_seq": body.catalog_seq,
                         "reason": body.reason.strip(), "actor_id": actor_id,
                         "revision": (task.revision or 1) + 1,
                         "edited_at": datetime.now(timezone.utc).isoformat()}
    apply_decisions(analysis, task.source_manifest, records, stage)
    return records
