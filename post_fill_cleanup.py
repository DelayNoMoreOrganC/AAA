#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""填充后清理：去除【】残留、模板说明片段，可填区统一黑色"""

import re

from template_manifest import PLACEHOLDER_RE, get_fill_cells, load_manifest
from word_atomic_fill import content_range, delete_substring_atomic

# 可填格内可能出现的模板说明（原子删除）
FILL_CELL_STRIP_SNIPPETS = (
    "参考格式：",
    "参考格式:",
    "参考格式",
    "（与审办结果一致）",
    "与审办结果一致",
    "字体格式要求",
    "字体格式",
    "所有字体格式要求：宋体四号，行距：固定值20磅，案情简介加上限制100字内",
    "格式：",
    "格式:",
    "【留空】",
    "留空",
    "（固定）",
    "(固定)",
)

# 质量监督卡：律师事务所固定格
QUALITY_CARD_LAW_FIRM_SNIPPETS = ("（固定）", "(固定)")

WD_REPLACE_ALL = 2
WD_FIND_STOP = 0
WD_COLOR_BLACK = 0


def _plain(text: str) -> str:
    return (text or "").replace("\x07", "").replace("\r", "").replace("\n", "")


def clear_remaining_brackets(doc, container_rng) -> int:
    """删除容器内所有未替换的【…】占位符"""
    n = 0
    for _ in range(50):
        base = content_range(container_rng)
        plain = _plain(base.Text or "")
        m = PLACEHOLDER_RE.search(plain)
        if not m:
            break
        token = m.group(0)
        if delete_substring_atomic(doc, container_rng, token):
            n += 1
        else:
            break
    return n


def clear_loose_bracket_chars(doc, container_rng) -> int:
    """删除可填格内残留的孤立【、】（替换错位后遗留）"""
    n = 0
    for ch in ("】", "【"):
        for _ in range(30):
            if not delete_substring_atomic(doc, container_rng, ch):
                break
            n += 1
    return n


def strip_template_snippets_in_cell(doc, container_rng) -> int:
    n = 0
    for snip in FILL_CELL_STRIP_SNIPPETS:
        while delete_substring_atomic(doc, container_rng, snip):
            n += 1
    return n


def _blacken_red_in_range(rng):
    """仅在给定 Range 内将红色字改为黑色"""
    color_indices = (6, 7, 13)
    font_colors = (255, 16711680, 0xFF0000)
    for color_index in color_indices:
        try:
            search = rng.Duplicate
            find = search.Find
            find.ClearFormatting()
            find.Font.ColorIndex = color_index
            find.Replacement.ClearFormatting()
            find.Replacement.Font.Color = WD_COLOR_BLACK
            find.Replacement.Font.ColorIndex = 1
            find.Replacement.Font.HighlightColorIndex = 0
            find.Replacement.Font.Bold = 0
            find.Execute(
                Replace=WD_REPLACE_ALL,
                Forward=True,
                Wrap=WD_FIND_STOP,
                Format=True,
            )
        except Exception:
            pass
    for font_color in font_colors:
        try:
            search = rng.Duplicate
            find = search.Find
            find.ClearFormatting()
            find.Font.Color = font_color
            find.Replacement.ClearFormatting()
            find.Replacement.Font.Color = WD_COLOR_BLACK
            find.Replacement.Font.ColorIndex = 1
            find.Replacement.Font.HighlightColorIndex = 0
            find.Replacement.Font.Bold = 0
            find.Execute(
                Replace=WD_REPLACE_ALL,
                Forward=True,
                Wrap=WD_FIND_STOP,
                Format=True,
            )
        except Exception:
            pass


def _fix_quality_supervision_law_firm(doc, blacken_fn=None) -> bool:
    """质量监督卡：律师事务所格去掉（固定）并变黑"""
    try:
        from template_manifest import get_fixed_cells, load_manifest

        manifest = load_manifest("质量监督卡")
        for cell in get_fixed_cells(manifest):
            note = (cell.get("note") or "") + (cell.get("preview") or "")
            if "至高" not in note and "律师事务所" not in note:
                continue
            ti, row, col = cell["table_index"], cell["row"], cell["col"]
            rng = doc.Tables(ti).Rows(row).Cells(col).Range
            for snip in QUALITY_CARD_LAW_FIRM_SNIPPETS:
                delete_substring_atomic(doc, rng, snip)
            base = content_range(rng)
            if blacken_fn:
                blacken_fn(base)
            _blacken_red_in_range(base)
            return True
    except Exception:
        pass
    return False


