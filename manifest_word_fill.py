#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按映射表填充 Word 文档（V1.3 原子替换，仅可填格）"""

from template_manifest import (
    get_fill_cells,
    get_paragraph_fills,
    group_cell_offset_hints,
    group_cell_patches,
    load_manifest,
    validate_manifest_against_doc,
)
from word_atomic_fill import (
    content_range,
    replace_placeholders_atomic,
    strip_reference_format_atomic,
)


def _use_textbox_fill(template_name: str = None) -> bool:
    if template_name == "立案审批表":
        return False
    try:
        from settings import get_fill_mode

        return get_fill_mode() == "textbox"
    except ImportError:
        return False


def _cell_range(doc, table_index, row, col):
    table = doc.Tables(table_index)
    return table.Rows(row).Cells(col).Range


def _paragraph_range(doc, para_index, table_start=None):
    para = doc.Paragraphs(para_index)
    rng = para.Range
    if table_start is not None and rng.End > table_start:
        return doc.Range(rng.Start, table_start)
    return rng


def _table_range_start(doc):
    if doc.Tables.Count < 1:
        return None
    return doc.Tables(1).Range.Start


def fill_document_by_manifest(
    doc,
    template_name: str,
    field_patch: dict,
    blacken_fn=None,
    validate: bool = False,
) -> tuple:
    """
    按 templates/manifests/{template}.json 仅填充标记为 fill/clear 的格与段落。
    返回 (替换次数, filled_coords, value_ranges)。
    """
    manifest = load_manifest(template_name)
    if validate:
        errs = validate_manifest_against_doc(doc, manifest)
        if errs:
            print(f"  [WARN] 映射表校验 {len(errs)} 项（仍将尝试填充）")
            for e in errs[:5]:
                print(f"         {e}")

    fill_cells = get_fill_cells(manifest)
    grouped = group_cell_patches(fill_cells, field_patch)
    offset_hints = group_cell_offset_hints(fill_cells)
    total = 0
    filled_coords = set()
    table_start = _table_range_start(doc)

    # 调试日志：检查关键字段
    if template_name == "送达材料清单":
        key_field = "判决书上代理律师"
        if key_field in field_patch:
            print(f"  [DEBUG] 字典中包含 {key_field}: \"{field_patch[key_field]}\"")
        else:
            print(f"  [DEBUG] 字典中缺失 {key_field}")
            print(f"  [DEBUG] 字典包含的字段: {list(field_patch.keys())[:10]}")

    if _use_textbox_fill(template_name):
        from textbox_fill import fill_textbox_by_manifest

        # 调试日志
        if template_name == "送达材料清单":
            print(f"  [DEBUG] 使用textbox填充模式")
            for key in field_patch.keys():
                if "律师" in key:
                    print(f"  [DEBUG] textbox字段 {key}: \"{field_patch[key]}\"")

        tb_total, tb_coords = fill_textbox_by_manifest(
            doc, template_name, field_patch, blacken_fn=blacken_fn
        )
        total += tb_total
        filled_coords.update(tb_coords)
        for (ti, row, col), patch in grouped.items():
            if patch and any("案号" in k for k in patch):
                try:
                    strip_reference_format_atomic(doc, _cell_range(doc, ti, row, col))
                except Exception:
                    pass
    else:
        for (ti, row, col), patch in grouped.items():
            if not patch:
                continue
            # 调试日志：检查送达材料清单的填充情况
            if template_name == "送达材料清单":
                for key in patch.keys():
                    if "律师" in key:
                        print(f"  [DEBUG] 尝试填充 {key}: \"{patch[key]}\" 到 位置(表格{ti}, 行{row}, 列{col})")
            try:
                rng = _cell_range(doc, ti, row, col)
                hints = offset_hints.get((ti, row, col), {})
                n = replace_placeholders_atomic(
                    doc,
                    rng,
                    patch,
                    blacken_fn=blacken_fn,
                    placeholder_offsets=hints,
                    fit_long_text=(template_name != "立案审批表"),
                )
                total += n
                if n:
                    filled_coords.add((ti, row, col))
                if n and any("案号" in k for k in patch):
                    strip_reference_format_atomic(doc, rng)
            except Exception as e:
                import sys
                print(f"  [WARN] 填充 T{ti} R{row} C{col}: {e}", file=sys.stderr)

    for p in get_paragraph_fills(manifest):
        idx = p.get("index")
        if not idx:
            continue
        ph = p.get("placeholder")
        if not ph:
            continue
        val = field_patch.get(ph, "" if p.get("role") == "clear" else None)
        if val is None and p.get("role") != "clear":
            continue
        try:
            rng = _paragraph_range(doc, idx, table_start)
            off = {ph: p["offset"]} if p.get("offset") else {}
            n = replace_placeholders_atomic(
                doc,
                rng,
                {ph: str(val)},
                blacken_fn=blacken_fn,
                placeholder_offsets=off,
            )
            total += n
        except Exception:
            pass

    return total, filled_coords


def fill_seq_cells_by_manifest(doc, template_name: str, sequential: dict, blacken_fn=None) -> tuple:
    """按 manifest 中 role=seq_fill 的格，逐行填入列表值"""
    if _use_textbox_fill(template_name):
        from textbox_fill import fill_seq_textboxes_by_manifest

        return fill_seq_textboxes_by_manifest(
            doc, template_name, sequential, blacken_fn=blacken_fn
        )

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
                base = content_range(rng)
                if bracketed not in (base.Text or "").replace("\x07", ""):
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
    from textbox_fill import clear_unfilled_seq_placeholders

    cleared = clear_unfilled_seq_placeholders(doc, template_name, filled_coords)
    if cleared:
        print(f"  [OK] {template_name} 已清除 {cleared} 处未填写的 seq 占位符")
    return total, filled_coords
