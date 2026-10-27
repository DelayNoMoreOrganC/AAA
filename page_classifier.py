#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""J-2 页级目录槽分类 — layout + 文本 + 可选视觉/LLM 复核"""

from __future__ import annotations

import base64
import io
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import archive_catalog as ac
import document_segmenter as ds

try:
    import fitz
except ImportError:
    fitz = None

# 低于此阈值视为需复核（GUI 可提示）
LOW_CONFIDENCE_THRESHOLD = 0.8

# 仅当文书类型锚点出现在「标题区」（页面顶部）时才视为新文书起点，
# 避免正文中部偶现的关键词（如合同条款里提到的"授权委托书"）误触发槽位切换。
# 【优化】对execution类型使用更大的搜索范围
DEFAULT_TITLE_ZONE_CHARS = 90
EXECUTION_TITLE_ZONE_CHARS = 300  # 执行类文书扩大到300字符
CONTRACT_TITLE_ZONE_CHARS = 200  # 合同类文书扩大到200字符

def get_title_zone_chars(doc_type_hint: str = None) -> int:
    """根据文书类型返回合适的标题区大小"""
    if doc_type_hint == "execution":
        return EXECUTION_TITLE_ZONE_CHARS
    elif doc_type_hint == "contract":
        return CONTRACT_TITLE_ZONE_CHARS
    return DEFAULT_TITLE_ZONE_CHARS

TITLE_ZONE_CHARS = DEFAULT_TITLE_ZONE_CHARS  # 保持向后兼容

_DOC_TYPE_LABELS = {v: k for k, v in ds.DOC_TYPE_LABELS.items()}


@dataclass
class PageClassifyResult:
    catalog_seq: int
    doc_type: str
    confidence: float
    method: str  # layout | anchor | inherit | llm | vision


def _catalog_seq_for_doc_type(case_type: str, doc_type: str) -> Optional[int]:
    if doc_type in (ds.DOC_TYPE_OTHER, ds.DOC_TYPE_UNKNOWN):
        return None
    item = ac.catalog_item_for_doc_type(case_type, doc_type)
    if item:
        return item.seq
    for manual_key, mdt in ac.MANUAL_KEY_DOC_TYPES.items():
        if mdt == doc_type:
            mk = ac.catalog_item_for_manual_key(case_type, manual_key)
            if mk:
                return mk.seq
    return None


def layout_headings_by_page(layout_blocks: List[dict]) -> Dict[int, List[str]]:
    by_page: Dict[int, List[str]] = {}
    for block in layout_blocks or []:
        text = (block.get("text") or "").strip()
        if not text:
            continue
        is_heading = block.get("text_level") is not None
        btype = (block.get("type") or "").lower()
        if not is_heading and btype not in ("title", "text"):
            continue
        if is_heading or btype == "title":
            page_idx = int(block.get("page_idx", 0))
            by_page.setdefault(page_idx, []).append(text)
    return by_page


def _classify_text_snippet(text: str, case_type: str) -> Tuple[Optional[int], str, float, str]:
    from pdf_doc_locator import _classify_page_prefix, _classify_page_text

    doc_type, anchor = _classify_page_text(text or "")
    if doc_type == ds.DOC_TYPE_OTHER:
        return None, doc_type, 0.0, "none"
    seq = _catalog_seq_for_doc_type(case_type, doc_type)
    if seq is None:
        return None, doc_type, 0.0, "none"
    conf = 0.65
    method = "anchor"
    if anchor and text and anchor in text[:400]:
        conf = 0.72
    return seq, doc_type, conf, method


