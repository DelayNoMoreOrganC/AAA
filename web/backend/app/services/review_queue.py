"""Group review presentation without resolving or dropping underlying decisions.

Exact fields, source spans and quality checks contained in one uniquely
identified classification span coalesce. A material missing from the
catalog never becomes present because a related document occupies its slot.
Source anchors are bounded by this task's manifest; private paths/quotes stay
out of the queue. Existing issue/catalog records remain the decision authority.
"""
from __future__ import annotations

import hashlib
import json
import os

from .preview_fields import TEMPLATE_FIELD_SPECS
from .evidence_links import supporting_refs


def _path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ""


def build_review_queue(task, issues=None):
    manifest = [row for row in (task.source_manifest or []) if isinstance(row, dict)
                and isinstance(row.get("file_id"), str) and type(row.get("pages")) is int and row["pages"] > 0]
    by_id = {row["file_id"]: row for row in manifest}
    by_path = {_path(row.get("path")): row for row in manifest if row.get("path")}
    fields = task.fields or {}

    def anchor(ref):
        if not isinstance(ref, dict):
            return None
        if ref.get("file_id") and ref["file_id"] not in by_id:
            return None
        source = by_id.get(ref.get("file_id")) or by_path.get(_path(ref.get("source_path")))
        # Conflicting identities must not borrow an in-case file ID.
        if source and ref.get("source_path") and _path(ref["source_path"]) != _path(source.get("path")):
            return None
        page = ref.get("page", ref.get("page_start"))
        if source and type(page) is int and 1 <= page <= source["pages"]:
            return {"file_id": source["file_id"], "page": page, "filename": source.get("filename", "")}
        return None

    def locations(detail, field):
        refs = [detail]
        for key in ("sources", "pages", "candidates", "references"):
            value = detail.get(key)
            if isinstance(value, list):
                refs.extend(value)
        provenance = (fields.get("_provenance") or {}).get(field) or []
        refs.extend([provenance] if isinstance(provenance, dict) else provenance if isinstance(provenance, list) else [])
        for ref in list(refs):
            refs.extend(supporting_refs(ref, fields, manifest) or [])
        found = {}
        for ref in refs:
            if located := anchor(ref):
                found[(located["file_id"], located["page"])] = located
        return list(found.values())

    entries = (task.issues or []) if issues is None else issues
    classification_spans=set()
    for entry in entries:
        detail=entry.get('detail') if isinstance(entry,dict) else None
        if not isinstance(detail,dict) or entry.get('kind')!='classification' or not entry.get('blocking'):continue
        target=anchor(detail);start=detail.get('page_start',detail.get('page'));end=detail.get('page_end',start)
        if target and type(start) is int and type(end) is int and start==target['page'] and 1<=start<=end<=by_id[target['file_id']]['pages']:
            classification_spans.add((target['file_id'],start,end))
    groups = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("blocking") or not isinstance(entry.get("id"), str):
            continue
        detail = entry.get("detail") if isinstance(entry.get("detail"), dict) else {}
        field = detail.get("field") if isinstance(detail.get("field"), str) else ""
        sources = locations(detail, field)
        target = anchor(detail)
        start = detail.get("page_start", detail.get("page"))
        end = detail.get("page_end", start)
        if field:
            identity = ["field", field]
        elif (entry.get("kind") in ("ocr", "classification", "classification_stale") and target
              and type(start) is int and type(end) is int and start == target["page"] and 1 <= start <= end <= by_id[target["file_id"]]["pages"]):
            containing=[span for span in classification_spans if span[0]==target['file_id'] and span[1]<=start<=end<=span[2]]
            if entry.get('kind')=='ocr' and len(containing)==1:
                _,start,end=containing[0]
            identity = ["source", target["file_id"], start, end]
        else:
            identity = ["issue", entry["id"]]
        key = "review:" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:20]
        field_targets = [{"template_name": name, "field": spec["key"]}
                         for name, specs in TEMPLATE_FIELD_SPECS.items() for spec in specs
                         if field and field in (spec["key"], *spec["aliases"])]
        group = groups.setdefault(key, {"key": key, "kind": "issue", "title": f"核对「{field}」" if field else entry.get("message", "材料待核对"),
            "issue_ids": [], "catalog_seqs": [], "reasons": [], "field": field,
            "template_names": list(dict.fromkeys(row["template_name"] for row in field_targets)),
            "field_targets": field_targets, "sources": [], "blocking": True})
        if entry["id"] not in group["issue_ids"]:
            group["issue_ids"].append(entry["id"])
            group["reasons"].append({"id": entry["id"], "message": entry.get("message", "待核对"), "kind": entry.get("kind", "")})
        known = {(row["file_id"], row["page"]) for row in group["sources"]}
        group["sources"].extend(row for row in sources if (row["file_id"], row["page"]) not in known)

    for group in groups.values():
        if group['field']:
            from .field_decisions import field_candidates
            group['field_candidates'] = field_candidates(task, group['field'])
        kinds={row['kind'] for row in group['reasons']}
        if {'ocr','classification'}<=kinds:
            group['title']='核对同一文书的归档位置与清晰度'
        group['sources'].sort(key=lambda row:(row['file_id'],row['page']))

    required, other = [], []
    for item in task.catalog_status or []:
        if not isinstance(item, dict) or item.get("found") or type(item.get("seq")) is not int:
            continue
        needed = item.get("requirement") == "required" and item.get("legal_requirement_verified") is True
        seq = item["seq"]
        row = {"key": f"missing:{seq}", "kind": "missing", "title": item.get("name") or f"目录第 {seq} 项",
               "issue_ids": [], "catalog_seqs": [seq], "reasons": [{"id": f"missing:{seq}",
               "message": "已核验必需材料待补充" if needed else "材料缺项，适用性需核对", "kind": "missing"}],
               "field": "", "template_names": [], "field_targets": [], "sources": [], "blocking": needed}
        (required if needed else other).append(row)
    return required + list(groups.values()) + other
