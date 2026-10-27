# -*- coding: utf-8 -*-
"""字段清洗回归测试：确认「待确认/字段说明文字」不留入模板。

保护 Iteration 17 的「宁可留空」原则：OCR 读不准时不得把
「待确认」或字段说明文字当值填进五个表格。
"""

from field_mapping import expand_fields_for_template, _is_valid_field_value
from field_merger import merge_partial_fields
from field_sanitize import enrich_party_fields


def test_merge_drops_placeholder_values():
    """merge_partial_fields 不保留「待确认」占位值。"""
    partials = {
        "contract": {"委托人": "张三", "收案日期": "待确认"},
        "judgment": {"案由": "借款纠纷", "承办律师": "无"},
    }
    merged = merge_partial_fields(partials)
    assert merged.get("委托人") == "张三"
    assert merged.get("案由") == "借款纠纷"
    assert not merged.get("收案日期"), "待确认应留空"
    assert not merged.get("承办律师"), "'无'应留空"


def test_enrich_clears_placeholder_all_fields():
    """enrich_party_fields 对全部字段清「待确认/无/未知/暂无」。"""
    m = enrich_party_fields({
        "委托人": "甲公司",
        "地址": "待确认",
        "案由": "未知",
        "承办律师": "暂无",
    })
    assert m["委托人"] == "甲公司"
    assert m["地址"] == ""
    assert m["案由"] == ""
    assert m["承办律师"] == ""


def test_is_valid_field_value_rejects_requirement_text():
    """字段说明/提取要求文字判定为无效。"""
    bad = [
        "[从委托代理合同中提取落款日期]",
        "从文档中提取",
        "[从判决书上提取代理律师信息]",
        "委托代理合同中落款时间",
        "原告律师信息",
    ]
    for v in bad:
        assert not _is_valid_field_value(v), f"应判无效: {v!r}"


def test_is_valid_field_value_keeps_real_data():
    """真实数据判定为有效。"""
    good = [
        "2019-09-01",
        "广东至高律师事务所",
        "（2019）粤0605民初22131号",
        "判决被告偿还贷款本金688204.93元及利息",
    ]
    for v in good:
        assert _is_valid_field_value(v), f"应判有效: {v!r}"


def test_archive_template_skips_placeholder_values():
    """档案卷宗模板：待确认/字段说明字段不填入。"""
    m = enrich_party_fields({
        "委托人": "甲公司",
        "委托人电话": "待确认",
        "地址": "[从起诉状中提取]",
        "案件类别": "民事",
    })
    mapped = expand_fields_for_template("档案卷宗", m)
    assert mapped.get("委托代理合同中委托人") == "甲公司"
    assert "委托人电话" not in mapped or not mapped.get("委托人电话")
    assert "地址" not in mapped or not mapped.get("地址")


def test_merger_does_not_invent_firm_case_type_or_client_satisfaction():
    merged = merge_partial_fields({"contract": {"委托人": "虚构甲公司"}})
    for field in ("律师事务所", "案件类别", "委托人对服务质量意见"):
        assert not merged.get(field)


def test_merger_preserves_actual_client_feedback_and_explicit_case_type():
    merged = merge_partial_fields(
        {"contract": {
            "律师事务所": "虚构示例律师事务所",
            "委托人对服务质量意见": "委托人提出需要改进沟通频率",
        }},
        case_type="admin",
    )
    assert merged["律师事务所"] == "虚构示例律师事务所"
    assert merged["委托人对服务质量意见"] == "委托人提出需要改进沟通频率"
    assert merged["案件类别"] == "行政"