def repair_lian_labeled_cell(
    doc, container_rng, label: str, token_num: str, value: str, blacken_fn=None
) -> bool:
    """0606 模板：保留标签，将【N】替换为 value"""
    if not value or not str(value).strip():
        return False
    value = str(value).strip()
    token = f"【{token_num}】"
    base = content_range(container_rng)
    plain = _plain(base.Text or "")
    if label not in plain or token not in plain:
        return False
    if token not in plain and value[:8] in plain:
        return False
    try:
        from word_atomic_fill import replace_token_atomic

        return replace_token_atomic(
            doc, container_rng, token, value, blacken_fn=blacken_fn, fit_long_text=False
        )
    except Exception:
        return False


def repair_case_brief_labeled_cell(doc, container_rng, brief: str, blacken_fn=None) -> bool:
    """
    立案审批表等：单元格形如「案情简介：【模板…】【格式说明…】」。
    若模板 XXX 仍在，将冒号后全部替换为 brief（修复先清尾部导致 元内】 错位）。
    """
    if not brief or not str(brief).strip():
        return False
    brief = str(brief).strip()
    base = content_range(container_rng)
    plain = _plain(base.Text or "")
    label = "案情简介："
    if label not in plain:
        return False
    needs = (
        "XXX" in plain
        or "起诉状中起诉标的" in plain
        or "所有字体格式要求" in plain
        or brief[:12] not in plain
    )
    if not needs:
        return False
    try:
        start = plain.find(label) + len(label)
        value_rng = doc.Range(base.Start + start, base.End)
        value_rng.Text = brief
        brief_rng = doc.Range(base.Start + start, base.Start + start + len(brief))
        if blacken_fn:
            blacken_fn(brief_rng)
        from word_atomic_fill import clear_range_bold

        clear_range_bold(brief_rng)
        _blacken_red_in_range(value_rng)
        return True
    except Exception:
        return False


def finalize_fill_document(
    doc, template_name: str, blacken_fn=None, field_patch=None
) -> dict:
    """
    对 manifest 中所有可填格：清除【】残留与说明片段，并设为黑色。
    返回统计 {brackets, snippets, cells}。
    """
    manifest = load_manifest(template_name)
    stats = {"brackets": 0, "snippets": 0, "cells": 0}

    def _cell_rng(ti, row, col):
        return doc.Tables(ti).Rows(row).Cells(col).Range

    for cell in get_fill_cells(manifest):
        try:
            ti, row, col = cell["table_index"], cell["row"], cell["col"]
            rng = _cell_rng(ti, row, col)
            stats["brackets"] += clear_remaining_brackets(doc, rng)
            if (
                field_patch
                and template_name == "立案审批表"
                and cell.get("placeholder") == "9"
            ):
                brief = field_patch.get("9") or field_patch.get("案情简介", "")
                if brief and repair_lian_labeled_cell(
                    doc, rng, "案情简介：", "9", brief, blacken_fn
                ):
                    stats["snippets"] += 1
            stats["brackets"] += clear_loose_bracket_chars(doc, rng)
            stats["snippets"] += strip_template_snippets_in_cell(doc, rng)
            base = content_range(rng)
            if blacken_fn:
                blacken_fn(base)
            _blacken_red_in_range(base)
            stats["cells"] += 1
        except Exception:
            pass

    if template_name == "质量监督卡" and _fix_quality_supervision_law_firm(
        doc, blacken_fn
    ):
        print("  [OK] 质量监督卡: 律师事务所已去掉（固定）并设为黑色")

    try:
        if template_name == "立案审批表":
            from lian_approval_fill import apply_lian_approval_formatting

            apply_lian_approval_formatting(doc, manifest)
        else:
            from fill_cell_format import apply_fill_cell_formatting

            apply_fill_cell_formatting(doc, template_name, manifest)
        if template_name == "质量监督卡":
            from fill_cell_format import (
                build_outcome_cell_coords,
                format_fill_cell,
            )
            from template_manifest import get_fixed_cells

            outcome_coords = build_outcome_cell_coords(manifest)
            for cell in get_fixed_cells(manifest):
                note = (cell.get("note") or "") + (cell.get("preview") or "")
                if "至高" in note or "律师事务所" in note:
                    format_fill_cell(
                        doc,
                        doc.Tables(cell["table_index"]),
                        cell["row"],
                        cell["col"],
                        outcome_coords=outcome_coords,
                        cell_meta=cell,
                    )
                    break
    except Exception as e:
        import sys
        print(f"  [WARN] 可填格版式: {e}", file=sys.stderr)

    if stats["brackets"] or stats["snippets"]:
        print(
            f"  [OK] {template_name} 清理: 去除【】/孤立括号 {stats['brackets']} 处, "
            f"说明片段 {stats['snippets']} 处"
        )
    return stats
