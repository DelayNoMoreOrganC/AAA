# -*- coding: utf-8 -*-
"""排序模式配置与 CLI 补充解析纯逻辑测试。"""

import os

import settings


def test_order_mode_default():
    assert settings.get_archive_order_mode({}) == "catalog"


def test_order_mode_original():
    assert settings.get_archive_order_mode({"archive": {"order_mode": "original"}}) == "original"


def test_order_mode_case_insensitive_and_invalid():
    assert settings.get_archive_order_mode({"archive": {"order_mode": "CATALOG"}}) == "catalog"
    assert settings.get_archive_order_mode({"archive": {"order_mode": "bogus"}}) == "catalog"


def test_parse_supplements(tmp_path):
    import run_archive
    f = tmp_path / "s.pdf"
    f.write_bytes(b"%PDF-1.4\n")
    p = str(f)
    parsed = run_archive.parse_supplements([f"2:{p}", f"2:{p}", f"7:{p}", "bad", "9:nope.pdf", f"x:{p}"])
    assert parsed == {2: [p, p], 7: [p]}
