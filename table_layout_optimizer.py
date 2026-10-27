#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V1.3 表格版式：仅分页约束与几何校验，不整格改字号/强制行高"""

ROW_HEIGHT_TOLERANCE_PT = 0.5
WD_ROW_HEIGHT_AUTO = 0
WD_ROW_HEIGHT_AT_LEAST = 1
WD_ROW_HEIGHT_EXACTLY = 2


def _row_spec(height, rule):
    return {"height": float(height), "rule": int(rule)}


def snapshot_table_row_heights(doc) -> dict:
    """记录各表行高与 HeightRule（用于填充后恢复）"""
    snap = {}
    try:
        for ti in range(1, doc.Tables.Count + 1):
            table = doc.Tables(ti)
            rows = {}
            for ri in range(1, table.Rows.Count + 1):
                try:
                    row = table.Rows(ri)
                    rows[ri] = _row_spec(row.Height, row.HeightRule)
                except Exception:
                    pass
            snap[ti] = rows
    except Exception:
        pass
    return snap


def restore_table_row_heights(doc, snapshot: dict, *, template_name: str = None) -> int:
    """将表格行高恢复为快照值（保留 AtLeast/Exactly/Auto）；返回恢复行数"""
    if not snapshot:
        return 0
    restored = 0
    try:
        for ti, rows in snapshot.items():
            if ti < 1 or ti > doc.Tables.Count:
                continue
            table = doc.Tables(ti)
            for ri, spec in rows.items():
                if ri < 1 or ri > table.Rows.Count:
                    continue
                if isinstance(spec, (int, float)):
                    height, rule = float(spec), WD_ROW_HEIGHT_EXACTLY
                else:
                    height = float(spec.get("height", 0))
                    rule = int(spec.get("rule", WD_ROW_HEIGHT_AUTO))
                try:
                    row = table.Rows(ri)
                    if rule == WD_ROW_HEIGHT_AUTO and height <= 0:
                        row.HeightRule = WD_ROW_HEIGHT_AUTO
                        restored += 1
                        continue
                    if height <= 0:
                        continue
                    use_rule = rule if rule in (
                        WD_ROW_HEIGHT_AUTO,
                        WD_ROW_HEIGHT_AT_LEAST,
                        WD_ROW_HEIGHT_EXACTLY,
                    ) else WD_ROW_HEIGHT_AT_LEAST
                    row.HeightRule = use_rule
                    row.Height = height
                    restored += 1
                except Exception:
                    pass
    except Exception:
        pass
    return restored


def lock_table_row_heights_from_snapshot(doc, snapshot: dict) -> int:
    """填充前锁定行高为模板快照（与 restore 相同，语义区分调用点）"""
    return restore_table_row_heights(doc, snapshot)


def compare_table_geometry(tpl_doc, out_doc, row_tol=ROW_HEIGHT_TOLERANCE_PT) -> list:
    """对比模板与输出表格行高（.doc 与 .docx 列宽读数不可靠，仅比行高）"""
    errors = []
    try:
        n_tables = min(tpl_doc.Tables.Count, out_doc.Tables.Count)
        for ti in range(1, n_tables + 1):
            tpl_t = tpl_doc.Tables(ti)
            out_t = out_doc.Tables(ti)
            for ri in range(1, min(tpl_t.Rows.Count, out_t.Rows.Count) + 1):
                try:
                    th = float(tpl_t.Rows(ri).Height)
                    oh = float(out_t.Rows(ri).Height)
                    if th > 0 and oh > 0 and abs(th - oh) > row_tol:
                        errors.append(f"T{ti} R{ri} 行高 {oh:.1f}pt != 模板 {th:.1f}pt")
                except Exception:
                    pass
    except Exception as e:
        errors.append(f"几何对比失败: {e}")
    return errors


def _link_table_with_previous_paragraphs(doc, table):
    try:
        start = table.Range.Start
        if start <= 1:
            return
        for i in range(doc.Paragraphs.Count, 0, -1):
            try:
                para = doc.Paragraphs(i)
                if para.Range.End <= start and para.Range.End > start - 800:
                    para.Range.ParagraphFormat.KeepWithNext = True
                    para.Range.ParagraphFormat.KeepTogether = True
            except Exception:
                pass
            if i < doc.Paragraphs.Count - 30:
                break
    except Exception:
        pass


def _apply_table_page_constraints(table):
    """仅分页约束，不调用 AutoFitBehavior（会改变列宽）"""
    try:
        pf = table.Range.ParagraphFormat
        pf.KeepTogether = True
        pf.KeepWithNext = False
        pf.WidowControl = False
    except Exception:
        pass
    try:
        for ri in range(1, table.Rows.Count + 1):
            try:
                table.Rows(ri).AllowBreakAcrossPages = False
            except Exception:
                pass
    except Exception:
        pass


def optimize_document_tables(doc, template_name=None, **_kwargs):
    """仅应用分页约束，不修改字号/行高（V1.3）"""
    count = 0
    try:
        for ti in range(1, doc.Tables.Count + 1):
            try:
                table = doc.Tables(ti)
                _apply_table_page_constraints(table)
                if ti == 1:
                    _link_table_with_previous_paragraphs(doc, table)
                count += 1
            except Exception:
                pass
    except Exception:
        pass

    if count:
        print(f"  [OK] 已应用 {count} 个表格分页约束（不改行高/字号）")
    return count
