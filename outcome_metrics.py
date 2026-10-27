#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审办结果/结案小结字段质量度量（V6）"""

from __future__ import annotations

import re

from case_outcome import classify_execution_outcome

OUTCOME_KEYS = ("结案小结", "审（办）结果", "审办结果")

EXECUTION_MARKERS = (
    "执行", "终本", "终结本次", "破产", "和解", "撤回", "执行完毕", "参与分配", "债权凭证",
)


def pick_outcome_text(fields: dict) -> str:
    if not fields:
        return ""
    for k in OUTCOME_KEYS:
        v = (fields.get(k) or "").strip()
        if v:
            return v
    return ""


def outcome_type_label(outcome_type: str) -> str:
    labels = {
        "zhiben": "常规终本",
        "bankruptcy": "破产/执转破",
        "settlement": "执行和解",
        "withdraw": "撤回执行",
        "completed": "执行完毕",
        "participation": "参与分配",
        "denial": "不予执行",
        "suspension": "中止执行",
        "debt_cert": "债权凭证",
        "property_offset": "以物抵债",
        "generic": "一般执行",
        "": "无执行/仅判决",
    }
    return labels.get(outcome_type or "", outcome_type or "未知")


def _char_bigrams(text: str) -> set:
    s = re.sub(r"\s+", "", text or "")
    if len(s) < 2:
        return set(s) if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def semantic_similarity(pred: str, gold: str) -> float:
    """轻量语义相似：二元组 Jaccard + 关键词加权。"""
    pred = (pred or "").strip()
    gold = (gold or "").strip()
    if not gold:
        return 1.0 if not pred else 0.0
    if not pred:
        return 0.0
    if pred == gold:
        return 1.0
    bg_p, bg_g = _char_bigrams(pred), _char_bigrams(gold)
    jaccard = len(bg_p & bg_g) / max(len(bg_p | bg_g), 1)
    kw_score = 0.0
    for kw in ("法院判决", "偿还", "利息", "连带", "执行", "终本", "破产", "和解", "撤回"):
        if kw in gold and kw in pred:
            kw_score += 0.08
    return min(1.0, jaccard * 0.75 + kw_score)


def outcome_type_match(pred: str, gold: str) -> bool:
    pt = classify_execution_outcome(pred)
    gt = classify_execution_outcome(gold)
    if not gt and not pt:
        return True
    if gt in ("generic", "zhiben") and pt in ("generic", "zhiben"):
        return True
    if gt == pt:
        return True
    # 金标准无执行表述
    if gt == "" and not any(m in gold for m in EXECUTION_MARKERS):
        return pt == "" or "终结本次" not in pred
    return False


def score_outcome(pred_fields: dict, gold_text: str) -> dict:
    pred = pick_outcome_text(pred_fields)
    gold = (gold_text or "").strip()
    sim = semantic_similarity(pred, gold)
    type_ok = outcome_type_match(pred, gold)
    struct_ok = (not pred) or pred.startswith("法院判决") or "调解" in pred or "裁定" in pred
    score = sim
    if not type_ok:
        score *= 0.6
    if gold and pred and not struct_ok:
        score *= 0.85
    return {
        "pred": pred,
        "gold": gold,
        "similarity": round(sim, 3),
        "type_match": type_ok,
        "struct_ok": struct_ok,
        "score": round(score, 3),
        "pred_type": classify_execution_outcome(pred),
        "gold_type": classify_execution_outcome(gold),
    }
