"""Build upload doc-type options from V4 catalog for a case type."""
from __future__ import annotations

from ..core.v4_bridge import archive_catalog, document_segmenter


def list_upload_doc_types(case_type: str) -> list[dict]:
    ac = archive_catalog()
    ds = document_segmenter()
    items: list[dict] = [
        {"value": "default", "label": "默认（综合文档）", "seq": None},
    ]
    seen = {"default"}
    try:
        catalog = ac.get_catalog(case_type)
    except ValueError:
        return items
    for entry in catalog:
        if entry.doc_types:
            for dt in entry.doc_types:
                if dt in seen:
                    continue
                seen.add(dt)
                type_label = ds.DOC_TYPE_LABELS.get(dt, dt)
                items.append({
                    "value": dt,
                    "label": f"seq{entry.seq} {entry.name} — {type_label}",
                    "seq": entry.seq,
                })
        elif entry.manual_key:
            dt = ac.MANUAL_KEY_DOC_TYPES.get(entry.manual_key)
            if dt and dt not in seen:
                seen.add(dt)
                type_label = ds.DOC_TYPE_LABELS.get(dt, dt)
                items.append({
                    "value": dt,
                    "label": f"seq{entry.seq} {entry.name} — {type_label}",
                    "seq": entry.seq,
                })
    return items
