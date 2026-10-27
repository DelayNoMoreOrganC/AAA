#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V2.0.3 文本框填充：表格结构固定，仅写 TextFrame 内容"""

import re

from word_atomic_fill import FIT_CHAR_THRESHOLD, FIT_LINE_SPACINGS, FIT_SIZES, clear_range_bold, content_range

WD_ROW_HEIGHT_EXACTLY = 2
MSO_TEXT_ORIENTATION_HORIZONTAL = 1

CELL_END = "\x07"


def default_shape_name(template_name: str, table_index: int, row: int, col: int) -> str:
    safe = re.sub(r'[<>:"/\\|?*\s]', "_", template_name or "tpl")
    return f"fill_{safe}_T{table_index}_R{row}C{col}"


def _plain(text: str) -> str:
    return (text or "").replace(CELL_END, "").replace("\r", "").replace("\n", "")


def find_shape_in_cell(doc, cell_rng, shape_name: str):
    """在单元格范围内按 Name 查找 Shape"""
    if not shape_name:
        return None
    try:
        base = content_range(cell_rng)
        start, end = base.Start, base.End
        for i in range(1, doc.Shapes.Count + 1):
            try:
                shp = doc.Shapes(i)
                if shp.Name != shape_name:
                    continue
                a_start = shp.Anchor.Start
                if start <= a_start < end:
                    return shp
            except Exception:
                pass
    except Exception:
        pass
    return None


def ensure_textbox_in_cell(doc, cell_rng, shape_name: str, placeholder: str = ""):
    """若单元格无文本框则创建固定尺寸文本框"""
    existing = find_shape_in_cell(doc, cell_rng, shape_name)
    if existing:
        return existing

    try:
        cell = cell_rng.Cells(1)
        width = max(float(cell.Width) - 4, 20)
        height = max(float(cell.Height) - 2, 12)

        inline = cell.Range.InlineShapes.AddTextbox(
            MSO_TEXT_ORIENTATION_HORIZONTAL,
            width,
            height,
        )
        shp = inline.ConvertToShape()
        shp.Name = shape_name
        shp.WrapFormat.Type = 7  # wdWrapInline
        try:
            shp.TextFrame.AutoSize = False
            shp.TextFrame.WordWrap = True
            shp.TextFrame.MarginLeft = 1
            shp.TextFrame.MarginRight = 1
            shp.TextFrame.MarginTop = 1
            shp.TextFrame.MarginBottom = 1
        except Exception:
            pass

        if placeholder:
            token = f"【{placeholder}】" if not placeholder.startswith("=") else placeholder
            try:
                shp.TextFrame.TextRange.Text = token
            except Exception:
                pass
        return shp
    except Exception:
        return None


def _fit_textbox_text(text_range, text: str, max_chars: int = 0):
    """文本框内阶梯缩字"""
    val = text or ""
    if max_chars and len(val) > max_chars:
        val = val[: max_chars - 1] + "…"
    try:
        text_range.Text = val
    except Exception:
        return
    try:
        text_range.Font.Bold = 0
    except Exception:
        pass
    clear_range_bold(text_range)
    if len(val) <= FIT_CHAR_THRESHOLD:
        return
    for size, spacing in zip(FIT_SIZES, FIT_LINE_SPACINGS):
        try:
            text_range.Font.Size = size
            text_range.ParagraphFormat.LineSpacingRule = 4
            text_range.ParagraphFormat.LineSpacing = spacing
        except Exception:
            pass


def fill_textbox_cell(doc, cell_rng, shape_name: str, value: str, placeholder: str = "", max_chars: int = 0, blacken_fn=None):
    """写入单个文本框；成功返回 True"""
    shp = find_shape_in_cell(doc, cell_rng, shape_name)
    if not shp:
        shp = ensure_textbox_in_cell(doc, cell_rng, shape_name, placeholder)
    if not shp:
        return False

    try:
        tr = shp.TextFrame.TextRange
        base_text = _plain(tr.Text or "")
        token = f"【{placeholder}】" if placeholder and not placeholder.startswith("=") else placeholder

        if token and token in base_text:
            new_text = base_text.replace(token, str(value or ""), 1)
        else:
            new_text = str(value or "")

        _fit_textbox_text(tr, new_text, max_chars=max_chars)
        if blacken_fn:
            blacken_fn(tr)
        return True
    except Exception:
        return False


