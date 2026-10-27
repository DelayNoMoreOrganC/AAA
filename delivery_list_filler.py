#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""律师所送达材料清单 — V1.3 映射表 + 原子替换"""

import os

from manifest_word_fill import fill_document_by_manifest, fill_seq_cells_by_manifest
from template_filler import WD_FORMAT_DOCX, _blacken_range, _split_field_data
from table_layout_optimizer import (
    optimize_document_tables,
    restore_table_row_heights,
    snapshot_table_row_heights,
)
from template_manifest import get_fixed_cells, load_manifest
from word_atomic_fill import content_range, delete_substring_atomic

TABLE_HEADER_LABELS = ("序号", "材料名称", "页数", "送达时间", "送达人", "接收人", "备注")
INSTRUCTION_SNIPPETS = ("页码识别", "可以的话")


def _restore_table_header_row(doc, table):
    """表头行恢复列名：仅重写表头格内容区（该格应仅有列名）"""
    try:
        row = table.Rows(1)
        for ci, label in enumerate(TABLE_HEADER_LABELS, 1):
            if ci > row.Cells.Count:
                break
            cell_rng = row.Cells(ci).Range
            base = content_range(cell_rng)
            cur = (base.Text or "").replace("\r", "").strip()
            wrong = any(x in cur for x in ("承办", "代理律师", "【", "判决"))
            if not wrong and (not cur or cur == label or label in cur):
                continue
            try:
                doc.Range(base.Start, base.End).Text = label
                _blacken_range(content_range(cell_rng))
            except Exception:
                pass
    except Exception:
        pass


def _clear_instruction_cells_from_manifest(doc):
    """原子删除 fixed 格内的说明片段"""
    try:
        manifest = load_manifest("送达材料清单")
        for cell in get_fixed_cells(manifest):
            try:
                table = doc.Tables(cell["table_index"])
                c = table.Rows(cell["row"]).Cells(cell["col"])
                for snip in INSTRUCTION_SNIPPETS:
                    delete_substring_atomic(doc, c.Range, snip)
            except Exception:
                pass
    except Exception:
        pass


def word_fill_delivery_list(doc, field_data, output_path):
    """送达材料清单：映射表驱动填充"""
    normal, sequential = _split_field_data(field_data)

    row_snapshot = snapshot_table_row_heights(doc)
    filled_coords = set()

    n, coords = fill_document_by_manifest(
        doc,
        "送达材料清单",
        normal,
        blacken_fn=_blacken_range,
    )
    filled_coords.update(coords)
    if doc.Tables.Count < 1:
        raise RuntimeError("送达材料清单模板缺少表格")

    table = doc.Tables(1)
    _clear_instruction_cells_from_manifest(doc)

    seq_n, seq_coords = fill_seq_cells_by_manifest(
        doc,
        "送达材料清单",
        sequential,
        blacken_fn=_blacken_range,
    )
    filled_coords.update(seq_coords)
    if seq_n:
        print(f"  [OK] 送达清单材料名称列已填入 {seq_n} 份法院文书")

    _restore_table_header_row(doc, table)
    optimize_document_tables(doc, template_name="送达材料清单")
    restored = restore_table_row_heights(doc, row_snapshot)
    if restored:
        print(f"  [OK] 送达清单已恢复 {restored} 行表格行高")

    from post_fill_cleanup import finalize_fill_document

    finalize_fill_document(
        doc, "送达材料清单", blacken_fn=_blacken_range, field_patch=normal
    )

    try:
        from template_page_fit import fit_document_to_page_budget

        fit_document_to_page_budget(doc, "送达材料清单")
    except Exception as ex:
        print(f"  [WARN] 送达清单页数预算压缩跳过: {ex}")

    out_abs = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)
    doc.SaveAs2(out_abs, FileFormat=WD_FORMAT_DOCX)
    print(f"\n[OK] 送达材料清单完成（V1.3 原子填充），输出: {output_path}")
    return output_path
