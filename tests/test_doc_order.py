# -*- coding: utf-8 -*-
"""文书排序与乱序检测纯逻辑测试（无 OCR/Word 依赖）。"""

import pdf_archive_merger as pam
import pdf_doc_locator as pdl
from pdf_doc_locator import DocumentUnit
import archive_catalog as ac


def _u(doc_id, seq, sp, ep, src="a.pdf"):
    return DocumentUnit(doc_id=doc_id, doc_type="evidence", start_page=sp,
                        end_page=ep, catalog_seq=seq, source_path=src)


def test_order_detector_no_false_positive():
    spans = [_u(0, 7, 0, 2), _u(1, 7, 3, 5), _u(2, 14, 6, 7)]
    assert pam._verify_document_order(None, spans) == []


def test_order_detector_catches_regression():
    spans = [_u(0, 7, 5, 6), _u(1, 7, 0, 2)]
    issues = pam._verify_document_order(None, spans)
    assert len(issues) == 1
    assert issues[0]["seq"] == 7


def test_order_detector_groups_by_source():
    spans = [_u(0, 7, 3, 4, "a.pdf"), _u(1, 7, 0, 1, "b.pdf")]
    assert pam._verify_document_order(None, spans) == []


def test_archive_result_order_issues_default():
    r = pam.ArchiveResult("x", True, [])
    assert r.order_issues == []


def test_assign_catalog_seq_groups_by_source():
    catalog = ac.get_catalog("civil")
    units = [
        DocumentUnit(doc_id=0, doc_type="judgment", start_page=0, end_page=1, source_path="b.pdf"),
        DocumentUnit(doc_id=1, doc_type="judgment", start_page=0, end_page=1, source_path="a.pdf"),
        DocumentUnit(doc_id=2, doc_type="evidence", start_page=2, end_page=3, source_path="a.pdf"),
    ]
    out = pdl.assign_catalog_seq(units, catalog, log=lambda *a, **k: None)
    paths = [u.source_path for u in out]
    # 同源文书应连续（a.pdf 的两份相邻）
    assert paths in (["a.pdf", "a.pdf", "b.pdf"], ["b.pdf", "a.pdf", "a.pdf"])


def _ud(doc_id, seq, sp, ep, dt="contract", src="a.pdf"):
    return DocumentUnit(doc_id=doc_id, doc_type=dt, start_page=sp,
                        end_page=ep, catalog_seq=seq, source_path=src,
                        confidence=0.8)


def test_dedup_keeps_noncontiguous_islands():
    """同一 catalog_seq 的不连续分段不得合并成跨段大范围，
    否则会吞并中间其他文书的页 → 物理重复插入。
    复现 2019/容健华 案：contract 出现在 0-4 与 61-67，中间夹着 poa/complaint。
    """
    units = [
        _ud(0, 3, 0, 4, "contract"),
        _ud(1, 4, 5, 5, "poa"),
        _ud(2, 5, 6, 60, "complaint"),
        _ud(3, 3, 61, 67, "contract"),
    ]
    out = pdl._deduplicate_units_by_catalog_seq(units, log=lambda *a, **k: None)
    # 两个 contract 孤岛应保留为两段，不能合并成 0-67
    contract_spans = sorted(
        (u.start_page, u.end_page) for u in out if u.catalog_seq == 3
    )
    assert contract_spans == [(0, 4), (61, 67)]
    # 全局无页码重复
    covered = []
    for u in out:
        covered.extend(range(u.start_page, u.end_page + 1))
    assert len(covered) == len(set(covered))


def test_dedup_merges_contiguous_runs():
    """连续/重叠的同 seq 分段仍应合并为一段（执行段 seq15 合并行为）。"""
    units = [
        _ud(0, 15, 68, 71, "execution"),
        _ud(1, 15, 72, 81, "execution"),
        _ud(2, 15, 82, 82, "execution"),
    ]
    out = pdl._deduplicate_units_by_catalog_seq(units, log=lambda *a, **k: None)
    spans = [(u.start_page, u.end_page) for u in out if u.catalog_seq == 15]
    assert spans == [(68, 82)]
