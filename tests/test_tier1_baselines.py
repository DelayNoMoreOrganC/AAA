# -*- coding: utf-8 -*-
"""P0 Tier1 baseline integrity (CI-runnable, no OCR).

Locks the "regression safety net" contract itself, so that the constants
underpinning every future high-risk change cannot be silently weakened:

- each Tier1 case has a registered type_acc threshold AND expected page count
- thresholds/expected pages are sane
- Tier1 GT page sets exactly cover [0, expected_pages): no gap, no overflow

The last check is the page-drift guard in pure-logic form: it catches any
off-by-one in the GT page space without needing the test PDFs (which are not
in CI). The live page-count enforcement (actual fitz page_count) runs locally
via scripts/verify_loop_smoke.py P0-D.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from ground_truth import (
    GROUND_TRUTH,
    GT_TIER1,
    GT_TIER1_EXPECTED_PAGES,
    GT_TIER1_MIN_ACC,
)


def test_tier1_constants_consistent():
    for name in GT_TIER1:
        assert name in GT_TIER1_MIN_ACC, f"缺少 type_acc 门槛: {name}"
        assert name in GT_TIER1_EXPECTED_PAGES, f"缺少期望页数: {name}"
        assert name in GROUND_TRUTH, f"缺少 GT: {name}"


def test_thresholds_sane():
    for name, acc in GT_TIER1_MIN_ACC.items():
        assert 0.0 < acc <= 1.0, f"{name}: 门槛越界 {acc}"


def test_expected_pages_positive():
    for name, n in GT_TIER1_EXPECTED_PAGES.items():
        assert isinstance(n, int) and n > 0, f"{name}: 期望页数非法 {n!r}"


def test_tier1_gt_full_page_coverage():
    """Tier1 GT must cover every page in [0, expected_pages) exactly once."""
    for name in GT_TIER1:
        expected = GT_TIER1_EXPECTED_PAGES[name]
        gt = GROUND_TRUTH[name]
        pages = set(gt.keys())
        wanted = set(range(expected))
        missing = sorted(wanted - pages)
        overflow = sorted(p for p in pages if p >= expected)
        assert not missing, f"{name}: GT 缺页 {missing[:12]}"
        assert not overflow, f"{name}: GT 越界页 {overflow[:12]}"


def test_page_count_gate_logic():
    """Documents the page-drift gate: any deviation from expected fails."""
    cases = [
        {"pages": 80, "expected": 80, "ok": True},
        {"pages": 79, "expected": 80, "ok": False},
        {"pages": 81, "expected": 80, "ok": False},
    ]
    for c in cases:
        assert (c["pages"] == c["expected"]) == c["ok"]
