#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""填充结果版式校验（供流水线与 tools 共用）"""

import os

from field_mapping import get_template_paths
from table_layout_optimizer import compare_table_geometry
from template_manifest import get_fill_cells, get_fixed_cells, load_manifest, TEMPLATE_NAMES


def _cell_text(cell):
    return (cell.Range.Text or "").replace("\x07", "").replace("\r", "").strip()


def verify_template(name: str, filled_path: str, field_data=None) -> list:
    """对比模板与填充结果：固定格、页数、行高、【】残留"""
    errors = []
    manifest = load_manifest(name)
    tpl_path = get_template_paths()[name]
    if not os.path.isfile(filled_path):
        return [f"输出文件不存在: {filled_path}"]
    if not os.path.isfile(tpl_path):
        return [f"模板不存在: {tpl_path}"]

    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        tpl = word.Documents.Open(os.path.abspath(tpl_path))
        out = word.Documents.Open(os.path.abspath(filled_path))
        try:
            tpl_pages = tpl.ComputeStatistics(2)
            out_pages = out.ComputeStatistics(2)
            try:
                from output_options import TEMPLATE_PAGE_BUDGET

                page_budget = TEMPLATE_PAGE_BUDGET.get(name, tpl_pages)
            except ImportError:
                page_budget = tpl_pages
            if out_pages > page_budget:
                errors.append(f"页数超出预算: 预算{page_budget}页 -> 输出{out_pages}页")

            errors.extend(compare_table_geometry(tpl, out))

            for cell in get_fixed_cells(manifest):
                try:
                    ti, ri, ci = cell["table_index"], cell["row"], cell["col"]
                    t1 = _cell_text(tpl.Tables(ti).Rows(ri).Cells(ci))
                    t2 = _cell_text(out.Tables(ti).Rows(ri).Cells(ci))
                    if t1 != t2 and "【" not in t1:
                        allowed_clear = ("页码识别", "可以的话")
                        if any(s in t1 for s in allowed_clear) and not t2:
                            continue
                        if (
                            name == "质量监督卡"
                            and "至高" in t1
                            and t2 == t1.replace("（固定）", "").replace("(固定)", "")
                        ):
                            continue
                        errors.append(
                            f"固定格 T{ti} R{ri}C{ci} 文本变化: 模板={t1[:30]!r} 输出={t2[:30]!r}"
                        )
                    if "【" in t2:
                        errors.append(f"固定格 T{ti} R{ri}C{ci} 仍有【】")
                except Exception as e:
                    errors.append(f"固定格 R{cell.get('row')}C{cell.get('col')}: {e}")

            for cell in get_fill_cells(manifest):
                if cell.get("role") == "seq_fill":
                    continue
                try:
                    ti, ri, ci = cell["table_index"], cell["row"], cell["col"]
                    t2 = _cell_text(out.Tables(ti).Rows(ri).Cells(ci))
                    if "【" in t2:
                        ph = cell.get("placeholder", "")
                        errors.append(
                            f"可填格 T{ti} R{ri}C{ci} 未替换完: 仍含【{ph[:20]}】"
                        )
                except Exception:
                    pass
        finally:
            out.Close(False)
            tpl.Close(False)
    finally:
        try:
            word.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()
    return errors


def verify_output_layout(output_dir: str, field_data: dict = None, log=print) -> list:
    """校验输出目录下全部 docx 版式；返回问题列表"""
    issues = []
    for name in TEMPLATE_NAMES:
        path = os.path.join(output_dir, f"{name}.docx")
        if not os.path.isfile(path):
            continue
        try:
            errs = verify_template(name, path, field_data)
            for e in errs:
                msg = f"{name}: {e}"
                issues.append(msg)
                log(f"  [LAYOUT] {msg}")
        except Exception as ex:
            msg = f"{name}: 版式校验失败 {ex}"
            issues.append(msg)
            log(f"  [LAYOUT] {msg}")
    return issues
