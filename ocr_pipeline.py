#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WF1 统一 OCR 摄入 — 一次重型 OCR，扇出 full_text + page_texts"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from archive_ocr import extract_pdf_text, extract_pdf_text_direct, get_pdf_page_count
from settings import get_ocr_engine


@dataclass
class OcrDocumentResult:
    pdf_path: str
    full_text: str = ""
    page_texts: List[str] = field(default_factory=list)
    source: str = ""  # text_layer | mineru | baidu | hybrid
    ocr_engine_calls: int = 0  # 重型 OCR（MinerU/Baidu）次数，每 PDF ≤1
    rapidocr_fallback_pages: int = 0  # 空页 RapidOCR 单页回退数（非全卷扫描）
    mineru_output_dir: Optional[str] = None
    layout_blocks: List[dict] = field(default_factory=list)
    local_ocr_pages: int = 0
    warnings: List[str] = field(default_factory=list)


_SKIP_LAYOUT_TYPES = frozenset(
    {"header", "footer", "page_number", "page_footnote", "aside_text"}
)


def _fitz_page_texts(pdf_path: str) -> Tuple[List[str], str]:
    try:
        import fitz
    except ImportError:
        return [], ""

    try:
        doc = fitz.open(pdf_path)
        pages = []
        for i in range(doc.page_count):
            text = doc[i].get_text() or ""
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            pages.append("\n".join(lines))
        doc.close()
        full = "\n\n".join(p for p in pages if p)
        return pages, full
    except Exception:
        return [], ""


