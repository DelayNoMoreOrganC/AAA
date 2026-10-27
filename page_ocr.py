#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""页级 OCR — 用于文书定位的轻量级文字识别

策略分层：
1. PDF 文字层优先（fitz/PyMuPDF）
2. 无文字层则页面上半部低 DPI RapidOCR
3. 回退到 ocr.engine（baidu/mineru/mineru_api）
"""

import io
from typing import List, Optional, Tuple

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


def _extract_text_from_pdf_page(pdf_path: str, page_num: int, config: dict, log=print) -> Optional[str]:
    """从 PDF 页提取文字层

    Args:
        pdf_path: PDF 文件路径
        page_num: 页码（0-based）
        config: 配置字典
        log: 日志函数

    Returns:
        提取的文字，若失败则返回 None
    """
    if fitz is None:
        log("fitz/PyMuPDF 未安装，跳过文字层提取")
        return None

    try:
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        text = page.get_text()
        doc.close()

        # 清理文字（去除过多空白）
        if text and len(text.strip()) > 10:
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            return '\n'.join(lines)
        return None
    except Exception as e:
        log(f"PDF 文字层提取失败: {e}")
        return None


def _rapidocr_page_region(page, clip_rect, ocr_engine, mat=None) -> Optional[str]:
    """对页面指定区域做 RapidOCR"""
    if ocr_engine is None:
        return None
    mat = mat or fitz.Matrix(1.5, 1.5)
    pix = page.get_pixmap(matrix=mat, clip=clip_rect)
    img_bytes = pix.tobytes("png")
    result = ocr_engine(img_bytes)
    if result and hasattr(result, "txts") and result.txts:
        texts = [text for text in result.txts if text and len(text.strip()) > 1]
        if texts:
            return "\n".join(texts)
    return None


def _ocr_page_rapidocr(doc, page_num: int, ocr_engine, log=print) -> Optional[str]:
    """RapidOCR：先上半页，无结果再整页（标题可能不在顶部）"""
    if fitz is None or ocr_engine is None:
        return None

    try:
        page = doc[page_num]
        rect = page.rect
        top_half_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + rect.height / 2)

        text = _rapidocr_page_region(page, top_half_rect, ocr_engine)
        if text:
            return text
        return _rapidocr_page_region(page, rect, ocr_engine)
    except Exception as e:
        log(f"RapidOCR 页级 OCR 失败: {e}")
        return None


def _fallback_baidu_page_ocr(pdf_path: str, page_num: int, config: dict, log=print) -> Optional[str]:
    """页级回退仅使用百度 OCR，避免每页调用 MinerU 导致内存耗尽"""
    if fitz is None:
        return None

    try:
        doc = fitz.open(pdf_path)
        single_page = fitz.open()
        single_page.insert_pdf(doc, from_page=page_num, to_page=page_num)
        pdf_bytes = single_page.tobytes()
        doc.close()
        single_page.close()
        return _baidu_ocr_bytes(pdf_bytes, config, log)
    except Exception as e:
        log(f"百度页级回退 OCR 失败: {e}")
        return None


def _baidu_ocr_bytes(pdf_bytes: bytes, config: dict, log=print) -> Optional[str]:
    """百度 OCR 单页识别"""
    try:
        import fitz
        from aip import AipOcr
        from baidu_ocr_implementation import call_baidu_ocr

        # 获取百度OCR配置
        baidu = config.get("baidu_ocr", {})
        app_id = baidu.get("app_id", "")
        api_key = baidu.get("api_key", "")
        secret_key = baidu.get("secret_key", "")

        if not all([app_id, api_key, secret_key]):
            log("百度 OCR 配置不完整")
            return None

        # 从PDF bytes中提取第一页图片
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) == 0:
            return None

        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        img_bytes = pix.tobytes("png")
        doc.close()

        # 调用百度OCR
        client = AipOcr(app_id, api_key, secret_key)
        ocr_mode = baidu.get("mode", "basic")
        result = call_baidu_ocr(client, img_bytes, ocr_mode)

        if result.get("words_result"):
            return "\n".join(w["words"] for w in result["words_result"])
        elif result.get("error_msg"):
            log(f"百度 OCR 错误: {result['error_msg']}")
            return None
        else:
            return None

    except Exception as e:
        log(f"百度 OCR 失败: {e}")
        return None


def _mineru_ocr_bytes(pdf_bytes: bytes, engine: str, config: dict, log=print) -> Optional[str]:
    """MinerU / MinerU_API 单页识别"""
    try:
        if engine == "mineru_api":
            # 使用 MinerU API
            try:
                from mineru_api import mineru_ocr_bytes
                return mineru_ocr_bytes(pdf_bytes, config, log)
            except ImportError:
                log("mineru_api 模块未找到")
                return None
        else:
            # 本地 MinerU（需要安装）
            log("本地 MinerU 暂不支持页级回退")
            return None
    except Exception as e:
        log(f"MinerU OCR 失败: {e}")
        return None


def get_page_text(
    pdf_path: str,
    page_num: int,
    config: dict,
    log=print,
    *,
    doc=None,
    rapidocr_engine=None,
) -> Optional[str]:
    """获取单页文字（分层策略）"""
    # 第 1 层：PDF 文字层
    if doc is not None:
        try:
            text = doc[page_num].get_text()
            if text and len(text.strip()) > 10:
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                if lines:
                    return "\n".join(lines)
        except Exception:
            pass
    else:
        text = _extract_text_from_pdf_page(pdf_path, page_num, config, log)
        if text:
            return text

    # 第 2 层：RapidOCR（上半页 → 整页）
    page_engine = config.get("ocr", {}).get("page_engine", "rapidocr")
    if page_engine == "rapidocr" and doc is not None and rapidocr_engine is not None:
        text = _ocr_page_rapidocr(doc, page_num, rapidocr_engine, log)
        if text:
            return text
    elif page_engine == "paddle":
        log("PaddleOCR 页级引擎暂未实现")
    elif page_engine == "tesseract":
        log("Tesseract 页级引擎暂未实现")

    # 第 3 层：仅百度轻量回退（禁止每页 MinerU，防止内存耗尽/系统死机）
    ocr_engine = config.get("ocr", {}).get("engine", "baidu")
    if ocr_engine == "baidu":
        text = _fallback_baidu_page_ocr(pdf_path, page_num, config, log)
        if text:
            return text

    return ""


def get_page_texts(pdf_path: str, config: dict, log=print) -> List[str]:
    """获取 PDF 所有页的文字（复用文档句柄与 RapidOCR 实例，降低内存压力）

    .. deprecated::
        V4 Phase E 起请使用 ``ocr_pipeline.ingest_pdf``（WF1 统一摄入）。
        本函数会对每页跑 RapidOCR，仅保留给遗留调用方。
    """
    if fitz is None:
        log("fitz/PyMuPDF 未安装，无法获取页数")
        return []

    rapidocr_engine = None
    page_engine = config.get("ocr", {}).get("page_engine", "rapidocr")
    if page_engine == "rapidocr":
        try:
            from rapidocr import RapidOCR

            rapidocr_engine = RapidOCR()
        except ImportError:
            log("RapidOCR 未安装，跳过页级 OCR")

    try:
        doc = fitz.open(pdf_path)
        page_count = doc.page_count
        page_texts = []
        for i in range(page_count):
            text = get_page_text(
                pdf_path,
                i,
                config,
                log,
                doc=doc,
                rapidocr_engine=rapidocr_engine,
            )
            page_texts.append(text or "")
            if (i + 1) % 5 == 0 or i + 1 == page_count:
                log(f"页 {i+1}/{page_count} OCR 完成")
        doc.close()
        return page_texts
    except Exception as e:
        log(f"获取 PDF 页数失败: {e}")
        return []
