#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 文本提取（V1 百度 OCR / V2 MinerU，供 EXE 与流水线共用）"""

import os
import time
import tempfile
import shutil

from settings import get_baidu_config, get_ocr_engine


def _is_baidu_quota_error(error_msg):
    if not error_msg:
        return False
    msg = error_msg.lower()
    return "daily request limit" in msg or "qps request limit" in msg


def extract_pdf_text_direct(pdf_path):
    try:
        import fitz
        doc = fitz.open(pdf_path)
        text = "".join(page.get_text() for page in doc)
        doc.close()
        if len(text.strip()) > 100:
            return text
    except Exception:
        pass
    return None


def get_pdf_page_count(pdf_path: str) -> int:
    """返回 PDF 总页数；失败时返回 0"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        n = len(doc)
        doc.close()
        return n
    except Exception:
        return 0


def sample_page_indices(total: int, budget: int) -> list:
    if total <= budget:
        return list(range(total))
    head = list(range(min(12, total)))
    tail = list(range(max(0, total - 8), total))
    mid_need = max(0, budget - len(head) - len(tail))
    mid = []
    if mid_need > 0 and total > 20:
        start, end = 12, total - 8
        step = max(1, (end - start) // mid_need)
        mid = [start + i * step for i in range(mid_need) if start + i * step < end]
    return sorted(set(head + mid + tail))[:budget]


def extract_pdf_text_sampled(pdf_path, config, log=print):
    """V1：百度 OCR（扫描件分页/抽样）"""
    from aip import AipOcr
    import fitz
    from baidu_ocr_implementation import call_baidu_ocr

    direct = extract_pdf_text_direct(pdf_path)
    if direct:
        log(f"  [OK] PDF 文字层 {len(direct)} 字符")
        return direct, None

    baidu = get_baidu_config()
    max_pages = config.get("local_ocr", {}).get("max_pages", 0)
    ocr_mode = config.get("baidu_ocr", {}).get("mode", baidu.get("OCR_MODE", "basic"))

    client = AipOcr(baidu["APP_ID"], baidu["API_KEY"], baidu["SECRET_KEY"])
    doc = fitz.open(pdf_path)
    total = len(doc)
    if max_pages is None or max_pages <= 0 or max_pages >= total:
        indices = list(range(total))
        log(f"  [INFO] OCR 全部 {total} 页")
    else:
        indices = sample_page_indices(total, max_pages)
        log(f"  [INFO] 抽样 OCR {len(indices)}/{total} 页")
    temp_dir = tempfile.mkdtemp()
    all_text = ""
    last_error = None
    try:
        for page_num in indices:
            page = doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            img_path = os.path.join(temp_dir, f"p{page_num + 1}.png")
            pix.save(img_path)
            with open(img_path, "rb") as fp:
                image_data = fp.read()
            result = call_baidu_ocr(client, image_data, ocr_mode)
            if result.get("words_result"):
                all_text += "\n".join(w["words"] for w in result["words_result"]) + "\n"
            elif result.get("error_msg"):
                last_error = result["error_msg"]
                if _is_baidu_quota_error(last_error):
                    break
            time.sleep(0.4)
        doc.close()
        if len(all_text.strip()) > 100:
            return all_text, None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return None, last_error


def extract_pdf_text(pdf_path, config, log=print):
    """
    统一入口。config.ocr.engine:
      - mineru : 本地 MinerU（V2，推荐）
      - baidu  : 百度云 OCR（V1 默认）
    """
    engine = get_ocr_engine(config)
    if engine == "local_onnx":
        from local_ocr import read_local_pdf

        result = read_local_pdf(pdf_path, config, log=log)
        for warning in result.warnings:
            log(f"  [WARN] {warning}")
        return "\n\n".join(result.page_texts), None
    if engine == "mineru_api":
        from mineru_api import extract_pdf_with_mineru_api

        text, err, _ = extract_pdf_with_mineru_api(pdf_path, config, log=log)
        return text, err

    if engine == "mineru":
        from mineru_ocr import extract_pdf_with_mineru

        return extract_pdf_with_mineru(pdf_path, config, log=log)

    text, err = extract_pdf_text_sampled(pdf_path, config, log=log)
    if text:
        return text, None
    return text, err
