#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""填充后页数预算：将系统模板控制在约定页数内（生成 PDF 前在 Word 内缩字/压行距）。"""

from __future__ import annotations

from template_manifest import TEMPLATE_NAMES, get_fill_cells, load_manifest
from word_atomic_fill import content_range, clear_range_bold

WD_LINE_SPACE_EXACTLY = 4
WD_ROW_HEIGHT_AT_LEAST = 1
CELL_END = "\x07"

# 各模板允许的最大页数（质量监督卡含「委托人须知」+「质量监督卡」共 2 页）
TEMPLATE_PAGE_BUDGET: dict[str, int] = {
    "档案卷宗": 1,
    "结案报告表": 1,
    "立案审批表": 1,
    "送达材料清单": 1,
    "质量监督卡": 2,
}

# 阶梯缩字：(字号 pt, 行距 pt)
COMPRESS_STEPS: tuple[tuple[float, float], ...] = (
    (12.0, 18.0),
    (10.5, 16.0),
    (9.0, 14.0),
    (8.0, 12.0),
    (7.5, 11.0),
    (7.0, 10.0),
)

BRIEF_TRUNCATE_CHARS = (100, 80, 60, 45)


def _plain(text: str) -> str:
    return (text or "").replace(CELL_END, "").replace("\r", "").replace("\n", "")


def page_count(doc) -> int:
    try:
        return int(doc.ComputeStatistics(2))
    except Exception:
        return 0


def _set_range_font(rng, size_pt: float, line_pt: float) -> None:
    if rng is None:
        return
    try:
        rng.Font.Size = size_pt
        rng.Font.Bold = 0
        clear_range_bold(rng)
    except Exception:
        pass
    try:
        for i in range(1, rng.Paragraphs.Count + 1):
            fmt = rng.Paragraphs(i).Format
            fmt.LineSpacingRule = WD_LINE_SPACE_EXACTLY
            fmt.LineSpacing = line_pt
            fmt.SpaceBefore = 0
            fmt.SpaceAfter = 0
    except Exception:
        pass


def _compress_cell(cell, size_pt: float, line_pt: float) -> None:
    try:
        rng = content_range(cell.Range)
        if not _plain(rng.Text or "").strip():
            return
        _set_range_font(rng, size_pt, line_pt)
    except Exception:
        pass


def _compress_fill_cells(doc, manifest: dict, size_pt: float, line_pt: float) -> int:
    count = 0
    for cell in get_fill_cells(manifest):
        try:
            ti, row, col = cell["table_index"], cell["row"], cell["col"]
            table = doc.Tables(ti)
            _compress_cell(table.Rows(row).Cells(col), size_pt, line_pt)
            count += 1
        except Exception:
            pass
    return count


def _compress_all_table_body_rows(doc, size_pt: float, line_pt: float, *, skip_header_rows: int = 1) -> int:
    """送达材料清单等：压缩数据行（保留表头字号）。"""
    count = 0
    try:
        for ti in range(1, doc.Tables.Count + 1):
            table = doc.Tables(ti)
            for ri in range(skip_header_rows + 1, table.Rows.Count + 1):
                try:
                    row = table.Rows(ri)
                    for ci in range(1, row.Cells.Count + 1):
                        _compress_cell(row.Cells(ci), size_pt, line_pt)
                        count += 1
                    try:
                        row.HeightRule = WD_ROW_HEIGHT_AT_LEAST
                        row.Height = max(10.0, line_pt + 2)
                    except Exception:
                        pass
                except Exception:
                    pass
    except Exception:
        pass
    return count


def _truncate_lian_brief(doc, manifest: dict, max_chars: int) -> bool:
    """立案审批表案情简介超长时截断。"""
    label = "案情简介："
    for cell in get_fill_cells(manifest):
        if cell.get("placeholder") not in ("9", "案情简介"):
            continue
        try:
            ti, row, col = cell["table_index"], cell["row"], cell["col"]
            rng = content_range(doc.Tables(ti).Rows(row).Cells(col).Range)
            plain = _plain(rng.Text or "")
            if label not in plain:
                continue
            start = plain.find(label) + len(label)
            body = plain[start:].strip()
            if len(body) <= max_chars:
                return False
            trimmed = body[: max_chars - 1].rstrip() + "…"
            doc.Range(rng.Start + start, rng.End).Text = trimmed
            return True
        except Exception:
            pass
    return False


def _tighten_page_setup(doc) -> None:
    """略微收紧页边距（在仍超页时作为辅助手段）。"""
    try:
        for i in range(1, doc.Sections.Count + 1):
            ps = doc.Sections(i).PageSetup
            for attr, val in (
                ("TopMargin", 72),      # 1 inch -> 72pt (already default, try smaller)
                ("BottomMargin", 72),
                ("LeftMargin", 68),
                ("RightMargin", 68),
            ):
                try:
                    cur = float(getattr(ps, attr))
                    if cur > val:
                        setattr(ps, attr, val)
                except Exception:
                    pass
    except Exception:
        pass


def fit_document_to_page_budget(doc, template_name: str, log=print) -> dict:
    """
    将已填充文档压缩到 TEMPLATE_PAGE_BUDGET 页数内。
    返回 {pages_before, pages_after, target, fitted}.
    """
    target = TEMPLATE_PAGE_BUDGET.get(template_name)
    if not target:
        return {"pages_before": page_count(doc), "pages_after": page_count(doc), "target": None, "fitted": True}

    before = page_count(doc)
    if before <= target:
        return {"pages_before": before, "pages_after": before, "target": target, "fitted": True}

    manifest = load_manifest(template_name)
    applied_step = 0

    for step_idx, (font_pt, line_pt) in enumerate(COMPRESS_STEPS, start=1):
        _compress_fill_cells(doc, manifest, font_pt, line_pt)
        if template_name == "送达材料清单":
            _compress_all_table_body_rows(doc, font_pt, line_pt)
        if template_name == "立案审批表":
            for max_chars in BRIEF_TRUNCATE_CHARS:
                _truncate_lian_brief(doc, manifest, max_chars)
                if page_count(doc) <= target:
                    break
        after = page_count(doc)
        applied_step = step_idx
        if after <= target:
            log(
                f"  [OK] {template_name} 页数 {before}→{after}（预算≤{target} 页，缩字档 {step_idx}）"
            )
            return {"pages_before": before, "pages_after": after, "target": target, "fitted": True}

    _tighten_page_setup(doc)
    after = page_count(doc)
    if after > target and template_name == "立案审批表":
        _truncate_lian_brief(doc, manifest, BRIEF_TRUNCATE_CHARS[-1])

    after = page_count(doc)
    if after <= target:
        log(
            f"  [OK] {template_name} 页数 {before}→{after}（预算≤{target} 页，缩字档 {applied_step}+边距）"
        )
        return {"pages_before": before, "pages_after": after, "target": target, "fitted": True}

    log(f"  [WARN] {template_name} 页数 {before}→{after}，仍超出预算 {target} 页（已用尽缩字档）")
    return {"pages_before": before, "pages_after": after, "target": target, "fitted": False}


def total_template_page_budget() -> int:
    """五份模板填满后的总页数预算（6 页）。"""
    return sum(TEMPLATE_PAGE_BUDGET.get(name, 1) for name in TEMPLATE_NAMES)
