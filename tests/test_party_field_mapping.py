# -*- coding: utf-8 -*-
"""模板字段槽位映射：原被告拆分、占位符不串格。"""

import pytest

from field_mapping import expand_fields_for_template
from field_sanitize import enrich_party_fields, parse_litigation_parties
from lian_approval_fill import expand_lian_fields


def test_parse_litigation_parties_labeled():
    pl, df = parse_litigation_parties("原告：兴泰贸易有限公司，被告：张三")
    assert pl == "兴泰贸易有限公司"
    assert df == "张三"


def test_parse_litigation_parties_su_format():
    pl, df = parse_litigation_parties("兴泰贸易有限公司诉张三借款合同纠纷一案")
    assert pl == "兴泰贸易有限公司"
    assert "张三" in df


def test_enrich_splits_combined_party():
    raw = {
        "委托人": "兴泰贸易有限公司",
        "当事人": "原告：兴泰贸易有限公司，被告：张三",
        "承办律师": "张鑫莹",
        "判决书上代理律师": "张鑫莹",
    }
    m = enrich_party_fields(raw)
    assert m["委托人"] == "兴泰贸易有限公司"
    assert m["原告"] == "兴泰贸易有限公司"
    assert m["被告"] == "张三"
    assert "判决书中的原告" not in m
    assert "起诉状中的原告" not in m
    assert m["判决书上代理律师"] == "张鑫莹"


def test_archive_template_no_cross_slot_fallback():
    m = enrich_party_fields({
        "委托人": "甲公司",
        "当事人": "原告：甲公司，被告：乙公司",
        "判决书中的原告": "甲公司",
        "判决书中的被告": "乙公司",
        "承办律师": "李律师",
        "判决书上代理律师": "李律师",
        "案由": "借款合同纠纷",
        "审理法院": "广东省佛山市中级人民法院",
        "案件类别": "民事",
    })
    mapped = expand_fields_for_template("档案卷宗", m)
    assert mapped["委托代理合同中委托人"] == "甲公司"
    assert mapped["判决书中的原告"] == "甲公司"
    assert mapped["判决书中的被告"] == "乙公司"
    assert mapped["判决书原告的委托诉讼代理人"] == "李律师"


def test_delivery_list_plaintiff_not_blob():
    m = enrich_party_fields({
        "当事人": "原告：甲公司，被告：乙公司",
        "判决书上代理律师": "王律师",
    })
    mapped = expand_fields_for_template("送达材料清单", m)
    assert mapped["判决书上的原告"] == "甲公司"
    assert mapped["判决书上代理律师"] == "王律师"


def test_bank_client_does_not_prove_plaintiff_or_opponent_defendant():
    m = enrich_party_fields({
        "委托人": "东莞银行股份有限公司佛山分行",
        "对方当事人": "潘超，男，1985年12月1日出生",
        "判决书上代理律师": "招伟松",
    })
    assert m["委托人"] == "东莞银行股份有限公司佛山分行"
    assert m["对方当事人"] == "潘超，男，1985年12月1日出生"
    assert not any(m.get(key) for key in ("原告", "被告", "判决书中的原告", "判决书中的被告"))


def test_lian_party_and_client_separate():
    m = enrich_party_fields({
        "委托人": "甲公司",
        "当事人": "原告：甲公司，被告：乙公司、丙公司",
        "判决书中的被告": "乙公司、丙公司",
        "判决书中的原告": "甲公司",
    })
    lian = expand_lian_fields(m)
    assert lian["3"] == "甲公司"
    assert lian["4"] == "甲公司"
    assert "乙公司" in lian["8"]


@pytest.mark.parametrize("case_type", ["civil", "criminal", "admin", "nonlit", "counsel", "arbitration", "consultation"])
def test_normalize_neutral_client_does_not_invent_litigation_or_document_roles(case_type):
    import archive_pipeline as ap
    fields = ap.normalize_fields({"委托人": "虚构甲", "对方当事人": "虚构乙", "承办律师": "李律师"},
                                 pdf_text="委托人：虚构甲", case_type=case_type)
    assert fields["委托人"] == "虚构甲"
    assert fields["对方当事人"] == "虚构乙"
    assert fields["承办律师"] == "李律师"
    for key in ("原告", "被告", "判决书中的原告", "起诉状中的原告", "判决书中的被告", "起诉状中的被告",
                "判决书上代理律师", "判决书原告的委托诉讼代理人"):
        assert not fields.get(key), (case_type, key, fields.get(key))
    if case_type in ("arbitration", "consultation", "nonlit", "counsel"):
        assert fields["当事人"] == "虚构甲"


def test_explicit_document_roles_are_preserved_without_cross_document_overwrite():
    original = {"委托人": "虚构被告", "原告": "虚构显式原告", "被告": "虚构被告",
                "起诉状中的原告": "虚构起诉原告", "判决书中的原告": "虚构判决原告",
                "起诉状中的被告": "虚构起诉被告", "判决书中的被告": "虚构判决被告",
                "承办律师": "虚构承办律师", "判决书原告的委托诉讼代理人": "虚构对方律师"}
    fields = enrich_party_fields(original, case_type="civil")
    for key, value in original.items():
        assert fields[key] == value


def test_only_explicit_complaint_role_does_not_assert_judgment_was_present():
    fields = enrich_party_fields({"起诉状中的原告": "虚构甲"}, case_type="civil")
    assert fields["起诉状中的原告"] == fields["原告"] == "虚构甲"
    assert not fields.get("判决书中的原告")
    # Historical Word slot names can share a value without mutating facts.
    rendered = expand_fields_for_template("档案卷宗", fields)
    assert rendered["判决书中的原告"] == "虚构甲"
    assert "判决书中的原告" not in fields


def test_nonlitigation_project_name_does_not_create_litigation_roles():
    fields = enrich_party_fields({"委托人": "虚构顾问单位", "案件或项目名称": "甲诉乙合同纠纷一案资料咨询"}, case_type="consultation")
    assert fields["委托人"] == "虚构顾问单位"
    assert not fields.get("原告")
    assert not fields.get("被告")
