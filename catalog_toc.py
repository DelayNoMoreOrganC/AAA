#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""卷内目录 — 五类案件 Word 模板，仅填入页码列"""

import os
import re
import shutil
from typing import Dict, Optional

import archive_catalog as ac

PAGE_PLACEHOLDER_PREFIX = "页码"


def get_catalog_template_path(case_type: str) -> Optional[str]:
    try:
        from app_paths import get_catalog_template_path as _p
        return _p(case_type)
    except ImportError:
        return None


def build_page_fields(
    catalog,
    display_pages: Dict[int, int],
    toc_self_page: Optional[int] = None,
) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    if toc_self_page is not None:
        fields[f"{PAGE_PLACEHOLDER_PREFIX}目录"] = str(toc_self_page)
    for item in catalog:
        page = display_pages.get(item.seq)
        if page is not None:
            fields[f"{PAGE_PLACEHOLDER_PREFIX}{item.seq}"] = str(page)
    return fields


def _normalize_cell_text(text: str) -> str:
    return re.sub(r"[\s\u3000\r\n\t\a]+", "", text or "")


def _parse_seq_from_cell(text: str) -> Optional[int]:
    norm = _normalize_cell_text(text)
    if norm.isdigit():
        return int(norm)
    m = re.match(r"^(\d+)", norm)
    return int(m.group(1)) if m else None


def _safe_word_quit(word):
    try:
        word.Quit()
    except Exception:
        pass


def _page_count(doc) -> int:
    try:
        return int(doc.ComputeStatistics(2))
    except Exception:
        return 0


def _fit_catalog_one_page(doc, log=print) -> None:
    """将卷内目录 Word 表格压缩到 1 页内。"""
    target = 1
    before = _page_count(doc)
    if before <= target:
        return

    WD_LINE_EXACTLY = 4
    WD_ROW_AT_LEAST = 1
    steps = ((10.5, 13.0), (9.0, 11.5), (8.0, 10.5), (7.0, 9.5), (6.5, 8.5))

    for font_pt, line_pt in steps:
        try:
            for ti in range(1, doc.Tables.Count + 1):
                table = doc.Tables(ti)
                for ri in range(1, table.Rows.Count + 1):
                    row = table.Rows(ri)
                    for ci in range(1, row.Cells.Count + 1):
                        rng = row.Cells(ci).Range
                        try:
                            rng.Font.Size = font_pt
                            for pi in range(1, rng.Paragraphs.Count + 1):
                                pf = rng.Paragraphs(pi).Format
                                pf.LineSpacingRule = WD_LINE_EXACTLY
                                pf.LineSpacing = line_pt
                                pf.SpaceBefore = 0
                                pf.SpaceAfter = 0
                        except Exception:
                            pass
                    try:
                        row.HeightRule = WD_ROW_AT_LEAST
                        row.Height = max(8.0, line_pt + 1)
                        row.AllowBreakAcrossPages = False
                    except Exception:
                        pass
            for si in range(1, doc.Sections.Count + 1):
                ps = doc.Sections(si).PageSetup
                for attr, val in (
                    ("TopMargin", 50),
                    ("BottomMargin", 50),
                    ("LeftMargin", 50),
                    ("RightMargin", 50),
                ):
                    try:
                        setattr(ps, attr, val)
                    except Exception:
                        pass
        except Exception:
            pass

        after = _page_count(doc)
        if after <= target:
            log(f"       [OK] 卷内目录 {before}→{after} 页（缩字 {font_pt}pt）")
            return

    log(f"       [WARN] 卷内目录仍 {_page_count(doc)} 页（目标 1 页）")


def _fill_table_pages(doc, catalog, display_pages: Dict[int, int], log=print) -> int:
    """填充目录表页码列：优先按序号列匹配 catalog seq，其次按名称模糊匹配"""
    filled = 0
    name_to_seq: Dict[str, int] = {}
    for item in catalog:
        key = _normalize_cell_text(item.name)
        if key:
            name_to_seq[key] = item.seq
        for part in re.split(r"[、，,（(]", item.name):
            part = _normalize_cell_text(part)
            if len(part) >= 2:
                name_to_seq[part] = item.seq

    try:
        for ti in range(1, doc.Tables.Count + 1):
            table = doc.Tables(ti)
            rows = table.Rows.Count
            if rows < 2:
                continue
            cols = table.Rows(1).Cells.Count
            page_col = cols
            for ci in range(1, cols + 1):
                hdr = _normalize_cell_text(table.Rows(1).Cells(ci).Range.Text)
                if "页" in hdr:
                    page_col = ci
                    break
            seq_col = 1
            name_col = 2 if cols >= 2 else 1

            for ri in range(2, rows + 1):
                seq = _parse_seq_from_cell(table.Rows(ri).Cells(seq_col).Range.Text)
                if seq is None:
                    try:
                        norm = _normalize_cell_text(table.Rows(ri).Cells(name_col).Range.Text)
                    except Exception:
                        norm = ""
                    for k, s in name_to_seq.items():
                        if k and (k in norm or norm in k):
                            seq = s
                            break
                if seq is None or seq not in display_pages:
                    continue
                try:
                    cell = table.Rows(ri).Cells(page_col)
                    cell.Range.Text = str(display_pages[seq])
                    filled += 1
                except Exception:
                    pass
    except Exception as e:
        log(f"       [WARN] 表格页码填充: {e}")
    return filled


