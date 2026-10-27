#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可填格版式：楷体、单元格垂直居中；结案小结/审（办）结果左对齐+首行缩进2字，其余水平居中"""

from word_atomic_fill import content_range, clear_range_bold

# Word 常量
WD_ALIGN_PARAGRAPH_LEFT = 0
WD_ALIGN_PARAGRAPH_CENTER = 1
WD_CELL_ALIGN_VERTICAL_CENTER = 1
WD_LINE_SPACE_SINGLE = 0
CELL_END = "\x07"

FONT_KAITI = "楷体_GB2312"
FONT_KAITI_FALLBACK = "楷体"
SIZE_SIHAO = 14.0  # 四号（全部可填格统一）

OUTCOME_LABEL_MARKERS = ("结案小结", "审（办）结果", "审办结果")

# 与 field_mapping 中审办/结案字段键一致（含长占位符名）
OUTCOME_FIELD_KEYS = frozenset(
    {
        "结案小结",
        "审（办）结果",
        "审办结果",
        "《律师业务卷宗（银行案)》sheet1的I列，根据判决书、执行裁定书的内容，匹配最相近的选项填写",
    }
)


def build_outcome_cell_coords(manifest: dict) -> set:
    """
    根据表头 fixed 格「结案小结」「审（办）结果」确定值格坐标。
    返回 {(table_index, row, col), ...}
    """
    coords = set()
    for tbl in manifest.get("tables") or []:
        ti = tbl.get("table_index", 1)
        by_rc = {}
        for cell in tbl.get("cells") or []:
            by_rc[(cell["row"], cell["col"])] = cell
        for (r, c), cell in by_rc.items():
            if cell.get("role") != "fixed":
                continue
            label = (cell.get("note") or "") + (cell.get("preview") or "")
            if not any(m in label for m in OUTCOME_LABEL_MARKERS):
                continue
            for dc in (1, 2):
                fill = by_rc.get((r, c + dc))
                if fill and fill.get("role") in (
                    "fill",
                    "header_fill",
                    "seq_fill",
                    "clear",
                ):
                    coords.add((ti, r, c + dc))
                    break
    return coords


def is_outcome_cell(cell: dict, outcome_coords: set) -> bool:
    """是否结案小结/审（办）结果值格（仅这两类左对齐+缩进）"""
    if not cell:
        return False
    key = (cell.get("table_index", 1), cell["row"], cell["col"])
    if key in outcome_coords:
        return True
    ph = (cell.get("placeholder") or "").strip()
    return ph in OUTCOME_FIELD_KEYS


def is_outcome_placeholder(name: str) -> bool:
    """原子填充是否跳过阶梯缩字（仅结案/审办字段键）"""
    if not name:
        return False
    n = name.strip()
    if n in OUTCOME_FIELD_KEYS:
        return True
    return any(m in n for m in OUTCOME_LABEL_MARKERS)


def _set_font_on_range(rng, size_pt: float):
    for name in (FONT_KAITI, FONT_KAITI_FALLBACK):
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


def _cell_has_content(cell) -> bool:
    try:
        t = (cell.Range.Text or "").replace(CELL_END, "").strip()
        return bool(t)
    except Exception:
        return False


def _apply_cell_alignment(cell, size_pt: float, *, outcome_style: bool = False):
    """对单元格内全部段落设置对齐与缩进，并垂直居中"""
    try:
        cell.VerticalAlignment = WD_CELL_ALIGN_VERTICAL_CENTER
    except Exception:
        pass

    align = WD_ALIGN_PARAGRAPH_LEFT if outcome_style else WD_ALIGN_PARAGRAPH_CENTER
    indent_chars = 2 if outcome_style else 0

    try:
        n = cell.Range.Paragraphs.Count
    except Exception:
        n = 0

    for i in range(1, n + 1):
        try:
            para = cell.Range.Paragraphs(i)
            pf = para.Format
            pf.Alignment = align
            pf.SpaceBefore = 0
            pf.SpaceAfter = 0
            pf.LineSpacingRule = WD_LINE_SPACE_SINGLE
            try:
                pf.CharacterUnitFirstLineIndent = indent_chars
                pf.CharacterUnitLeftIndent = 0
                pf.CharacterUnitRightIndent = 0
            except Exception:
                pf.FirstLineIndent = size_pt * indent_chars if indent_chars else 0
                pf.LeftIndent = 0
            _set_font_on_range(para.Range, size_pt)
        except Exception:
            pass


