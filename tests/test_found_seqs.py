# -*- coding: utf-8 -*-
"""compute_found_seqs / recompute_found_and_missing 纯逻辑测试。"""

import archive_pipeline as ap
from archive_catalog import get_catalog
from pdf_doc_locator import DocumentUnit


class _Span:
    def __init__(self, doc_type, catalog_seq=None):
        self.doc_type = doc_type
        self.catalog_seq = catalog_seq


def test_compute_found_seqs_by_doc_type():
    spans = [_Span("evidence"), _Span("judgment")]
    found = ap.compute_found_seqs(get_catalog("civil"), spans, {})
    assert 7 in found  # 证据材料
    assert 14 in found  # 裁判文书槽
    assert 2 not in found  # 发票槽无对应


class _Analysis:
    def __init__(self, doc_spans):
        self.case_type = "civil"
        self.generated_templates = {}
        self.doc_spans = doc_spans
        self.found_seqs = []
        self.missing_items = []


def test_recompute_found_and_missing():
    a = _Analysis([
        DocumentUnit(doc_id=0, doc_type="judgment", start_page=0, end_page=1, catalog_seq=14),
        DocumentUnit(doc_id=1, doc_type="evidence", start_page=2, end_page=3, catalog_seq=7),
    ])
    ap.recompute_found_and_missing(a)
    found = set(a.found_seqs)
    assert 7 in found and 14 in found
    missing = {m["seq"] for m in a.missing_items}
    assert 7 not in missing and 14 not in missing