def _text_layer_sufficient(page_texts: List[str], min_chars: int = 80) -> bool:
    if not page_texts:
        return False
    total = sum(len(p.strip()) for p in page_texts)
    nonempty = sum(1 for p in page_texts if len(p.strip()) > 10)
    return total >= min_chars and nonempty >= max(1, len(page_texts) // 4)


def find_mineru_sidecar_files(output_dir: str, pdf_path: str) -> Dict[str, str]:
    """在 MinerU 输出目录查找 content_list / middle.json"""
    found: Dict[str, str] = {}
    if not output_dir or not os.path.isdir(output_dir):
        return found
    base = os.path.splitext(os.path.basename(pdf_path))[0].lower()
    for root, _, files in os.walk(output_dir):
        for name in files:
            low = name.lower()
            path = os.path.join(root, name)
            if low.endswith("_content_list.json") or low == "content_list.json":
                found["content_list"] = path
            elif low.endswith("_middle.json") or low == "middle.json":
                found["middle"] = path
            elif low.endswith(".md") and (base in low or "content" in low):
                if "markdown" not in found:
                    found["markdown"] = path
    return found


def page_texts_from_content_list(
    content_list_path: str,
    page_count: int,
) -> List[str]:
    import json

    pages = [""] * page_count
    try:
        with open(content_list_path, encoding="utf-8", errors="replace") as f:
            blocks = json.load(f)
    except Exception:
        return pages

    if not isinstance(blocks, list):
        return pages

    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = (block.get("type") or "").lower()
        if btype in _SKIP_LAYOUT_TYPES:
            continue
        idx = int(block.get("page_idx", 0))
        if idx < 0 or idx >= page_count:
            continue
        chunk = (
            block.get("text")
            or block.get("code_body")
            or block.get("table_body")
            or ""
        )
        if isinstance(chunk, str) and chunk.strip():
            pages[idx] = (pages[idx] + "\n" + chunk.strip()).strip()

    return pages


def layout_blocks_from_content_list(content_list_path: str) -> List[dict]:
    """提取带页码与标题级别的 layout 块，供 WF2 补起点"""
    import json

    try:
        with open(content_list_path, encoding="utf-8", errors="replace") as f:
            blocks = json.load(f)
    except Exception:
        return []
    if not isinstance(blocks, list):
        return []

    out = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = (block.get("type") or "").lower()
        if btype in _SKIP_LAYOUT_TYPES:
            continue
        text = (block.get("text") or "").strip()
        if not text:
            continue
        out.append(
            {
                "page_idx": int(block.get("page_idx", 0)),
                "type": btype,
                "text": text,
                "text_level": block.get("text_level"),
            }
        )
    return out


def _fill_empty_pages_from_fulltext(
    page_texts: List[str],
    full_text: str,
) -> List[str]:
    if not full_text or not page_texts:
        return page_texts
    n = len(page_texts)
    empty = sum(1 for p in page_texts if len((p or "").strip()) < 5)
    # 过半页为空：若已有部分页有实质内容则跳过均分；否则用全文填充（扫描件常见）
    if empty > n // 2:
        nonempty_chars = sum(len((p or "").strip()) for p in page_texts)
        if nonempty_chars > max(len(full_text) // 10, 200):
            return page_texts
    if n == 1 and not page_texts[0].strip():
        return [full_text]

    avg = max(len(full_text) // n, 1)
    out = list(page_texts)
    pos = 0
    for i in range(n):
        if out[i].strip():
            continue
        end = min(pos + avg, len(full_text))
        chunk = full_text[pos:end].strip()
        if chunk:
            out[i] = chunk
        pos = end
    return out


def _repair_page_texts(page_texts: List[str], pdf_path: str, log=print) -> List[str]:
    """页文本大量重复或异常时，回退 PDF 文字层 / RapidOCR 单页"""
    if not page_texts or not pdf_path:
        return page_texts
    n = len(page_texts)
    nonempty = [p for p in page_texts if (p or "").strip()]
    if not nonempty:
        fitz_pages, _ = _fitz_page_texts(pdf_path)
        return fitz_pages if fitz_pages else page_texts

    from collections import Counter
    sigs = Counter((p or "")[:300] for p in page_texts if (p or "").strip())
    if sigs:
        top_count = sigs.most_common(1)[0][1]
        if top_count > max(3, n * 0.25):
            log(f"  [WARN] {top_count}/{n} 页 OCR 文本重复，回退 PDF 文字层")
            fitz_pages, _ = _fitz_page_texts(pdf_path)
            if fitz_pages and sum(len(p.strip()) for p in fitz_pages) > 100:
                merged = list(page_texts)
                for i in range(min(len(fitz_pages), n)):
                    if len(fitz_pages[i].strip()) > len((merged[i] or "").strip()):
                        merged[i] = fitz_pages[i]
                return merged

    return page_texts


def _rapidocr_fallback_pages(
    pdf_path: str,
    page_texts: List[str],
    config: dict,
    log=print,
) -> Tuple[List[str], int]:
    """仅对仍无文字的页跑 RapidOCR"""
    import page_ocr as po

    calls = 0
    out = list(page_texts)
    empty_idx = [i for i, t in enumerate(out) if len((t or "").strip()) < 5]
    if not empty_idx:
        return out, 0

    page_engine = config.get("ocr", {}).get("page_engine", "rapidocr")
    if page_engine != "rapidocr":
        return out, 0

    try:
        import fitz
        from rapidocr import RapidOCR

        rapid = RapidOCR()
        doc = fitz.open(pdf_path)
        for i in empty_idx:
            if i >= doc.page_count:
                continue
            text = po.get_page_text(
                pdf_path,
                i,
                config,
                log=lambda *a, **k: None,
                doc=doc,
                rapidocr_engine=rapid,
            )
            if text:
                out[i] = text
                calls += 1
        doc.close()
        if calls:
            log(f"  [INFO] RapidOCR fallback: {calls} 页")
    except Exception as e:
        log(f"  [WARN] RapidOCR fallback 失败: {e}")

    return out, calls


def _ocr_cache_enabled(config: dict) -> bool:
    return bool((config.get("ocr") or {}).get("cache", True))


def _ocr_cache_dir() -> str:
    try:
        from app_paths import get_outputs_dir
        base = get_outputs_dir()
    except Exception:
        base = os.path.join(os.getcwd(), "outputs")
    d = os.path.join(base, "ocr_cache")
    os.makedirs(d, exist_ok=True)
    return d


def _ocr_cache_key(pdf_path: str, engine: str, page_count: int) -> Optional[str]:
    """按 PDF 路径+大小+mtime+引擎+页数 生成缓存键。"""
    try:
        st = os.stat(pdf_path)
    except OSError:
        return None
    raw = f"{os.path.abspath(pdf_path)}|{st.st_size}|{int(st.st_mtime)}|{engine}|{page_count}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _load_ocr_cache(key: str) -> Optional[OcrDocumentResult]:
    path = os.path.join(_ocr_cache_dir(), f"{key}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return OcrDocumentResult(**data)
    except (OSError, ValueError, TypeError):
        return None


def _save_ocr_cache(key: str, result: OcrDocumentResult) -> None:
    path = os.path.join(_ocr_cache_dir(), f"{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(result), f, ensure_ascii=False)
    except (OSError, TypeError):
        pass


def ingest_pdf(pdf_path: str, config: dict, log=print) -> OcrDocumentResult:
    """WF1：单 PDF 统一 OCR，返回 full_text + page_texts"""
    if get_ocr_engine(config) == "local_onnx":
        from local_ocr import read_local_pdf

        local = read_local_pdf(pdf_path, config, log=log)
        for warning in local.warnings:
            log(f"  [WARN] {warning}")
        return OcrDocumentResult(
            pdf_path=pdf_path,
            page_texts=local.page_texts,
            full_text="\n\n".join(local.page_texts),
            source="local_onnx" if local.ocr_pages else "text_layer",
            ocr_engine_calls=1 if local.ocr_pages else 0,
            local_ocr_pages=local.ocr_pages,
            layout_blocks=local.layout_blocks,
            warnings=local.warnings,
        )
    page_count = get_pdf_page_count(pdf_path)
    if page_count <= 0:
        log(f"  [WARN] 无法读取页数: {pdf_path}")
        return OcrDocumentResult(pdf_path=pdf_path)

    cache_on = _ocr_cache_enabled(config)
    cache_key = None
    if cache_on:
        engine_name = get_ocr_engine(config)
        cache_key = _ocr_cache_key(pdf_path, engine_name, page_count)
        if cache_key:
            cached = _load_ocr_cache(cache_key)
            if cached is not None:
                log(f"  [OK] 命中 OCR 缓存，跳过重型 OCR: {os.path.basename(pdf_path)}")
                return cached

    result = OcrDocumentResult(pdf_path=pdf_path)
    page_texts, layer_full = _fitz_page_texts(pdf_path)

    if len(page_texts) < page_count:
        page_texts.extend([""] * (page_count - len(page_texts)))
    elif len(page_texts) > page_count:
        page_texts = page_texts[:page_count]

    if _text_layer_sufficient(page_texts):
        result.page_texts = page_texts
        result.full_text = layer_full or "\n\n".join(page_texts)
        result.source = "text_layer"
        result.ocr_engine_calls = 0
        log(f"  [OK] 文字层 {page_count} 页，跳过重型 OCR")
        if cache_on and cache_key:
            _save_ocr_cache(cache_key, result)
        return result

    engine = get_ocr_engine(config)
    full_text = ""
    err = None
    mineru_out = None

    mineru_out = None
    if engine == "mineru":
        from mineru_ocr import run_mineru_parse

        full_text, err, mineru_out = run_mineru_parse(pdf_path, config, log=log)
        result.ocr_engine_calls = 1
        result.source = "mineru"
        result.mineru_output_dir = mineru_out
    elif engine == "mineru_api":
        from mineru_api import extract_pdf_with_mineru_api

        full_text, err, mineru_out = extract_pdf_with_mineru_api(
            pdf_path, config, log=log
        )
        result.ocr_engine_calls = 1
        result.source = "mineru_api"
        result.mineru_output_dir = mineru_out
    else:
        full_text, err = extract_pdf_text(pdf_path, config, log=log)
        result.ocr_engine_calls = 1
        result.source = "baidu" if engine == "baidu" else engine

    if not full_text:
        log(f"  [WARN] 全文 OCR 失败: {err}")
        full_text = layer_full or ""

    result.full_text = full_text.strip()

    # MinerU layout → page_texts
    if mineru_out:
        sidecars = find_mineru_sidecar_files(mineru_out, pdf_path)
        if sidecars.get("content_list"):
            layout_pages = page_texts_from_content_list(
                sidecars["content_list"], page_count
            )
            if any(p.strip() for p in layout_pages):
                page_texts = layout_pages
                result.layout_blocks = layout_blocks_from_content_list(
                    sidecars["content_list"]
                )
                log(f"  [OK] MinerU layout → {page_count} 页文本")

    # 合并文字层与全文分配
    fitz_pages, _ = _fitz_page_texts(pdf_path)
    if fitz_pages:
        for i in range(min(len(fitz_pages), page_count)):
            if fitz_pages[i].strip() and len(fitz_pages[i].strip()) > len(
                (page_texts[i] or "").strip()
            ):
                page_texts[i] = fitz_pages[i]

    if result.full_text:
        page_texts = _fill_empty_pages_from_fulltext(page_texts, result.full_text)

    page_texts, rapid_calls = _rapidocr_fallback_pages(
        pdf_path, page_texts, config, log=log
    )
    page_texts = _repair_page_texts(page_texts, pdf_path, log=log)
    result.rapidocr_fallback_pages = rapid_calls
    if rapid_calls and result.source:
        result.source = f"{result.source}+rapidocr"
    elif rapid_calls:
        result.source = "rapidocr"

    result.page_texts = page_texts
    if not result.full_text:
        result.full_text = "\n\n".join(p for p in page_texts if p)

    # 仅缓存成功的重型 OCR 结果，避免缓存空/失败输出
    if cache_on and cache_key and result.full_text:
        _save_ocr_cache(cache_key, result)

    return result


def ingest_sources(
    paths: List[str],
    config: dict,
    log=print,
) -> Dict[str, OcrDocumentResult]:
    """批量 WF1"""
    out: Dict[str, OcrDocumentResult] = {}
    for path in paths:
        if path and os.path.exists(path):
            log(f"WF1 摄入: {os.path.basename(path)}")
            out[path] = ingest_pdf(path, config, log=log)
    return out
