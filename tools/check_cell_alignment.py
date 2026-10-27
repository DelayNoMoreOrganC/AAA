#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查输出 docx 可填格段落对齐（0=左 1=中 3=两端）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pythoncom
import win32com.client
from fill_cell_format import build_outcome_cell_coords, is_outcome_cell
from template_manifest import load_manifest, get_fill_cells

WD = {0: "left", 1: "center", 2: "right", 3: "justify"}


def check_docx(path, template_name):
    m = load_manifest(template_name)
    outcome_coords = build_outcome_cell_coords(m)
    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    doc = word.Documents.Open(os.path.abspath(path))
    issues = []
    for cell in get_fill_cells(m):
        if cell.get("role") not in ("fill", "header_fill", "seq_fill"):
            continue
        ti, r, col = cell["table_index"], cell["row"], cell["col"]
        cr = doc.Tables(ti).Rows(r).Cells(col).Range
        txt = (cr.Text or "").replace("\x07", "").strip()
        if not txt:
            continue
        expect_center = not is_outcome_cell(cell, outcome_coords)
        aligns = []
        for i in range(1, cr.Paragraphs.Count + 1):
            aligns.append(int(cr.Paragraphs(i).Format.Alignment))
        ok = (all(a == 1 for a in aligns) if expect_center else all(a == 0 for a in aligns))
        if not ok:
            issues.append(
                f"  R{r}C{col} expect={'center' if expect_center else 'left'} "
                f"got={[WD.get(a, a) for a in aligns]} text={txt[:30]!r}"
            )
    doc.Close(False)
    try:
        word.Quit()
    except Exception:
        pass
    pythoncom.CoUninitialize()
    return issues


if __name__ == "__main__":
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "outputs/v136_center_test"
    for name in ("立案审批表", "送达材料清单", "档案卷宗", "结案报告表", "质量监督卡"):
        p = os.path.join(out_dir, f"{name}.docx")
        if not os.path.isfile(p):
            print(f"[SKIP] {p}")
            continue
        iss = check_docx(p, name)
        if iss:
            print(f"[FAIL] {name}")
            print("\n".join(iss))
        else:
            print(f"[OK] {name} 可填格对齐符合预期")
