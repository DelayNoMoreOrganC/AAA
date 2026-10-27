#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""附件分类器 — 将用户补充的附件归位到目录项

策略：
1. 优先通过文件名匹配 doc_type 常量
2. 若文件名不明确，使用页级 OCR 识别标题
3. 仍无法识别则默认归类到 'evidence'（证据材料）
"""

import os
from dataclasses import dataclass
from typing import List, Optional

import archive_catalog as ac
import document_segmenter as ds
import page_ocr as po


@dataclass
class ClassifiedAttachment:
    """已分类的附件"""
    file_path: str  # 文件路径
    doc_type: str  # 识别出的文书类型
    catalog_item: Optional[object]  # 对应的目录项（CatalogItem），若 None 则未匹配到具体位置
    confidence: str = "filename"  # "filename" | "ocr" | "default"


def classify_by_filename(filepath: str, case_type: str) -> Optional[str]:
    """根据文件名猜测 doc_type

    Args:
        filepath: 文件路径
        case_type: 案件类型

    Returns:
        doc_type 字符串，若无法识别则返回 None
    """
    filename = os.path.basename(filepath or "").lower()
    doc_type = ds.guess_doc_type_from_filename(filename)
    # 如果识别为 'other'，返回 None 让后续层处理（OCR → default evidence）
    if doc_type == ds.DOC_TYPE_OTHER:
        return None
    return doc_type


def classify_by_ocr(
    filepath: str,
    case_type: str,
    config: dict,
    log=print
) -> Optional[str]:
    """通过 OCR 识别文件内容来猜测 doc_type

    Args:
        filepath: 文件路径（PDF 或 图片）
        case_type: 案件类型
        config: 配置字典
        log: 日志函数

    Returns:
        doc_type 字符串，若无法识别则返回 None
    """
    if not filepath or not os.path.exists(filepath):
        return None

    ext = os.path.splitext(filepath)[1].lower()

    # 若是图片，先转 PDF（这里简化处理，假设只有 PDF）
    if ext not in ('.pdf',):
        log(f"非 PDF 文件跳过 OCR: {ext}")
        return None

    # 获取第一页文字
    try:
        page_text = po.get_page_text(filepath, 0, config, log)
        if not page_text:
            return None

        # 检查各 doc_type 的锚点
        for doc_type, anchors in ds.ANCHORS.items():
            for anchor in anchors:
                if anchor in page_text:
                    log(f"OCR 识别到 {doc_type}: {anchor}")
                    return doc_type
    except Exception as e:
        log(f"OCR 分类失败: {e}")

    return None


def classify_attachments(
    files: List[str],
    case_type: str,
    config: dict,
    log=print
) -> List[ClassifiedAttachment]:
    """分类用户补充的附件

    Args:
        files: 文件路径列表
        case_type: 案件类型代码
        config: 配置字典
        log: 日志函数

    Returns:
        ClassifiedAttachment 列表
    """
    results = []

    for filepath in files:
        if not filepath or not os.path.exists(filepath):
            log(f"文件不存在，跳过: {filepath}")
            continue

        # 第 1 层：文件名匹配
        doc_type = classify_by_filename(filepath, case_type)

        # 第 2 层：OCR 匹配
        if not doc_type:
            doc_type = classify_by_ocr(filepath, case_type, config, log)
            confidence = "ocr" if doc_type else "default"
        else:
            confidence = "filename"

        # 第 3 层：默认证据材料
        if not doc_type:
            doc_type = ds.DOC_TYPE_EVIDENCE
            confidence = "default"
            log(f"无法识别，默认归类为证据材料: {filepath}")

        # 查找对应的目录项
        catalog_item = ac.catalog_item_for_doc_type(case_type, doc_type)

        result = ClassifiedAttachment(
            file_path=filepath,
            doc_type=doc_type,
            catalog_item=catalog_item,
            confidence=confidence,
        )
        results.append(result)

        log(f"附件分类: {os.path.basename(filepath)} -> {doc_type} (confidence: {confidence})")

    return results


def group_attachments_by_seq(
    attachments: List[ClassifiedAttachment]
) -> dict:
    """按目录序号分组附件

    Args:
        attachments: ClassifiedAttachment 列表

    Returns:
        {seq: [attachments]} 字典
    """
    groups = {}

    for att in attachments:
        if att.catalog_item is not None:
            seq = att.catalog_item.seq
        else:
            # 未匹配到目录项的归入 -1（待处理）
            seq = -1

        if seq not in groups:
            groups[seq] = []
        groups[seq].append(att)

    return groups