def classify_page_with_layout(
    page_idx: int,
    page_text: str,
    case_type: str,
    layout_blocks: Optional[List[dict]] = None,
) -> PageClassifyResult:
    """J-1：layout 标题优先，锚点需出现在页面上部才切换槽位"""
    from pdf_doc_locator import _classify_page_prefix, _classify_page_text

    evidence = ac.catalog_item_for_manual_key(case_type, "evidence")
    default_seq = evidence.seq if evidence else 7
    evidence_seq = default_seq

    headings = layout_headings_by_page(layout_blocks or {}).get(page_idx, [])
    heading_seq = None
    heading_type = ds.DOC_TYPE_OTHER
    for h in headings:
        seq, dt, _, _ = _classify_text_snippet(h, case_type)
        if seq is not None:
            heading_seq, heading_type = seq, dt
            break

    text = page_text or ""
    # 【优化】使用动态标题区大小，提高execution和contract识别率
    title_zone_chars = get_title_zone_chars()
    # 首先尝试用小范围检测类型，再决定是否扩大范围
    title_zone = text[:title_zone_chars]
    body_seq, body_type, body_conf, _ = _classify_text_snippet(title_zone, case_type)
    prefix_text = title_zone

    # 如果在小范围内没有检测到锚点，但对execution或contract类型扩大搜索
    if body_seq is None and len(text) > DEFAULT_TITLE_ZONE_CHARS:
        extended_title_zone = text[:EXECUTION_TITLE_ZONE_CHARS]
        extended_seq, extended_type, extended_conf, _ = _classify_text_snippet(extended_title_zone, case_type)
        if extended_seq is not None and extended_type in (ds.DOC_TYPE_EXECUTION, ds.DOC_TYPE_CONTRACT):
            body_seq, body_type, body_conf = extended_seq, extended_type, extended_conf
            title_zone = extended_title_zone
            prefix_text = extended_title_zone

    def _stage_fix(seq, dt):
        """阶段细分：案号为「执保/财保」等保全字号的执行裁定/裁定，实为保全(seq8)。
        优先级高于 layout 标题——MinerU 标题块常只截到「执行裁定书」缺案号，会误判执行。"""
        if dt in (ds.DOC_TYPE_EXECUTION, ds.DOC_TYPE_RULING):
            from pdf_doc_locator import _PRESERVATION_CASE_RE, _ENFORCE_MARK_RE
            zone = text[:EXECUTION_TITLE_ZONE_CHARS]
            if _PRESERVATION_CASE_RE.search(zone) and not _ENFORCE_MARK_RE.search(zone):
                pseq = _catalog_seq_for_doc_type(case_type, ds.DOC_TYPE_PRESERVATION)
                if pseq is not None:
                    return pseq, ds.DOC_TYPE_PRESERVATION
        return seq, dt

    if body_seq is not None:
        doc_type, anchor = _classify_page_prefix(text, max_chars=TITLE_ZONE_CHARS)
        if anchor and anchor in prefix_text:
            if heading_seq is not None and heading_seq != body_seq:
                hs, ht = _stage_fix(heading_seq, heading_type)
                return PageClassifyResult(hs, ht, 0.88, "layout")
            conf = 0.90 if heading_seq == body_seq else 0.78
            bs, bt = _stage_fix(body_seq, body_type)
            return PageClassifyResult(bs, bt, conf, "anchor")

    # layout 标题（MinerU title 块）跨位置可靠，作为新文书起点的权威信号
    if heading_seq is not None:
        hs, ht = _stage_fix(heading_seq, heading_type)
        return PageClassifyResult(hs, ht, 0.88, "layout")

    if body_seq is not None and len(text.strip()) < 350:
        bs, bt = _stage_fix(body_seq, body_type)
        return PageClassifyResult(bs, bt, 0.66, "anchor")

    if body_seq is not None:
        return PageClassifyResult(evidence_seq, ds.DOC_TYPE_OTHER, 0.45, "weak_anchor")

    return PageClassifyResult(default_seq, ds.DOC_TYPE_OTHER, 0.4, "inherit")


def _render_page_png(pdf_path: str, page_idx: int, dpi: int = 120) -> Optional[bytes]:
    if fitz is None or not pdf_path or not os.path.isfile(pdf_path):
        return None
    try:
        doc = fitz.open(pdf_path)
        if page_idx < 0 or page_idx >= doc.page_count:
            doc.close()
            return None
        page = doc[page_idx]
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        png = pix.tobytes("png")
        doc.close()
        return png
    except Exception:
        return None


