#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
立案审批表（0606）专用：楷体_GB2312、行数补全。
除案情简介外，可填格水平居中。
"""

import re

from word_atomic_fill import clear_range_bold, content_range

FONT_KAITI = "楷体_GB2312"
FONT_KAITI_FB = "楷体"
SIZE_SIHAO = 14.0
SIZE_XIAOSI = 12.0
FEE_CHAR_THRESHOLD = 12

WD_ALIGN_LEFT = 0
WD_ALIGN_CENTER = 1
WD_CELL_ALIGN_VERTICAL_CENTER = 1
WD_LINE_EXACTLY = 4
LINE_BRIEF_PT = 24.0

BRIEF_MAX_CHARS = 100
BRIEF_CONTENT_LINES = 3

BRIEF_LABEL = "案情简介："
DATE_LABEL = "立案日期："
CELL_END = "\x07"

# 除案情简介外：水平居中
LIAN_CENTER_CELLS = {
    (1, 1, 2),
    (1, 1, 4),
    (1, 2, 2),
    (1, 2, 4),
    (1, 3, 2),
    (1, 4, 4),
    (1, 5, 2),
    (1, 9, 1),
}

LIAN_FEE_CELL = (1, 4, 2)


def _plain(text: str) -> str:
    return (text or "").replace(CELL_END, "").replace("\r", "")


def _set_kaiti(rng, size_pt: float = SIZE_SIHAO):
    for name in (FONT_KAITI, FONT_KAITI_FB):
        try:
            rng.Font.NameFarEast = name
            rng.Font.Name = name
            break
        except Exception:
            continue
    try:
        rng.Font.Size = size_pt
        rng.Font.Color = 0
        rng.Font.ColorIndex = 1
        rng.Font.Bold = 0
    except Exception:
        pass
    clear_range_bold(rng)


def _pick_lian_party(base_fields: dict) -> str:
    from field_sanitize import parse_litigation_parties, is_placeholder_value

    client = (base_fields.get("委托人") or base_fields.get("委托人名称") or "").strip()
    if client and not is_placeholder_value(client):
        return client

    for key in ("判决书中的原告", "起诉状中的原告", "原告", "当事人"):
        raw = (base_fields.get(key) or "").strip()
        if not raw or is_placeholder_value(raw):
            continue
        pl, _ = parse_litigation_parties(raw)
        if pl:
            return pl
        if key != "当事人":
            return raw
    return ""

def _pick_defendants(base_fields: dict) -> str:
    raw = (base_fields.get("对方当事人") or "").strip()
    if not raw:
        return ""
    parts = re.split(r"[、,，;；\n]+", raw)
    seen = []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.append(p)
    return "、".join(seen)


def _pad_lines(lines: list, min_lines: int) -> list:
    out = list(lines)
    while len(out) < min_lines:
        out.append("")
    return out


def _join_word_lines(lines: list) -> str:
    return "\r".join(lines)


def _normalize_fee(text: str) -> str:
    s = (text or "").strip().replace("\\", " ")
    return s


def _pad_brief_content(text: str) -> list:
    """正常填写内容，不足 3 行时在末尾补空行（不强制按字数拆行）。"""
    s = (text or "").strip()
    if len(s) > BRIEF_MAX_CHARS:
        s = s[:BRIEF_MAX_CHARS]
    if not s:
        lines = [""]
    else:
        raw_lines = re.split(r"[\r\n]+", s)
        lines = [ln for ln in raw_lines if ln is not None]
        if not lines or all(not ln.strip() for ln in lines):
            lines = [s]
    return _pad_lines(lines, BRIEF_CONTENT_LINES)


def _build_case_brief(base_fields: dict) -> str:
    from field_sanitize import is_placeholder_value

    brief = (base_fields.get("案情简介") or "").strip()
    if brief and is_placeholder_value(brief):
        brief = ""
    if not brief:
        from field_mapping import _build_case_brief as _build_generic_brief

        brief = _build_generic_brief(base_fields)
    content_lines = _pad_brief_content(brief)
    return "\r" + _join_word_lines(content_lines)

def expand_lian_fields(base_fields: dict) -> dict:
    bf = dict(base_fields or {})
    from field_mapping import _is_valid_field_value

    def _cell(val):
        """取有效值；字段说明/提取要求/占位符一律留空。"""
        v = (val or "").strip()
        return v if _is_valid_field_value(v) else ""

    return {
        "1": (bf.get("案件类别") or "").strip(),
        "2": "",
        "3": _cell(bf.get("委托人") or bf.get("委托人名称") or ""),
        "4": _cell(_pick_lian_party(bf)),
        "5": _cell(bf.get("委托人电话") or ""),
        "6": _normalize_fee(bf.get("收费标准") or ""),
        "7": _cell(bf.get("地址") or ""),
        "8": _pick_defendants(bf) or _cell(bf.get("对方当事人") or ""),
        "9": _build_case_brief(bf),
        "10": _cell(bf.get("收案日期") or bf.get("立案日期") or ""),
    }


def _apply_para(
    para,
    *,
    align,
    indent_chars=0,
    line_spacing=None,
    v_center_cell=None,
    size_pt=SIZE_SIHAO,
):
    try:
        pf = para.Format
        pf.Alignment = WD_ALIGN_CENTER if align == "center" else WD_ALIGN_LEFT
        pf.SpaceBefore = 0
        pf.SpaceAfter = 0
        if line_spacing:
            pf.LineSpacingRule = WD_LINE_EXACTLY
            pf.LineSpacing = line_spacing
        else:
            pf.LineSpacingRule = 0
        try:
            pf.CharacterUnitFirstLineIndent = indent_chars
            pf.CharacterUnitLeftIndent = 0
        except Exception:
            pf.FirstLineIndent = size_pt * indent_chars if indent_chars else 0
        _set_kaiti(para.Range, size_pt)
    except Exception:
        pass
    if v_center_cell is not None:
        try:
            v_center_cell.VerticalAlignment = WD_CELL_ALIGN_VERTICAL_CENTER
        except Exception:
            pass


def _format_fee_cell(cell):
    """收费标准：超过 12 字用小四，否则四号；水平居中。"""
    try:
        cell.VerticalAlignment = WD_CELL_ALIGN_VERTICAL_CENTER
        rng = content_range(cell.Range)
        plain = _plain(rng.Text or "")
        size_pt = SIZE_XIAOSI if len(plain) > FEE_CHAR_THRESHOLD else SIZE_SIHAO
        try:
            n = rng.Paragraphs.Count
        except Exception:
            n = 1
        for j in range(1, n + 1):
            _apply_para(
                rng.Paragraphs(j),
                align="center",
                v_center_cell=cell,
                size_pt=size_pt,
            )
    except Exception:
        pass


def _format_center_cell(cell):
    try:
        cell.VerticalAlignment = WD_CELL_ALIGN_VERTICAL_CENTER
        rng = content_range(cell.Range)
        plain = _plain(rng.Text or "")
        if plain.startswith(DATE_LABEL):
            parts = [
                cell.Range.Document.Range(rng.Start, rng.Start + len(DATE_LABEL)),
                cell.Range.Document.Range(
                    rng.Start + len(DATE_LABEL),
                    rng.End - (1 if (rng.Text or "").endswith(CELL_END) else 0),
                ),
            ]
            for part in parts:
                try:
                    n = part.Paragraphs.Count
                except Exception:
                    n = 1
                for j in range(1, n + 1):
                    _apply_para(part.Paragraphs(j), align="center", v_center_cell=cell)
            return
        try:
            n = rng.Paragraphs.Count
        except Exception:
            n = 1
        for j in range(1, n + 1):
            _apply_para(rng.Paragraphs(j), align="center", v_center_cell=cell)
    except Exception:
        pass


def _format_brief_cell(cell):
    """案情简介：左对齐；第 1 行标签无缩进，第 2–4 行内容首行缩进 2 字符"""
    try:
        rng = content_range(cell.Range)
        n = rng.Paragraphs.Count
        for i in range(1, n + 1):
            para = rng.Paragraphs(i)
            text = _plain(para.Range.Text or "")
            is_label = i == 1 or text.startswith(BRIEF_LABEL) or text == BRIEF_LABEL.rstrip("：")
            _apply_para(
                para,
                align="left",
                indent_chars=0 if is_label else 2,
                line_spacing=LINE_BRIEF_PT,
            )
    except Exception:
        pass


def apply_lian_approval_formatting(doc, manifest: dict) -> int:
    count = 0
    try:
        table = doc.Tables(1)
        for ti, row, col in LIAN_CENTER_CELLS:
            try:
                _format_center_cell(table.Rows(row).Cells(col))
                count += 1
            except Exception:
                pass
        try:
            _format_fee_cell(table.Rows(LIAN_FEE_CELL[1]).Cells(LIAN_FEE_CELL[2]))
            count += 1
        except Exception:
            pass
        try:
            _format_brief_cell(table.Rows(6).Cells(1))
            count += 1
        except Exception:
            pass
    except Exception:
        pass
    if count:
        print(
            "  [OK] 立案审批表 可填格版式：楷体_GB2312 四号；"
            "除案情简介外水平居中；案情简介4行左对齐"
        )
    return count
