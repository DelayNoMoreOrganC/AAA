#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将模板可填格转换为固定文本框（需本机 Word）"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pythoncom
import win32com.client

from field_mapping import get_template_paths
from template_manifest import TEMPLATE_NAMES, get_fill_cells, load_manifest
from textbox_fill import default_shape_name, ensure_textbox_in_cell
from word_atomic_fill import content_range

WD_FORMAT_DOCX = 16


def convert_template(template_name: str, save_docx: bool = True) -> int:
    manifest = load_manifest(template_name)
    tpl_path = get_template_paths()[template_name]
    fill_cells = [c for c in get_fill_cells(manifest) if c.get("role") != "header"]

    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    count = 0
    try:
        doc = word.Documents.Open(os.path.abspath(tpl_path))
        for cell in fill_cells:
            ti, row, col = cell["table_index"], cell["row"], cell["col"]
            tb = cell.get("textbox") or {}
            shape_name = tb.get("shape_name") or default_shape_name(
                template_name, ti, row, col
            )
            ph = cell.get("placeholder", "")
            try:
                rng = doc.Tables(ti).Rows(row).Cells(col).Range
                if ensure_textbox_in_cell(doc, rng, shape_name, ph):
                    count += 1
            except Exception as e:
                print(f"  [WARN] T{ti} R{row}C{col}: {e}")

        if save_docx:
            out = tpl_path.replace(".doc", "_textbox.docx")
            doc.SaveAs2(os.path.abspath(out), FileFormat=WD_FORMAT_DOCX)
            print(f"  已保存: {out}")
        else:
            doc.Save()
        doc.Close(False)
    finally:
        try:
            word.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()
    return count


def main():
    names = sys.argv[1:] if len(sys.argv) > 1 else list(TEMPLATE_NAMES)
    for name in names:
        print(f"\n=== {name} ===")
        n = convert_template(name)
        print(f"[OK] 创建/更新 {n} 个文本框")
    return 0


if __name__ == "__main__":
    sys.exit(main())