def _llm_classify_page(
    page_text: str,
    case_type: str,
    config: dict,
    log=print,
) -> Optional[PageClassifyResult]:
    """DeepSeek 文本分类（边界页复核）"""
    try:
        from archive_pipeline import _deepseek_chat
        from settings import get_deepseek_config
    except ImportError:
        return None

    ds_cfg = get_deepseek_config()
    if not (ds_cfg.get("api_key") or "").strip():
        return None

    catalog = ac.get_catalog(case_type)
    lines = [f"seq{item.seq}: {item.name}" for item in catalog if item.source != "system"]
    prompt = (
        "你是法律卷宗归档助手。根据下列单页 OCR 文字，判断该页属于哪一项卷内目录（只输出一行 JSON）。\n"
        "格式: {\"seq\": 数字, \"doc_type\": \"英文类型码\", \"confidence\": 0.0-1.0}\n"
        "doc_type 可选: complaint, contract, poa, evidence, summons, court_record, "
        "judgment, ruling, execution, mediation, invoice, other\n\n"
        "目录项:\n" + "\n".join(lines) + "\n\n"
        "OCR 文字:\n" + (page_text or "")[:2500]
    )
    try:
        raw = _deepseek_chat(prompt, "只输出 JSON，不要解释。")
        text = raw if isinstance(raw, str) else str(raw)
        m = re.search(r"\{[^{}]+\}", text)
        if not m:
            return None
        import json
        import re as _re
        text = raw if isinstance(raw, str) else str(raw)
        m = _re.search(r"\{[^{}]+\}", text)
        if not m:
            return None
        data = json.loads(m.group())
        seq = int(data.get("seq", -1))
        doc_type = str(data.get("doc_type") or "other")
        conf = float(data.get("confidence") or 0.7)
        if seq < 0:
            item = ac.catalog_item_for_doc_type(case_type, doc_type)
            seq = item.seq if item else None
        if seq is None:
            return None
        return PageClassifyResult(seq, doc_type, min(conf, 0.92), "llm")
    except Exception as e:
        log(f"       [WARN] LLM 页分类失败: {e}")
        return None


def refine_low_confidence_pages(
    page_seqs: List[int],
    confidences: List[float],
    page_texts: List[str],
    case_type: str,
    pdf_path: Optional[str],
    config: dict,
    log=print,
) -> Tuple[List[int], List[float], List[dict]]:
    """J-2：对低置信度页与槽位边界页做 LLM/视觉复核"""
    low_items: List[dict] = []
    n = len(page_seqs)
    if n == 0:
        return page_seqs, confidences, low_items

    boundary = {0}
    for i in range(1, n):
        if page_seqs[i] != page_seqs[i - 1]:
            boundary.add(i)
            boundary.add(i - 1)

    for idx in sorted(boundary):
        if confidences[idx] >= LOW_CONFIDENCE_THRESHOLD:
            continue
        refined = _llm_classify_page(page_texts[idx], case_type, config, log=log)
        if refined and refined.confidence > confidences[idx]:
            old_seq = page_seqs[idx]
            # 仅当 LLM 置信度足够且与邻页差异相关时才改 seq
            if refined.confidence >= 0.7:
                page_seqs[idx] = refined.catalog_seq
                confidences[idx] = refined.confidence
                log(
                    f"       J-2 复核 页{idx}: seq{old_seq}→seq{refined.catalog_seq} "
                    f"({refined.method}, conf={refined.confidence:.2f})"
                )
        if confidences[idx] < LOW_CONFIDENCE_THRESHOLD:
            low_items.append({
                "page": idx,
                "seq": page_seqs[idx],
                "confidence": confidences[idx],
                "preview": (page_texts[idx] or "")[:80],
            })

    return page_seqs, confidences, low_items


def collect_low_confidence_units(units, threshold: float = LOW_CONFIDENCE_THRESHOLD) -> List[dict]:
    out = []
    for u in units or []:
        conf = getattr(u, "confidence", 1.0)
        if conf is None:
            conf = 1.0
        if conf < threshold:
            out.append({
                "doc_id": u.doc_id,
                "catalog_seq": u.catalog_seq,
                "pages": f"{u.start_page}-{u.end_page}",
                "confidence": conf,
                "title": getattr(u, "title", ""),
            })
    return out
