#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 归档合并器 — 按 catalog_seq 整份插入，页守恒

原则：各源 PDF 的已映射页段必须完整插入（仅调整顺序，不删减）。
系统模板按目录序号插入；已映射文书按 catalog_seq 整段 insert_pdf。
"""

import os
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


@dataclass
class ArchiveResult:
    """归档结果"""
    output_pdf: str
    success: bool
    missing: List[Dict]
    page_count: int = 0
    sources: Dict[int, str] = None
    original_pages_included: int = 0
    order_issues: List[Dict] = None
    pagination: Optional[Dict] = None

    def __post_init__(self):
        if self.sources is None:
            self.sources = {}
        if self.order_issues is None:
            self.order_issues = []


def docx_to_pdf(docx_path: str, pdf_path: str, log=print) -> bool:
    try:
        from archive_pipeline import docx_to_pdf as _convert
        return _convert(docx_path, pdf_path, log=log)
    except ImportError:
        log("archive_pipeline 未找到，无法转换 docx→pdf")
        return False
    except Exception as e:
        log(f"docx→pdf 转换失败: {e}")
        return False


def insert_pdf_pages(
    merger,
    pdf_path: str,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
) -> bool:
    if fitz is None:
        return False
    try:
        with fitz.open(pdf_path) as src:
            if start_page is not None or end_page is not None:
                # PyMuPDF 会对负数/越界页做特殊处理，不能将其当合法源页记账。
                if (
                    type(start_page) is not int or type(end_page) is not int
                    or not 0 <= start_page <= end_page < src.page_count
                ):
                    return False
                merger.insert_pdf(src, from_page=start_page, to_page=end_page)
            else:
                merger.insert_pdf(src)
        return True
    except Exception:
        return False


def _find_cjk_font() -> str:
    """Find an embeddable CJK font so the plain TOC works in every PDF viewer."""
    candidates = [
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        os.path.expandvars(r"%WINDIR%\Fonts\simsun.ttc"),
        os.path.expandvars(r"%WINDIR%\Fonts\msyh.ttc"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def image_to_pdf(image_path: str, pdf_path: str, log=print) -> bool:
    if fitz is None:
        log("PyMuPDF 未安装，无法转换图片")
        return False
    try:
        if not image_path.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff")):
            return False
        doc = fitz.open()
        img_doc = fitz.open(image_path)
        if img_doc.page_count > 0:
            pdfpage = doc.new_page()
            pdfpage.insert_image(pdfpage.rect, filename=image_path)
        img_doc.close()
        doc.save(pdf_path)
        doc.close()
        return os.path.exists(pdf_path)
    except Exception as e:
        log(f"图片转 PDF 失败: {e}")
        return False


def _pdf_page_count(pdf_path: str) -> int:
    if fitz is None or not pdf_path or not os.path.exists(pdf_path):
        return 0
    try:
        doc = fitz.open(pdf_path)
        n = doc.page_count
        doc.close()
        return n
    except Exception:
        return 0


def _source_key(path: str) -> str:
    """同一个源文件的相对/绝对路径及 Windows 大小写使用同一计数键。"""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _insert_unit(
    merger,
    fallback_pdf: str,
    unit,
    inserted_by_source: Dict[str, Counter],
) -> bool:
    pdf_path = getattr(unit, "source_path", "") or fallback_pdf
    if not pdf_path:
        return False
    before_pages = merger.page_count
    if insert_pdf_pages(merger, pdf_path, unit.start_page, unit.end_page):
        if merger.page_count - before_pages != unit.end_page - unit.start_page + 1:
            # 物理插入量不一致时不记成功，后续守恒检查必须阻断保存。
            inserted_by_source.setdefault(_source_key(pdf_path), Counter())[-1] += 1
            return False
        key = _source_key(pdf_path)
        inserted_by_source.setdefault(key, Counter()).update(range(unit.start_page, unit.end_page + 1))
        return True
    return False


def build_catalog_content_pdf(
    case_type: str,
    original_pdf: str,
    doc_spans: List,
    output_pdf: str,
    log=print,
) -> tuple:
    """仅按目录顺序提取原 PDF 材料（无系统模板），用于切分/排版验收。

    Returns:
        (success, page_count, original_pages_included)
    """
    if fitz is None:
        log("PyMuPDF 未安装，无法合并 PDF")
        return False, 0, 0

    try:
        import archive_catalog as ac
    except ImportError:
        return False, 0, 0

    catalog = ac.get_catalog(case_type)
    back_system_seqs = set(ac.get_back_system_seqs(case_type))
    front_system_seqs = {0, 1}

    merger = fitz.open()
    inserted_by_source: Dict[str, Counter] = defaultdict(Counter)
    placed_doc_ids: Set[int] = set()

    for item in catalog:
        seq = item.seq
        if seq in front_system_seqs or seq in back_system_seqs or item.source == "system":
            continue

        matched = [
            u for u in (doc_spans or [])
            if getattr(u, "catalog_seq", None) == seq and u.doc_id not in placed_doc_ids
        ]
        matched.sort(key=lambda u: (u.doc_id, u.start_page))
        for unit in matched:
            if _insert_unit(merger, original_pdf, unit, inserted_by_source):
                placed_doc_ids.add(unit.doc_id)
                log(
                    f"  seq{seq} {item.name}: 页{unit.start_page}-{unit.end_page} "
                    f"({unit.end_page - unit.start_page + 1}页)"
                )

    page_count = merger.page_count
    success = False
    conservation_ok, included, _expected = _check_page_conservation(
        doc_spans, inserted_by_source, original_pdf, log=log
    )
    if page_count > 0 and conservation_ok:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_pdf)) or ".", exist_ok=True)
            merger.save(output_pdf)
            success = True
            log(f"目录材料 PDF: {output_pdf} ({page_count} 页)")
        except Exception as e:
            log(f"保存 PDF 失败: {e}")
    merger.close()

    return success, page_count, included


def _catalog_item_matches_unit(item, unit, manual_doc_types: Dict[str, Optional[str]]) -> bool:
    """目录项逻辑命中：用于 mixed/manual 判定，不代表一定重复插页。"""
    if getattr(unit, "manual_catalog_seq", None) is not None:
        return item.seq == unit.manual_catalog_seq
    doc_type = getattr(unit, "doc_type", None)
    if getattr(unit, "catalog_seq", None) == item.seq:
        return True
    if doc_type and doc_type in (item.doc_types or ()):
        return True
    manual_doc_type = manual_doc_types.get(item.manual_key)
    return bool(manual_doc_type and doc_type == manual_doc_type)


def _logical_matches(item, doc_spans: List, manual_doc_types: Dict[str, Optional[str]]) -> List:
    return [
        unit for unit in (doc_spans or [])
        if _catalog_item_matches_unit(item, unit, manual_doc_types)
    ]


def _check_page_conservation(
    doc_spans: List,
    inserted_by_source: Dict[str, Counter],
    fallback_pdf: str,
    log=print,
    expected_source_paths: Optional[List[str]] = None,
) -> tuple:
    """每个来源的每一页恰好一次，拒绝重页、漏页、越界及无法读取的来源。

    expected_source_paths 可传上传清单，覆盖整份文件未生成任何 Unit 的情况。
    不传时仍检查 doc_spans 和 fallback_pdf 中的全部来源。
    """
    source_paths = {_source_key(path) for path in (expected_source_paths or []) if path}
    if fallback_pdf:
        source_paths.add(_source_key(fallback_pdf))
    for u in doc_spans or []:
        path = getattr(u, "source_path", "") or fallback_pdf
        if path:
            source_paths.add(_source_key(path))

    # 统一调用者提供的路径别名；Counter 保留重复次数，不能退回 set 数量。
    counts_by_source = defaultdict(Counter)
    for path, counts in inserted_by_source.items():
        counts_by_source[_source_key(path)].update(counts)
    source_paths.update(counts_by_source)

    ok = bool(source_paths)
    total_expected = 0
    total_included = 0
    for path in sorted(source_paths):
        expected = _pdf_page_count(path)
        counts = counts_by_source[path]
        wanted = set(range(expected))
        present = {page for page, count in counts.items() if count > 0}
        included = len(wanted & present)
        missing = wanted - present
        unexpected = present - wanted
        duplicates = sum(count - 1 for count in counts.values() if count > 1)
        total_expected += expected
        total_included += included
        if expected <= 0 or missing or unexpected or duplicates:
            ok = False
            log(
                f"       [FAIL] 页守恒: {os.path.basename(path)} "
                f"{included}/{expected} 页，漏页 {len(missing)}，"
                f"重页 {duplicates}，越界页 {len(unexpected)}"
            )
    return ok, total_included, total_expected


def _verify_document_order(catalog, doc_spans, log=print, *, order_mode="catalog") -> List[Dict]:
    """检查文档顺序：catalog_seq单调递增 + 同源内页序正确

    检查两个层次的问题：
    1. catalog_seq单调递增 - 确保最终PDF按标准目录顺序排列
    2. 同源内页序正确 - 确保同一catalog_seq内文书按页码排列
    """
    issues: List[Dict] = []

    # 1. 检查catalog_seq单调递增
    for i in range(len(doc_spans) - 1) if order_mode == "catalog" else ():
        current = doc_spans[i]
        next_doc = doc_spans[i + 1]

        current_seq = getattr(current, "catalog_seq", None)
        next_seq = getattr(next_doc, "catalog_seq", None)

        if current_seq is not None and next_seq is not None:
            if current_seq > next_seq:
                current_type = getattr(current, "doc_type", "unknown")
                next_type = getattr(next_doc, "doc_type", "unknown")
                issues.append({
                    "type": "catalog_seq顺序异常",
                    "seq": f"{current_seq} > {next_seq}",
                    "description": (
                        f"seq{current_seq}({current_type}) 出现在 "
                        f"seq{next_seq}({next_type}) 之前"
                    ),
                })

    # 2. 原有的同源内页序检查
    by_seq_source: Dict[tuple, List] = defaultdict(list)
    for unit in doc_spans or []:
        seq = getattr(unit, "catalog_seq", None)
        if seq is None:
            continue
        src = getattr(unit, "source_path", "") or ""
        by_seq_source[(seq, src)].append(unit)

    for (seq, src), units in by_seq_source.items():
        if len(units) <= 1:
            continue
        # Callers provide the actual physical insertion order; doc_id describes
        # the original analysis order and may differ after catalog sorting.
        ordered = units
        prev_start = ordered[0].start_page
        for unit in ordered[1:]:
            if unit.start_page < prev_start:
                src_name = os.path.basename(src) if src else "原PDF"
                issues.append({
                    "type": "同目录项顺序异常",
                    "seq": seq,
                    "source": src,
                    "description": (
                        f"seq{seq}（{src_name}）内文书页序回退："
                        f"doc_id={unit.doc_id} 起始页{unit.start_page} "
                        f"早于前一份的起始页{prev_start}"
                    ),
                })
                break
            prev_start = unit.start_page

    return issues


def _generate_toc_pdf(
    catalog: List,
    body_starts: Dict[int, int],
    cover_end_idx: int,
    toc_pages: int,
    pagination_mode: str = "legacy",
) -> "fitz.Document":
    """生成卷内目录 PDF（插入封面之后）"""

    def _display_page(body_idx: int) -> int:
        if pagination_mode == "draft":
            return None
        if pagination_mode == "body":
            return body_idx-cover_end_idx+1 if body_idx >= cover_end_idx else None
        if body_idx < cover_end_idx:
            return body_idx + 1
        return body_idx + toc_pages + 1

    toc_self_page = cover_end_idx + 1 if pagination_mode == "legacy" else None
    entries: List[tuple] = [("卷内目录", toc_self_page)]
    for item in catalog:
        body_idx = body_starts.get(item.seq)
        # Keep missing material rows visible; a blank page cell is not a false
        # claim that material exists, and matches the standard archive directory.
        entries.append((item.name, _display_page(body_idx) if body_idx is not None else None))

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    font_path = _find_cjk_font()
    font_name = "toc-cjk" if font_path else "china-s"
    if font_path:
        page.insert_font(fontname=font_name, fontfile=font_path)
    y = 72
    page.insert_text((72, y), "卷内目录", fontname=font_name, fontsize=18)
    y += 36
    page.insert_text((72, y), "名称", fontname=font_name, fontsize=11)
    page.insert_text((460, y), "页码", fontname=font_name, fontsize=11)
    y += 24

    line_height = 16
    max_y = 800
    for idx, (name, page_num) in enumerate(entries, start=1):
        if y > max_y:
            # 超出单页：缩小行距继续在同一页绘制，不再新增页
            line_height = max(12, line_height - 2)
            y = 72
        page.insert_text((72, y), f"{idx}. {name[:38]}", fontname=font_name, fontsize=9)
        if page_num is not None:
            page.insert_text((460, y), str(page_num), fontname=font_name, fontsize=9)
        y += line_height

    return doc


def _build_toc_doc(catalog, body_starts, cover_end_idx, case_type, work_dir, log=print, *, prefer_word=True, original_required=False, pagination_mode="legacy"):
    """优先 Word 卷内目录模板（仅填页码），失败则回退纯文本目录"""
    if original_required:
        from original_catalog import original_catalog_pdf
        result = original_catalog_pdf(case_type, body_starts, cover_end_idx, pagination_mode=pagination_mode)
        log("  [卷内目录] 使用律所原目录，仅填写原表页码格")
        return result, 1
    if not prefer_word or pagination_mode != "legacy":
        log("  [卷内目录] 使用本地 PDF 目录，不调用 Word")
        return _build_toc_doc_plain(catalog, body_starts, cover_end_idx, pagination_mode=pagination_mode)
    toc_pages = 1
    toc_doc = None

    try:
        from catalog_toc import catalog_toc_to_pdf, compute_display_pages
    except ImportError:
        catalog_toc_to_pdf = None

    if catalog_toc_to_pdf and case_type:
        os.makedirs(work_dir, exist_ok=True)
        for _ in range(5):
            display = compute_display_pages(body_starts, cover_end_idx, toc_pages)
            toc_self = cover_end_idx + 1
            pdf_path = os.path.join(work_dir, "_catalog_toc_tmp.pdf")
            if toc_doc:
                toc_doc.close()
                toc_doc = None
            try:
                made = catalog_toc_to_pdf(
                    case_type,
                    display,
                    pdf_path,
                    work_dir,
                    toc_self_page=toc_self,
                    log=log,
                )
            except Exception as exc:
                log(f"  [卷内目录] Word 模板不可用: {exc}")
                made = False
            if made and fitz and os.path.isfile(pdf_path):
                toc_doc = fitz.open(pdf_path)
                actual = toc_doc.page_count
                if actual == toc_pages:
                    filled = len(display)
                    log(f"  [卷内目录] Word 模板 {filled} 项有页码（缺失项留空）")
                    return toc_doc, toc_pages
                toc_pages = actual
            else:
                break

    if toc_doc:
        toc_doc.close()
    log("  [卷内目录] Word 模板不可用，回退纯文本目录")
    return _build_toc_doc_plain(catalog, body_starts, cover_end_idx)


def _build_toc_doc_plain(catalog, body_starts, cover_end_idx, *, pagination_mode="legacy"):
    """迭代生成纯文本目录（回退方案）"""
    toc_pages = 1
    toc_doc = None
    for _ in range(5):
        if toc_doc:
            toc_doc.close()
        toc_doc = _generate_toc_pdf(catalog, body_starts, cover_end_idx, toc_pages, pagination_mode)
        actual = toc_doc.page_count
        if actual == toc_pages:
            break
        toc_pages = actual
    return toc_doc, toc_pages


def _add_archive_navigation(document, catalog, body_starts, cover_end_idx, toc_pages, log=print, *, original_case_type=None):
    """Create navigation only after final page offsets are known."""
    entries = [("卷内目录", cover_end_idx)]
    for item in catalog:
        body_index = body_starts.get(item.seq)
        if body_index is None:
            continue
        target = body_index if body_index < cover_end_idx else body_index + toc_pages
        if 0 <= target < document.page_count:
            entries.append((item.name, target))
    document.set_toc([[1, title, target + 1] for title, target in sorted(entries, key=lambda item: item[1])])
    links = 0
    if original_case_type:
        from original_catalog import navigation_rows
        page = document[cover_end_idx]
        for cell, target in navigation_rows(original_case_type, body_starts, cover_end_idx):
            page.insert_link({"kind": fitz.LINK_GOTO, "from": cell, "page": target, "to": fitz.Point(0, 0)})
            links += 1
        log(f"  [PDF 导航] {len(entries)} 个书签，{links} 个原目录页码链接")
        return
    for page_index in range(cover_end_idx, cover_end_idx + toc_pages):
        page = document[page_index]
        used_rectangles = set()
        for title, target in entries:
            # Plain PDF directories print the first 38 characters; Word fallback
            # directories can wrap the same title over more than one line.
            for rectangle in page.search_for(title[:38]):
                bounds = (round(rectangle.y0, 2), round(rectangle.y1, 2))
                if bounds in used_rectangles:
                    continue
                used_rectangles.add(bounds)
                page.insert_link({
                    "kind": fitz.LINK_GOTO,
                    "from": fitz.Rect(60, rectangle.y0, min(520, page.rect.width - 20), rectangle.y1),
                    "page": target,
                    "to": fitz.Point(0, 0),
                })
                links += 1
    log(f"  [PDF 导航] {len(entries)} 个书签，{links} 条目录链接")


def _insert_system_template(
    merger,
    item,
    generated_templates: Dict[str, str],
    template_pdfs: Dict[str, bool],
    log=print,
) -> bool:
    template_name = item.templates[0]
    if template_name not in generated_templates:
        return False
    docx_path = generated_templates[template_name]
    # template_pdfs: {docx_path -> 临时 PDF 路径}（位于 scratch 目录，转换成功才有值）
    tmp_pdf = template_pdfs.get(docx_path)
    if not tmp_pdf or not os.path.isfile(tmp_pdf):
        log(f"  [WARN] 系统模板 PDF 转换失败: {template_name}")
        return False

    try:
        from output_options import TEMPLATE_PAGE_BUDGET

        # Browser-rendered forms may grow when long editable cells wrap. The
        # historical page budget only applies to fixed DOCX templates.
        max_pages = None if docx_path.lower().endswith(".pdf") else TEMPLATE_PAGE_BUDGET.get(template_name)
    except ImportError:
        max_pages = None

    if max_pages and fitz is not None:
        try:
            src = fitz.open(tmp_pdf)
            actual = src.page_count
            src.close()
            if actual > max_pages:
                log(
                    f"  [WARN] {template_name} PDF {actual} 页，按预算仅插入前 {max_pages} 页"
                )
                if insert_pdf_pages(merger, tmp_pdf, 0, max_pages - 1):
                    log(f"  [系统模板] seq{item.seq}: {item.name} → {template_name}")
                    return True
                return False
        except Exception:
            pass

    if insert_pdf_pages(merger, tmp_pdf):
        log(f"  [系统模板] seq{item.seq}: {item.name} → {template_name}")
        return True
    log(f"  [WARN] 系统模板 PDF 插入失败: {template_name}")
    return False


def _insert_content_for_item(
    item,
    seq: int,
    merger,
    original_pdf: Optional[str],
    doc_spans: List,
    supplements: Dict[int, List[str]],
    skipped: List[int],
    placed_doc_ids: Set[int],
    inserted_by_source: Dict[str, Counter],
    sources: Dict[int, str],
    missing: List[Dict],
    manual_doc_types: Dict[str, Optional[str]],
    log=print,
    doc_body_idx: Optional[Dict[int, int]] = None,
    logical_pending: Optional[Dict[int, List[int]]] = None,
    scratch_dir: Optional[str] = None,
) -> bool:
    """插入非系统目录项（PDF 页段 / 用户补充）"""
    if doc_body_idx is None:
        doc_body_idx = {}
    is_skipped = seq in skipped
    if is_skipped:
        log("       → 已跳过（不占位；已识别文书仍插入）")

    added = False
    source_desc = ""

    if doc_spans:
        matched = [
            u for u in doc_spans
            if getattr(u, "catalog_seq", None) == seq and u.doc_id not in placed_doc_ids
        ]
        matched.sort(key=lambda u: (u.doc_id, u.start_page))
        for unit in matched:
            body_idx_before = merger.page_count
            if _insert_unit(merger, original_pdf or "", unit, inserted_by_source):
                placed_doc_ids.add(unit.doc_id)
                doc_body_idx[unit.doc_id] = body_idx_before
                added = True
                src_name = os.path.basename(getattr(unit, "source_path", "") or original_pdf or "")
                part = (
                    f"{src_name}: {unit.doc_type} "
                    f"(页{unit.start_page}-{unit.end_page})"
                )
                source_desc = part if not source_desc else source_desc + "; " + part
        if added:
            log(f"       → {source_desc}")

    if not added and not is_skipped and seq in supplements and supplements[seq]:
        # 插入该 seq 下的全部补充文件（支持多文件补充）
        supp_descs = []
        for supp_file in supplements[seq]:
            if not os.path.exists(supp_file):
                continue
            if supp_file.lower().endswith(".pdf"):
                if insert_pdf_pages(merger, supp_file):
                    added = True
                    supp_descs.append(os.path.basename(supp_file))
            else:
                tmp_dir = scratch_dir or os.path.dirname(os.path.abspath(supp_file))
                tmp_pdf = os.path.join(
                    tmp_dir, os.path.basename(supp_file) + ".tmp.pdf"
                )
                if image_to_pdf(supp_file, tmp_pdf, log):
                    if insert_pdf_pages(merger, tmp_pdf):
                        added = True
                        supp_descs.append(f"{os.path.basename(supp_file)}(图片)")
                        try:
                            os.remove(tmp_pdf)
                        except OSError:
                            pass
        if supp_descs:
            source_desc = "用户补充: " + ", ".join(supp_descs)

    if not added:
        logical_matched = _logical_matches(item, doc_spans, manual_doc_types)
        if logical_matched and not is_skipped:
            source_desc = "已识别（同一源页已在其他目录项插入，未重复插页）"
            sources[seq] = source_desc
            # 记录该 seq 逻辑命中的文书，待全部插入完成后回填卷内目录页码，
            # 指向这些页实际所在的位置（修复"已识别但目录无页码"）
            if logical_pending is not None:
                logical_pending[seq] = [u.doc_id for u in logical_matched]
            log(f"       → {source_desc}")
        else:
            status = "skipped" if is_skipped else "missing"
            missing.append({"seq": seq, "name": item.name, "status": status})
            if not is_skipped:
                log("       → 缺失")
    else:
        sources[seq] = source_desc

    return added


def build_full_archive(
    case_type: str,
    original_pdf: Optional[str],
    generated_templates: Dict[str, str],
    doc_spans: List,
    supplements: Dict[int, List[str]],
    skipped: List[int],
    output_pdf: str,
    docx_to_pdf_func=None,
    log=print,
    order_mode: str = "catalog",
    expected_source_paths: Optional[List[str]] = None,
    use_word_catalog: Optional[bool] = None,
    use_original_catalog: bool = False,
    pagination_mode: str = "legacy",
) -> ArchiveResult:
    if pagination_mode not in ("legacy", "draft", "body"):
        raise ValueError("未知归档页码模式")
    try:
        import archive_catalog as ac
    except ImportError:
        return ArchiveResult(output_pdf, success=False, missing=[])

    if fitz is None:
        log("PyMuPDF 未安装，无法合并 PDF")
        return ArchiveResult(output_pdf, success=False, missing=[])

    if docx_to_pdf_func is None:
        docx_to_pdf_func = docx_to_pdf

    catalog_full = ac.get_catalog(case_type)
    found_from_spans = {
        getattr(u, "catalog_seq", None)
        for u in (doc_spans or [])
        if getattr(u, "catalog_seq", None) is not None
    }
    catalog = ac.get_effective_catalog(case_type, found_from_spans)
    catalog_toc = ac.get_effective_catalog(case_type, found_from_spans, for_toc=True)
    manual_doc_types = getattr(ac, "MANUAL_KEY_DOC_TYPES", {})
    back_system_seqs = set(ac.get_back_system_seqs(case_type))
    front_system_seqs = {0, 1}

    body = fitz.open()
    sources = {}
    missing = []
    inserted_by_source: Dict[str, Counter] = defaultdict(Counter)
    placed_doc_ids: Set[int] = set()
    body_starts: Dict[int, int] = {}
    doc_body_idx: Dict[int, int] = {}  # doc_id -> 在 body 中的起始页索引
    logical_pending: Dict[int, List[int]] = {}  # seq -> 逻辑命中的 doc_id（待回填页码）

    # 所有中间产物（docx→pdf 临时件、卷内目录临时件、图片转 PDF）统一放入
    # 独立的 scratch 目录，最终只在 output_pdf 目录留下成品 PDF，结束后清理。
    scratch = tempfile.mkdtemp(prefix="archive_scratch_")

    template_pdfs = {}  # {系统表源路径 -> 可直接插入的 PDF 路径}
    convert_pairs = []
    for item in catalog_full:
        if item.source != "system" or not item.templates:
            continue
        template_name = item.templates[0]
        if template_name in generated_templates:
            source_path = generated_templates[template_name]
            if source_path.lower().endswith(".pdf") and os.path.isfile(source_path):
                template_pdfs[source_path] = source_path
            else:
                tmp_pdf = os.path.join(scratch, f"{template_name}_tmp.pdf")
                convert_pairs.append((source_path, tmp_pdf))

    if convert_pairs:
        log(f"批量转换 {len(convert_pairs)} 份系统模板 docx→pdf…")
        ok_map = {}
        try:
            from archive_pipeline import _word_convert_pairs
            ok_map = _word_convert_pairs(convert_pairs, log=log)
        except ImportError:
            for docx_path, tmp_pdf in convert_pairs:
                ok_map[docx_path] = docx_to_pdf_func(docx_path, tmp_pdf, log)
        for docx_path, tmp_pdf in convert_pairs:
            if ok_map.get(docx_path):
                template_pdfs[docx_path] = tmp_pdf

    catalog_by_seq = {item.seq: item for item in catalog_full}

    def _mark_section_start(seq: int, before_pages: int):
        if body.page_count > before_pages:
            body_starts[seq] = before_pages

    def _insert_preserved_form(item):
        from source_form_policy import source_units_for_item, QUALITY_COMPONENTS
        originals=source_units_for_item(item,doc_spans)
        if not originals:return False
        before=body.page_count
        quality=item.templates[0]=='质量监督卡'
        present={u.doc_type for u in originals}
        def insert_missing_quality_component():
            start=body.page_count
            if not _insert_system_template(body,item,generated_templates,template_pdfs,log=log) or body.page_count-start!=1:
                raise ValueError('缺失质量表组件未独立生成，不能重复插入组合模板')
        if quality:
            originals=sorted(originals,key=lambda u:(QUALITY_COMPONENTS.index(u.doc_type),u.doc_id))
            if 'quality_card' not in present:insert_missing_quality_component()
        for unit in originals:
            start=body.page_count
            if unit.doc_id in placed_doc_ids or not _insert_unit(body,original_pdf or '',unit,inserted_by_source):
                raise ValueError('原始表单重复或插入失败')
            placed_doc_ids.add(unit.doc_id);doc_body_idx[unit.doc_id]=start
        if quality and 'client_notice' not in present:insert_missing_quality_component()
        _mark_section_start(item.seq,before)
        sources[item.seq]='原始表单（保留原文，不代表已审批、签署或送达）'
        return True

    # 阶段 1：封面（seq0）
    cover_item = catalog_by_seq.get(0)
    if cover_item:
        log(f"  目录 0: {cover_item.name}")
        before = body.page_count
        if _insert_system_template(body, cover_item, generated_templates, template_pdfs, log=log):
            _mark_section_start(0, before)

    cover_end_idx = body.page_count

    # 阶段 2：立案审批表（seq1）
    filing_item = catalog_by_seq.get(1)
    if filing_item:
        log(f"  目录 1: {filing_item.name}")
        before = body.page_count
        if not _insert_preserved_form(filing_item):
            if _insert_system_template(body, filing_item, generated_templates, template_pdfs, log=log):
                _mark_section_start(1, before)

    # 阶段 3：原 PDF 材料
    # 修复：不再硬编码覆盖order_mode参数
    if order_mode not in ("catalog", "original"):
        log(f"       [WARN] 无效的order_mode({order_mode})，使用默认catalog模式")
        order_mode = "catalog"

    log(f"       [INFO] 使用 {order_mode} 模式进行文书排序")

    body_seq_set = {
        it.seq for it in catalog
        if it.seq not in front_system_seqs
        and it.seq not in back_system_seqs
        and it.source != "system"
    }

    # 统一处理逻辑：按order_mode选择排序方式
    material = [
        u for u in (doc_spans or [])
        if getattr(u, "catalog_seq", None) in body_seq_set
    ]

    if order_mode == "original" or case_type == "consultation":
        # 原始顺序模式：按源PDF页序插入
        log("  [原始顺序模式] 正文按源PDF页序插入")
        material.sort(key=lambda u: (u.doc_id, u.start_page))
    else:
        # 标准目录模式：按catalog_seq强制排序
        log("  [标准目录模式] 正文按catalog_seq顺序重新排序")
        # 按catalog_seq强制排序，同seq内按原始页码排序
        material.sort(key=lambda u: (u.catalog_seq if u.catalog_seq is not None else 9999, u.start_page))
        log(f"       [排序] 已按catalog_seq重新排序{len(material)}个文书")

    # 详细调试输出：显示每个文书的排序依据
    for i, unit in enumerate(material):
        log(f"       [文书{i+1}] catalog_seq={unit.catalog_seq}, doc_type={unit.doc_type}, pages={unit.start_page}-{unit.end_page}")

    # 统一插入逻辑：按排序后的顺序插入
    for unit in material:
        seq = unit.catalog_seq
        if unit.doc_id in placed_doc_ids:
            log(f"       [跳过] doc_id={unit.doc_id} 已插入，跳过重复")
            continue

        before = body.page_count

        # 注意：_insert_unit 从「源 PDF」按 unit.start_page/end_page 读取页面，
        # 这些是源 PDF 内的页索引，与输出 body 中已插入的系统模板页数无关。
        # 历史上曾错误地给源页索引加上 cover_end_idx 偏移，导致读到越界/错误页，
        # 源 PDF 页守恒直接归零（0/80）。此处必须直接使用原始 unit。
        added = _insert_unit(body, original_pdf or "", unit, inserted_by_source)

        if added:
            placed_doc_ids.add(unit.doc_id)
            doc_body_idx[unit.doc_id] = before
            if body.page_count > before and seq not in body_starts:
                _mark_section_start(seq, before)

            src_name = os.path.basename(getattr(unit, "source_path", "") or original_pdf or "")
            part = f"{src_name}: {unit.doc_type} (页{unit.start_page}-{unit.end_page})"
            sources[seq] = part if seq not in sources else sources[seq] + "; " + part
            log(f"  目录 {seq}: {part}")
        else:
            log(f"       [WARN] 插入失败: doc_type={unit.doc_type}, pages={unit.start_page}-{unit.end_page}")

    # 处理缺失的catalog项：补充上传或判定为缺失
    for item in catalog:
        seq = item.seq
        if seq in front_system_seqs or seq in back_system_seqs or item.source == "system":
            continue
        if seq in sources:
            continue  # 已有正文

        log(f"  目录 {seq}: {item.name} (缺失)")
        before = body.page_count
        added = _insert_content_for_item(
            item, seq, body, original_pdf, doc_spans, supplements, skipped,
            placed_doc_ids, inserted_by_source, sources, missing, manual_doc_types, log=log,
            doc_body_idx=doc_body_idx, logical_pending=logical_pending, scratch_dir=scratch,
        )
        if body.page_count > before:
            _mark_section_start(seq, before)
        elif not added:
            log(f"       → 目录页码留空（未插入内容）")
            # _insert_content_for_item already records missing/skipped once.

    # 阶段 4：卷末系统模板
    for seq in ac.get_back_system_seqs(case_type):
        item = catalog_by_seq.get(seq)
        if not item:
            continue
        log(f"  目录 {seq}: {item.name}")
        before = body.page_count
        if not _insert_preserved_form(item) and _insert_system_template(body, item, generated_templates, template_pdfs, log=log):
            _mark_section_start(seq, before)

    # 回填逻辑命中项的卷内目录页码：指向其页面实际所在位置
    for seq, doc_ids in logical_pending.items():
        if seq in body_starts:
            continue
        idxs = [doc_body_idx[d] for d in doc_ids if d in doc_body_idx]
        if idxs:
            body_starts[seq] = min(idxs)
            log(f"       → seq{seq} 目录页码指向已插入位置 (body_idx {min(idxs)})")

    # 生成卷内目录并拼装：封面 + 目录 + 其余（卷内目录中间件放 scratch，避免污染输出目录）
    if use_word_catalog is None:
        use_word_catalog = not (generated_templates and all(path.lower().endswith(".pdf") for path in generated_templates.values()))
    toc_doc, toc_page_count = _build_toc_doc(
        catalog_toc, body_starts, cover_end_idx, case_type, scratch, log=log,
        prefer_word=use_word_catalog,
        original_required=use_original_catalog,
        pagination_mode=pagination_mode,
    )

    merger = fitz.open()
    if cover_end_idx > 0:
        merger.insert_pdf(body, from_page=0, to_page=cover_end_idx - 1)
    merger.insert_pdf(toc_doc)
    if body.page_count > cover_end_idx:
        merger.insert_pdf(body, from_page=cover_end_idx, to_page=body.page_count - 1)
    toc_doc.close()
    body.close()
    _add_archive_navigation(merger, catalog_toc, body_starts, cover_end_idx, toc_page_count, log=log,
                            original_case_type=case_type if use_original_catalog else None)

    log(f"  [卷内目录] 已插入封面之后（{toc_page_count} 页）")

    conservation_ok, orig_included, orig_expected = _check_page_conservation(
        doc_spans, inserted_by_source, original_pdf or "", log=log,
        expected_source_paths=expected_source_paths,
    )

    # 防御性守恒：路径 A 单卷若源 PDF 有内容却 doc_spans 为空（切分崩溃/全失败），
    # _check_page_conservation 会得到 0/0 而“真空通过”，造成 0 正文页却 success=True 的
    # 假成功。此处显式判失败，避免再次出现历史回归被静默吞掉。
    if original_pdf and not (doc_spans or []):
        src_pages = _pdf_page_count(original_pdf)
        if src_pages and src_pages > 0:
            conservation_ok = False
            orig_expected = max(orig_expected, src_pages)
            log(
                f"       [FAIL] doc_spans 为空但源 PDF 有 {src_pages} 页："
                f"文书切分失败导致正文全部丢失，归档判为失败"
            )

    inserted_units = sorted(
        (unit for unit in doc_spans if unit.doc_id in doc_body_idx),
        key=lambda unit: doc_body_idx[unit.doc_id],
    )
    order_issues = _verify_document_order(catalog, inserted_units, log=log, order_mode=order_mode)
    if order_issues:
        log("       [WARN] 文书顺序验证:")
        for issue in order_issues:
            log(f"         - {issue['type']}: {issue['description']}")

    success = False
    page_count = 0

    if merger.page_count > 0:
        if not conservation_ok:
            log("       [FAIL] 源 PDF 页守恒未满足，归档标记为失败")
        else:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(output_pdf)) or ".", exist_ok=True)
                from archive_pagination import numbered_volume
                if pagination_mode == "draft":
                    numbered = fitz.open(stream=merger.tobytes(), filetype="pdf")
                    numbered.set_page_labels([{"startpage":0,"prefix":"","style":""}])
                else:
                    numbered = numbered_volume(merger, start_page=cover_end_idx+toc_page_count, style="body") if pagination_mode == "body" else numbered_volume(merger)
                try:
                    numbered.save(output_pdf, garbage=3, deflate=True)
                finally:
                    numbered.close()
                page_count = merger.page_count
                success = True
                log(f"归档 PDF 已生成: {output_pdf} ({page_count} 页)")
                log(f"源 PDF 已包含 {orig_included}/{orig_expected} 页")
            except Exception as e:
                log(f"保存 PDF 失败: {e}")
    else:
        log("没有可合并的页面")

    merger.close()

    # 清理所有中间产物（docx→pdf 临时件、卷内目录临时件、图片临时件）
    shutil.rmtree(scratch, ignore_errors=True)

    return ArchiveResult(
        output_pdf=output_pdf,
        success=success,
        missing=missing,
        page_count=page_count,
        sources=sources,
        original_pages_included=orig_included,
        order_issues=order_issues,
        pagination={"mode":pagination_mode, "body_start":cover_end_idx+toc_page_count},
    )
