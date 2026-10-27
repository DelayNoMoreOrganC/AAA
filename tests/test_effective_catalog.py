# -*- coding: utf-8 -*-
"""V6 动态目录与缺失项测试"""

import archive_catalog as ac
import archive_pipeline as ap


def test_effective_catalog_drops_optional_seq15_when_absent():
    catalog = ac.get_effective_catalog("civil", found_seqs={14, 16, 18})
    seqs = {item.seq for item in catalog}
    assert 15 not in seqs
    assert 14 in seqs


def test_effective_catalog_keeps_seq15_when_found():
    catalog = ac.get_effective_catalog("civil", found_seqs={14, 15, 16, 18})
    seqs = {item.seq for item in catalog}
    assert 15 in seqs


def test_toc_keeps_delivery_list_required_by_archive_standard():
    catalog = ac.get_effective_catalog("civil", found_seqs={16, 17, 18}, for_toc=True)
    seqs = {item.seq for item in catalog}
    assert 17 in seqs
    assert 16 in seqs and 18 in seqs


def test_missing_items_skips_optional_seq15():
    catalog = ac.get_catalog("civil")
    found = {14, 16, 18}
    missing = ap.compute_missing_items("civil", catalog, found)
    missing_seqs = {m["seq"] for m in missing}
    assert 15 not in missing_seqs


def test_back_system_order_keeps_all_three_litigation_forms():
    for case_type in ("civil", "admin", "criminal"):
        assert ac.get_back_system_seqs(case_type) == (16, 17, 18)