def format_fill_cell(
    doc,
    table,
    row: int,
    col: int,
    placeholder: str = None,
    *,
    outcome_coords: set = None,
    cell_meta: dict = None,
):
    """对单个可填格施加字体与段落格式（整格所有段落）"""
    try:
        cell = table.Rows(row).Cells(col)
        if not _cell_has_content(cell):
            return
        meta = cell_meta or {
            "table_index": 1,
            "row": row,
            "col": col,
            "placeholder": placeholder,
        }
        if cell_meta is None and table is not None:
            try:
                # 尽力带上 table_index（调用方通常已写入 cell_meta）
                pass
            except Exception:
                pass
        outcome = is_outcome_cell(meta, outcome_coords or set())
        size = SIZE_SIHAO
        rng = content_range(cell.Range)
        _set_font_on_range(rng, size)
        _apply_cell_alignment(cell, size, outcome_style=outcome)
    except Exception:
        pass


def format_paragraph_fill_range(
    rng,
    placeholder: str = None,
    *,
    outcome_coords: set = None,
    para_meta: dict = None,
):
    """表格外段落（如送达清单表头）"""
    try:
        if rng is None:
            return
        meta = para_meta or {"placeholder": placeholder}
        outcome = is_outcome_cell(meta, outcome_coords or set()) or is_outcome_placeholder(
            placeholder
        )
        size = SIZE_SIHAO
        _set_font_on_range(rng, size)
        align = WD_ALIGN_PARAGRAPH_LEFT if outcome else WD_ALIGN_PARAGRAPH_CENTER
        indent_chars = 2 if outcome else 0
        try:
            n = rng.Paragraphs.Count
        except Exception:
            n = 0
        for i in range(1, n + 1):
            try:
                para = rng.Paragraphs(i)
                pf = para.Format
                pf.Alignment = align
                pf.SpaceBefore = 0
                pf.SpaceAfter = 0
                pf.LineSpacingRule = WD_LINE_SPACE_SINGLE
                try:
                    pf.CharacterUnitFirstLineIndent = indent_chars
                    pf.CharacterUnitLeftIndent = 0
                except Exception:
                    pf.FirstLineIndent = size * indent_chars if indent_chars else 0
                _set_font_on_range(para.Range, size)
            except Exception:
                pass
    except Exception:
        pass


def apply_fill_cell_formatting(doc, template_name: str, manifest: dict) -> int:
    """对 manifest 中所有可填格/可填段落应用版式，返回处理格数"""
    from template_manifest import get_fill_cells, get_paragraph_fills

    outcome_coords = build_outcome_cell_coords(manifest)
    count = 0
    for cell in get_fill_cells(manifest):
        try:
            ti = cell["table_index"]
            table = doc.Tables(ti)
            format_fill_cell(
                doc,
                table,
                cell["row"],
                cell["col"],
                cell.get("placeholder"),
                outcome_coords=outcome_coords,
                cell_meta=cell,
            )
            count += 1
        except Exception:
            pass

    table_start = None
    try:
        if doc.Tables.Count >= 1:
            table_start = doc.Tables(1).Range.Start
    except Exception:
        pass

    for p in get_paragraph_fills(manifest):
        try:
            idx = p.get("index")
            if not idx:
                continue
            para = doc.Paragraphs(idx)
            rng = para.Range
            if table_start is not None and rng.End > table_start:
                rng = doc.Range(rng.Start, table_start)
            format_paragraph_fill_range(
                rng,
                p.get("placeholder"),
                outcome_coords=outcome_coords,
                para_meta=p,
            )
            count += 1
        except Exception:
            pass

    if count:
        print(
            f"  [OK] {template_name} 可填格版式：楷体_GB2312 四号、单元格垂直居中；"
            f"结案小结/审（办）结果左对齐+首行缩进2字，其余填入水平居中"
        )
    return count