def fill_catalog_template(
    case_type: str,
    display_pages: Dict[int, int],
    output_docx: str,
    toc_self_page: Optional[int] = None,
    log=print,
) -> Optional[str]:
    """用 Word 打开卷内目录模板，仅填页码列，保存 docx"""
    template_path = get_catalog_template_path(case_type)
    if not template_path or not os.path.isfile(template_path):
        log(f"       [WARN] 卷内目录模板不存在: {template_path or case_type}")
        return None

    os.makedirs(os.path.dirname(os.path.abspath(output_docx)) or ".", exist_ok=True)

    try:
        import win32com.client
        import pythoncom
    except ImportError:
        log("       [WARN] 未安装 pywin32，无法填充卷内目录模板")
        return None

    catalog = ac.get_catalog(case_type)

    # 如果模板是 .doc 格式，先转换为 .docx
    work_template = template_path
    if template_path.lower().endswith(".doc"):
        try:
            import tempfile
            temp_dir = tempfile.gettempdir()
            temp_docx = os.path.join(temp_dir, f"temp_catalog_{case_type}.docx")

            pythoncom.CoInitialize()
            word = None
            try:
                word = win32com.client.DispatchEx("Word.Application")
                word.Visible = False
                word.DisplayAlerts = 0
                doc = word.Documents.Open(os.path.abspath(template_path))
                doc.SaveAs2(os.path.abspath(temp_docx), FileFormat=16)  # 16 = wdFormatXMLDocument
                doc.Close(False)
                work_template = temp_docx
                log(f"       [INFO] 模板格式转换: .doc → .docx")
            except Exception as e:
                log(f"       [WARN] .doc → .docx 转换失败: {e}")
            finally:
                if word is not None:
                    _safe_word_quit(word)
        except Exception as e:
            log(f"       [WARN] 模板转换初始化失败: {e}")

    # 使用转换后的 .docx 文件或原始模板
    word = None
    doc = None
    try:
        pythoncom.CoInitialize()
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(os.path.abspath(work_template))
        n = _fill_table_pages(doc, catalog, display_pages, log=log)
        if n == 0:
            log("       [WARN] 卷内目录表格未填入任何页码")
            return None
        _fit_catalog_one_page(doc, log=log)
        out_abs = os.path.abspath(output_docx)
        if out_abs.lower().endswith(".docx"):
            doc.SaveAs2(out_abs, FileFormat=16)
        else:
            doc.SaveAs2(out_abs + "x", FileFormat=16)
            output_docx = out_abs + "x"
        log(f"       卷内目录已填 {n} 处页码 → {os.path.basename(output_docx)}")
        return output_docx
    except Exception as e:
        log(f"       [WARN] 卷内目录 Word 填充失败: {e}")
        return None
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if word is not None:
            _safe_word_quit(word)


def catalog_toc_to_pdf(
    case_type: str,
    display_pages: Dict[int, int],
    output_pdf: str,
    work_dir: str,
    toc_self_page: Optional[int] = None,
    log=print,
) -> Optional[str]:
    os.makedirs(work_dir, exist_ok=True)
    label = ac.CASE_TYPE_LABELS.get(case_type, case_type)
    docx_out = os.path.join(work_dir, f"卷内目录_{label}.docx")
    docx = fill_catalog_template(
        case_type, display_pages, docx_out, toc_self_page=toc_self_page, log=log
    )
    if not docx:
        return None
    tmp_pdf = docx.replace(".docx", "_tmp.pdf")
    try:
        from archive_pipeline import docx_to_pdf
        if docx_to_pdf(docx, tmp_pdf, log=log) and os.path.isfile(tmp_pdf):
            shutil.copy2(tmp_pdf, output_pdf)
            return output_pdf
    except Exception as e:
        log(f"       [WARN] 卷内目录 docx→pdf 失败: {e}")
    return None


def compute_display_pages(
    body_starts: Dict[int, int],
    cover_end_idx: int,
    toc_pages: int = 1,
) -> Dict[int, int]:
    pages: Dict[int, int] = {}

    def _display(body_idx: int) -> int:
        if body_idx < cover_end_idx:
            return body_idx + 1
        return body_idx + toc_pages + 1

    for seq, body_idx in body_starts.items():
        pages[seq] = _display(body_idx)
    return pages
