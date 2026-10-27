#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长 PDF 文本截取：保证判决书、执行裁定书等关键段落进入 LLM 上下文"""


def build_pdf_chunk_for_llm(pdf_text: str, ocr_engine: str = "baidu") -> str:
    """
    MinerU 长卷宗：头+尾+锚点段落（执行裁定书/判决书），避免中间执行文书被省略。
    """
    if not pdf_text:
        return ""
    head_lim = 18000 if ocr_engine in ("mineru", "mineru_api") else 12000
    tail_lim = 8000 if ocr_engine in ("mineru", "mineru_api") else 6000
    if len(pdf_text) <= head_lim + tail_lim:
        return pdf_text

    head = pdf_text[:head_lim]
    tail = pdf_text[-tail_lim:]
    mid_slices = []
    seen = set()
    for anchor in ("刑事判决书", "行政判决书", "执行裁定书", "终结本次执行程序", "民事判决书", "判决书"):
        idx = pdf_text.find(anchor)
        if idx < 0:
            continue
        snippet = pdf_text[max(0, idx - 2000) : idx + 7000]
        key = snippet[:200]
        if key in seen:
            continue
        seen.add(key)
        mid_slices.append(snippet)
        if len(mid_slices) >= 2:
            break

    if mid_slices:
        mid = "\n\n".join(mid_slices)
        return (
            head
            + "\n\n[---以下摘录含判决书/执行裁定书等关键段落---]\n\n"
            + mid
            + "\n\n[...其余页省略...]\n\n"
            + tail
        )
    return head + "\n\n[...中间部分省略...]\n\n" + tail
