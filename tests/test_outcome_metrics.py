# -*- coding: utf-8 -*-
"""outcome_metrics 度量测试"""

from outcome_metrics import (
    outcome_type_match,
    pick_outcome_text,
    score_outcome,
    semantic_similarity,
)


def test_semantic_similarity_identical():
    assert semantic_similarity("法院判决被告偿还借款。", "法院判决被告偿还借款。") == 1.0


def test_semantic_similarity_partial():
    a = "法院判决被告向原告偿还借款本金及利息。"
    b = "法院判决被告偿还借款本金。"
    assert semantic_similarity(a, b) > 0.4


def test_outcome_type_match_zhiben_generic():
    pred = "法院判决偿还借款。执行过程中，无财产可供执行，终结本次执行程序。"
    gold = "法院判决被告偿还本息。执行中查封财产后终本。"
    assert outcome_type_match(pred, gold) is True


def test_outcome_type_match_no_exec():
    pred = "法院判决被告偿还借款。"
    gold = "法院判决被告向原告支付货款。"
    assert outcome_type_match(pred, gold) is True


def test_score_outcome_returns_keys():
    sc = score_outcome({"结案小结": "法院判决被告偿还借款。"}, "法院判决被告偿还借款本金。")
    assert "score" in sc and "similarity" in sc
    assert sc["score"] > 0


def test_pick_outcome_prefers_结案小结():
    fields = {"审办结果": "B", "结案小结": "A"}
    assert pick_outcome_text(fields) == "A"
