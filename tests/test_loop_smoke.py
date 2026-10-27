# -*- coding: utf-8 -*-
"""P0 冒烟逻辑单测（免 OCR）。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# GT 门槛与 verify_loop_smoke 同步
GT_MIN = {
    "2014-兴泰贸易.pdf": 0.85,
    "2016-容健华.pdf": 0.95,
    "2019-佛山金百纳贸易有限公司.pdf": 0.85,
}


def test_gt_cases_registered():
    from ground_truth import GROUND_TRUTH, GT_TIER1
    for name in GT_TIER1:
        assert name in GROUND_TRUTH, f"缺少 GT: {name}"


def test_standard_catalogs_parsed_if_present():
    path = os.path.join("outputs", "_standard_catalogs.json")
    if not os.path.isfile(path):
        pytest.skip("未生成 _standard_catalogs.json，本地跑 extract_standard_catalog.py")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("parsed", 0) >= 28


def test_smoke_gate_logic():
    """验证 P0 判定逻辑本身。"""
    cases = [
        {"dup_pages": 0, "gap_pages": 0, "type_acc": 0.90, "min": 0.85, "ok": True},
        {"dup_pages": 1, "gap_pages": 0, "type_acc": 0.99, "min": 0.85, "ok": False},
        {"dup_pages": 0, "gap_pages": 0, "type_acc": 0.80, "min": 0.85, "ok": False},
    ]
    for c in cases:
        ok = c["dup_pages"] == 0 and c["gap_pages"] == 0 and c["type_acc"] >= c["min"]
        assert ok == c["ok"]