def fill_textbox_by_manifest(
    doc,
    template_name: str,
    field_patch: dict,
    blacken_fn=None,
) -> tuple:
    """按 manifest textbox 映射填充；无文本框时回退原子替换"""
    from manifest_word_fill import _cell_range
    from template_manifest import get_fill_cells, group_cell_patches, load_manifest
    from word_atomic_fill import replace_placeholders_atomic

    manifest = load_manifest(template_name)
    fill_cells = [c for c in get_fill_cells(manifest) if c.get("role") != "seq_fill"]
    grouped = group_cell_patches(fill_cells, field_patch)

    total = 0
    filled_coords = set()

    for (ti, row, col), patch in grouped.items():
        if not patch:
            continue
        try:
            rng = _cell_range(doc, ti, row, col)
            cell_meta = next(
                (
                    c
                    for c in fill_cells
                    if c["table_index"] == ti and c["row"] == row and c["col"] == col
                ),
                {},
            )
            tb = cell_meta.get("textbox") or {}
            shape_name = tb.get("shape_name") or default_shape_name(
                template_name, ti, row, col
            )
            max_chars = int(tb.get("max_chars") or 0)

            cell_ok = True
            for ph, val in patch.items():
                # 调试日志
                if template_name == "送达材料清单" and "律师" in ph:
                    print(f"  [DEBUG textbox fill] 尝试替换占位符: {ph} = \"{val}\"")
                ok = fill_textbox_cell(
                    doc,
                    rng,
                    shape_name,
                    val,
                    placeholder=ph,
                    max_chars=max_chars,
                    blacken_fn=blacken_fn,
                )
                if not ok:
                    cell_ok = False
                    break

            if cell_ok:
                total += len(patch)
                filled_coords.add((ti, row, col))
            else:
                hints = {}
                if cell_meta.get("offset"):
                    for ph in patch:
                        hints[ph] = cell_meta["offset"]
                n = replace_placeholders_atomic(
                    doc, rng, patch, blacken_fn=blacken_fn, placeholder_offsets=hints
                )
                total += n
                if n:
                    filled_coords.add((ti, row, col))
        except Exception as e:
            import sys

            print(f"  [WARN] 文本框填充 T{ti} R{row} C{col}: {e}", file=sys.stderr)

    # 处理段落占位符（送达材料清单的paragraph类型占位符）
    try:
        print(f"  [DEBUG] 开始处理段落占位符，模板: {template_name}")
        from template_manifest import get_paragraph_fills
        from manifest_word_fill import _paragraph_range, _table_range_start

        paragraph_fills = get_paragraph_fills(manifest)
        print(f"  [DEBUG] get_paragraph_fills返回: {len(paragraph_fills)}个段落")
        if paragraph_fills:
            table_start = _table_range_start(doc)
            for p in paragraph_fills:
                idx = p.get("index")
                if not idx:
                    continue
                ph = p.get("placeholder")
                if not ph:
                    continue
                val = field_patch.get(ph, "" if p.get("role") == "clear" else None)
                if val is None and p.get("role") != "clear":
                    print(f"  [DEBUG] 跳过段落 {ph}（val为None且role不是clear）")
                    continue

                # 调试日志
                print(f"  [DEBUG] 准备处理段落 {ph}, val=\"{val}\", role={p.get('role')}")
                if template_name == "送达材料清单" and "律师" in ph:
                    print(f"  [DEBUG textbox paragraph] 尝试填充段落占位符: {ph} = \"{val}\"")

                try:
                    print(f"  [DEBUG] 开始处理段落 index={idx}, ph={ph}")
                    rng = _paragraph_range(doc, idx, table_start)
                    print(f"  [DEBUG] _paragraph_range成功，range长度: {rng.End - rng.Start}")
                    off = {ph: p["offset"]} if p.get("offset") else {}
                    print(f"  [DEBUG] offset配置: {off}")
                    n = replace_placeholders_atomic(
                        doc,
                        rng,
                        {ph: str(val)},
                        blacken_fn=blacken_fn,
                        placeholder_offsets=off,
                    )
                    print(f"  [DEBUG] replace_placeholders_atomic返回: {n}")
                    if n:
                        total += n
                        # 调试日志
                        if template_name == "送达材料清单" and "律师" in ph:
                            print(f"  [DEBUG textbox paragraph] 成功填充段落占位符: {ph}")
                except Exception as e:
                    import sys
                    print(f"  [WARN] 文本框段落填充 idx={idx}, ph={ph}: {e}", file=sys.stderr)
    except Exception as e:
        import sys
        print(f"  [WARN] 处理段落占位符时出错: {e}", file=sys.stderr)

    return total, filled_coords


