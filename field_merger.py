#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分路提取结果合并"""

from case_outcome import synthesize_outcome_narrative
from document_segmenter import (
    DOC_TYPE_COMPLAINT,
    DOC_TYPE_CONTRACT,
    DOC_TYPE_EXECUTION,
    DOC_TYPE_INDICTMENT,
    DOC_TYPE_JUDGMENT,
    DOC_TYPE_POA,
)

FIELD_PRIORITY = {
    "委托人": [DOC_TYPE_POA, DOC_TYPE_CONTRACT, DOC_TYPE_JUDGMENT, DOC_TYPE_COMPLAINT],  # poa优先
    "委托人名称": [DOC_TYPE_POA, DOC_TYPE_CONTRACT],  # poa优先
    "委托人电话": [DOC_TYPE_POA, DOC_TYPE_CONTRACT],  # poa优先
    "委托人联系地址及电话": [DOC_TYPE_POA, DOC_TYPE_CONTRACT],  # poa优先
    "收案日期": [DOC_TYPE_CONTRACT],
    "立案日期": [DOC_TYPE_CONTRACT],
    "案号": [DOC_TYPE_JUDGMENT, DOC_TYPE_EXECUTION],
    "法院收案号": [DOC_TYPE_JUDGMENT, DOC_TYPE_EXECUTION],
    "案由": [DOC_TYPE_JUDGMENT],
    "审理法院": [DOC_TYPE_JUDGMENT],
    "审级": [DOC_TYPE_JUDGMENT],
    "委托方": [DOC_TYPE_JUDGMENT],  # 保留别名兼容
    "当事人": [DOC_TYPE_JUDGMENT, DOC_TYPE_COMPLAINT],
    "判决书中的原告": [DOC_TYPE_JUDGMENT, DOC_TYPE_COMPLAINT],
    "判决书中的被告": [DOC_TYPE_JUDGMENT, DOC_TYPE_COMPLAINT],
    "起诉状中的原告": [DOC_TYPE_COMPLAINT, DOC_TYPE_JUDGMENT],
    "起诉状中的被告": [DOC_TYPE_COMPLAINT, DOC_TYPE_JUDGMENT],
    "判决书上代理律师": [DOC_TYPE_JUDGMENT, DOC_TYPE_POA],
    "判决书原告的委托诉讼代理人": [DOC_TYPE_JUDGMENT, DOC_TYPE_POA],
    "地址": [DOC_TYPE_COMPLAINT],
    "对方当事人": [DOC_TYPE_JUDGMENT, DOC_TYPE_COMPLAINT],  # 调整优先级，判决书优先
    "案情简介": [DOC_TYPE_COMPLAINT, DOC_TYPE_JUDGMENT],
    "案件或项目名称": [DOC_TYPE_JUDGMENT],
    "结案小结": [DOC_TYPE_JUDGMENT, DOC_TYPE_EXECUTION],
    "审（办）结果": [DOC_TYPE_JUDGMENT, DOC_TYPE_EXECUTION],
    "法院文件清单": [DOC_TYPE_JUDGMENT, DOC_TYPE_EXECUTION],
    "承办律师": [DOC_TYPE_POA, DOC_TYPE_JUDGMENT],  # poa优先（授权委托书有律师信息）
    # 刑事案件角色（后续 normalize_fields 会映射到通用模板字段）
    "被告人": [DOC_TYPE_JUDGMENT, DOC_TYPE_INDICTMENT],
    "犯罪嫌疑人": [DOC_TYPE_INDICTMENT, DOC_TYPE_JUDGMENT],
    "公诉机关": [DOC_TYPE_INDICTMENT, DOC_TYPE_JUDGMENT],
    "辩护人": [DOC_TYPE_JUDGMENT, DOC_TYPE_POA],
    "罪名": [DOC_TYPE_JUDGMENT, DOC_TYPE_INDICTMENT],
    "审判法院": [DOC_TYPE_JUDGMENT],
}




def _is_valid(val: str) -> bool:
    from field_mapping import is_placeholder_value
    return not is_placeholder_value(val)


def _pick_value(field: str, partials: dict) -> str:
    # 优先按字段路由顺序取「有效」值（跳过"待确认"等占位符）
    for doc_type in FIELD_PRIORITY.get(field, []):
        val = (partials.get(doc_type) or {}).get(field) or ""
        if _is_valid(val):
            return val.strip()
    for bucket in partials.values():
        val = bucket.get(field) or ""
        if _is_valid(val):
            return val.strip()
    # 全部分路都没有有效值：留空（不再保留"待确认"占位符）
    return ""


def merge_partial_fields(partials: dict, case_type: str | None = None) -> dict:
    """partials: {doc_type: {field: value}} → flat dict"""
    all_keys = set()
    for bucket in partials.values():
        all_keys.update(bucket.keys())

    merged = {}
    for key in sorted(all_keys):
        val = _pick_value(key, partials)
        if val:
            merged[key] = val

    j_part = (partials.get(DOC_TYPE_JUDGMENT) or {}).get("结案小结", "")
    e_part = (partials.get(DOC_TYPE_EXECUTION) or {}).get("结案小结", "")
    j_review = (partials.get(DOC_TYPE_JUDGMENT) or {}).get("审（办）结果", "")
    e_review = (partials.get(DOC_TYPE_EXECUTION) or {}).get("审（办）结果", "")
    if not j_part and j_review:
        j_part = j_review
    if not e_part and e_review:
        e_part = e_review

    if j_part and e_part:
        combined = synthesize_outcome_narrative(j_part, e_part)
        if combined:
            merged["结案小结"] = combined
            merged["审（办）结果"] = combined
    elif j_part and not merged.get("结案小结"):
        merged["结案小结"] = j_part
        merged["审（办）结果"] = j_part
    elif e_part and not merged.get("结案小结"):
        merged["结案小结"] = e_part
        merged["审（办）结果"] = e_part

    doc_lists = []
    for dt in (DOC_TYPE_JUDGMENT, DOC_TYPE_EXECUTION):
        raw = (partials.get(dt) or {}).get("法院文件清单", "")
        if raw:
            doc_lists.append(raw)
    if doc_lists:
        items = []
        seen = set()
        for raw in doc_lists:
            for part in raw.replace("，", "、").split("、"):
                p = part.strip()
                if p and p not in seen:
                    seen.add(p)
                    items.append(p)
        if items:
            merged["法院文件清单"] = "、".join(items)

    # 案件类别仅服从显式案件配置；律所名称、客户评价没有材料就留空，
    # 不使用某一律所或「客户满意」作为全局默认事实。
    labels = {
        "civil": "民事",
        "criminal": "刑事",
        "admin": "行政",
        "nonlit": "非诉",
        "counsel": "法律顾问",
        "arbitration": "仲裁",
        "consultation": "咨询代书",
    }
    if case_type in labels:
        merged["案件类别"] = labels[case_type]

    return merged
