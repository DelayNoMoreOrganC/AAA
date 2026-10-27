"""Draft-only arbitration/consultation segmentation with complete source pages."""
from __future__ import annotations

from datetime import date
import re

import archive_catalog as catalog
from document_segmenter import ANCHORS
from pdf_doc_locator import DocumentUnit

_SPECIAL_HEADINGS = {
    "仲裁申请书": "complaint", "仲裁答辩书": "complaint", "仲裁反请求申请书": "complaint",
    "仲裁裁决书": "judgment", "裁决书": "judgment", "仲裁调解书": "mediation",
    "仲裁开庭通知书": "summons", "仲裁庭审笔录": "court_record",
    "咨询记录": "evidence", "法律咨询记录": "evidence", "咨询意见书": "evidence",
    "代书记录": "evidence", "代书定稿": "evidence", "代书成果": "evidence",
}
_HEADING_TYPES = dict(_SPECIAL_HEADINGS)
for _kind, _anchors in ANCHORS.items():
    for _anchor in _anchors:
        if len(_anchor) >= 4:
            _HEADING_TYPES.setdefault(_anchor, _kind)

_DATE = re.compile(r"(?:咨询|代书|服务|形成|出具|制作|记录)日期[:：]?\s*(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})日?")


def _document_date(text):
    found = set()
    for match in _DATE.finditer(re.sub(r"[ \t]", "", text or "")):
        try:
            found.add(date(*(int(value) for value in match.groups())))
        except ValueError:
            return None
    return next(iter(found)) if len(found) == 1 else None


def _heading(text):
    # Whole heading lines only: “咨询记录的续页…” is narrative, not a title.
    # OCR sometimes joins a heading directly to a labelled first field.
    for line in (text or "")[:260].splitlines()[:8]:
        clean = re.sub(r"\s+", "", line).strip("《》【】[]")
        for title in sorted(_HEADING_TYPES, key=len, reverse=True):
            if clean == title or re.match(re.escape(title) + r"[:：]?(?:咨询日期|代书日期|形成日期|申请人[:：]|被申请人[:：]|案号[:：])", clean):
                return title, _HEADING_TYPES[title]
    return "", "evidence"


def build_specialty_units(sources, case_type, page_texts_by_path, log=print):
    if case_type not in ("arbitration", "consultation"):
        raise ValueError("specialty unit builder only supports arbitration/consultation")
    units, dated = [], []
    evidence = catalog.catalog_item_for_manual_key(case_type, "evidence")
    for source in sources:
        pages = page_texts_by_path.get(source.path) or []
        if not pages:
            raise ValueError(f"无法确认来源页数：{source.path}")
        boundaries = [0]
        current_title, _ = _heading(pages[0])
        current_date = _document_date(pages[0])
        for index, text in enumerate(pages[1:], 1):
            title, _ = _heading(text)
            explicit_date = _document_date(text)
            if title and (title != current_title or (explicit_date and current_date and explicit_date != current_date)):
                boundaries.append(index)
                current_title, current_date = title, explicit_date
        boundaries.append(len(pages))
        for start, stop in zip(boundaries, boundaries[1:]):
            title, kind = _heading(pages[start])
            if not title and getattr(source, "doc_type", "default") not in ("default", "unknown", "other"):
                kind = source.doc_type
            item = catalog.catalog_item_for_doc_type(case_type, kind)
            if item is None:
                manual_key = next((key for key, value in catalog.MANUAL_KEY_DOC_TYPES.items() if value == kind), "evidence")
                item = catalog.catalog_item_for_manual_key(case_type, manual_key) or evidence
            unit = DocumentUnit(len(units), kind, start, stop - 1, title or "待核对业务材料",
                                2 if case_type == "consultation" else item.seq,
                                source.path, confidence=0.8 if title else 0.45)
            units.append(unit)
            dated.append(_document_date("\n".join(pages[start:stop])))
    metadata = {"strategy": "catalog", "status": "draft", "warnings": []}
    if case_type == "consultation":
        if all(value is not None for value in dated) and units:
            ordered = sorted(zip(units, dated), key=lambda pair: (pair[1], pair[0].doc_id))
            units = [pair[0] for pair in ordered]
            dated = [pair[1] for pair in ordered]
            metadata.update(strategy="year_then_document_date", status="dated")
        else:
            warning = "咨询代书材料存在缺失或冲突的明确业务日期，已保留原输入顺序；请核对年度与时间顺序。"
            metadata.update(strategy="original_pending_date_review", status="needs_review", warnings=[warning])
            log(warning)
        metadata["documents"] = [{"source_path": unit.source_path, "source_pages": [unit.start_page + 1, unit.end_page + 1],
                                  "date": value.isoformat() if value else None} for unit, value in zip(units, dated)]
    for index, unit in enumerate(units):
        unit.doc_id = index
    return units, metadata