def fill_seq_textboxes_by_manifest(doc, template_name: str, sequential: dict, blacken_fn=None) -> tuple:
    """seq_fill 格按行填入文本框"""
    from manifest_word_fill import _cell_range
    from template_manifest import get_fill_cells, load_manifest
    from word_atomic_fill import replace_placeholders_atomic

    manifest = load_manifest(template_name)
    seq_cells = [c for c in get_fill_cells(manifest) if c.get("role") == "seq_fill"]
    if not seq_cells:
        return 0, set()

    total = 0
    filled_coords = set()

    for placeholder, values in (sequential or {}).items():
        if not values:
            continue
        cells = [c for c in seq_cells if c.get("placeholder") == placeholder]
        cells.sort(key=lambda c: (c["table_index"], c["row"], c["col"]))
        idx = 0
        bracketed = f"【{placeholder}】"
        for cell in cells:
            if idx >= len(values):
                break
            try:
                rng = _cell_range(doc, cell["table_index"], cell["row"], cell["col"])
                tb = cell.get("textbox") or {}
                shape_name = tb.get("shape_name") or default_shape_name(
                    template_name, cell["table_index"], cell["row"], cell["col"]
                )
                base = content_range(rng)
                has_ph = bracketed in _plain(base.Text or "")
                shp = find_shape_in_cell(doc, rng, shape_name)

                if shp or has_ph:
                    ok = fill_textbox_cell(
                        doc,
                        rng,
                        shape_name,
                        values[idx],
                        placeholder=placeholder,
                        blacken_fn=blacken_fn,
                    )
                    if ok:
                        total += 1
                        filled_coords.add(
                            (cell["table_index"], cell["row"], cell["col"])
                        )
                        idx += 1
                        continue

                hint = {placeholder: cell["offset"]} if cell.get("offset") else {}
                n = replace_placeholders_atomic(
                    doc,
                    rng,
                    {placeholder: values[idx]},
                    blacken_fn=blacken_fn,
                    placeholder_offsets=hint,
                )
                if n:
                    total += n
                    filled_coords.add(
                        (cell["table_index"], cell["row"], cell["col"])
                    )
                    idx += 1
            except Exception:
                pass
    cleared = clear_unfilled_seq_placeholders(doc, template_name, filled_coords)
    if cleared:
        import sys

        print(
            f"  [OK] {template_name} 已清除 {cleared} 处未填写的 seq 占位符",
            file=sys.stderr,
        )
    return total, filled_coords


def clear_unfilled_seq_placeholders(
    doc, template_name: str, filled_coords: set = None
) -> int:
    """seq_fill 格未填入文件时，清空文本框/单元格内残留的占位符或说明文字。"""
    from manifest_word_fill import _cell_range
    from post_fill_cleanup import clear_loose_bracket_chars, clear_remaining_brackets
    from template_manifest import PLACEHOLDER_RE, get_fill_cells, load_manifest

    manifest = load_manifest(template_name)
    seq_cells = [c for c in get_fill_cells(manifest) if c.get("role") == "seq_fill"]
    if not seq_cells:
        return 0

    filled_coords = filled_coords or set()
    cleared = 0
    for cell in seq_cells:
        coord = (cell["table_index"], cell["row"], cell["col"])
        if coord in filled_coords:
            continue
        try:
            rng = _cell_range(doc, cell["table_index"], cell["row"], cell["col"])
            placeholder = cell.get("placeholder") or ""
            bracketed = f"【{placeholder}】" if placeholder else ""
            tb = cell.get("textbox") or {}
            shape_name = tb.get("shape_name") or default_shape_name(
                template_name, cell["table_index"], cell["row"], cell["col"]
            )
            shp = find_shape_in_cell(doc, rng, shape_name)
            if shp:
                try:
                    tr = shp.TextFrame.TextRange
                    base = _plain(tr.Text or "")
                    if (
                        not base
                        or (bracketed and bracketed in base)
                        or (placeholder and placeholder in base)
                        or PLACEHOLDER_RE.search(base)
                    ):
                        tr.Text = ""
                        cleared += 1
                    continue
                except Exception:
                    pass

            base = content_range(rng)
            plain = _plain(base.Text or "")
            if (
                not plain
                or (bracketed and bracketed in plain)
                or (placeholder and placeholder in plain)
                or PLACEHOLDER_RE.search(plain)
            ):
                cleared += clear_remaining_brackets(doc, rng)
                cleared += clear_loose_bracket_chars(doc, rng)
                plain2 = _plain(content_range(rng).Text or "")
                if placeholder and placeholder in plain2:
                    from word_atomic_fill import delete_substring_atomic

                    while delete_substring_atomic(doc, rng, placeholder):
                        cleared += 1
                plain3 = _plain(content_range(rng).Text or "")
                if plain3 in (placeholder, bracketed):
                    try:
                        doc.Range(base.Start, base.End).Text = ""
                        cleared += 1
                    except Exception:
                        pass
        except Exception:
            pass
    return cleared
