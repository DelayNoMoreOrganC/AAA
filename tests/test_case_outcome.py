# -*- coding: utf-8 -*-
"""结案小结/审办结果 — 法律实务表述测试"""

import case_outcome as co
import pytest


def test_bankruptcy_blurb_extracted():
    text = (
        "执行裁定书……本院于2021年裁定受理被执行人某公司破产清算，"
        "本案移送破产审查，终结对被执行人的本次执行程序。"
    )
    blurb = co.extract_special_execution_blurb(text)
    assert "破产" in blurb


def test_outcome_appends_bankruptcy_when_missing():
    fields = {
        "结案小结": "法院判决被告偿还本金及利息。执行过程中查封拍卖部分财产。",
        "审（办）结果": "法院判决被告偿还本金及利息。执行过程中查封拍卖部分财产。",
    }
    pdf_text = (
        "民事判决书……判决被告偿还本金及利息。"
        "执行裁定书……执行过程中查封、拍卖部分财产，"
        "后裁定受理被执行人破产清算，本案移送破产审查，终结本次执行程序。"
    )
    out = co.ensure_outcome_covers_execution(fields, pdf_text)
    assert "破产" in out["结案小结"], out["结案小结"]
    assert "移送破产" in out["结案小结"]
    assert out["结案小结"] == out["审（办）结果"] == out["审办结果"]
    assert len(out["结案小结"]) <= co.CASE_OUTCOME_MAX_LEN


def test_no_duplicate_when_already_has_special():
    fields = {
        "结案小结": "法院判决偿还借款。执行中被执行人破产清算，移送破产审查后终结执行。",
        "审（办）结果": "法院判决偿还借款。执行中被执行人破产清算，移送破产审查后终结执行。",
    }
    pdf_text = "……破产清算……移送破产审查……"
    out = co.ensure_outcome_covers_execution(fields, pdf_text)
    assert out["结案小结"] == fields["结案小结"]


def test_settlement_and_withdraw_markers_scored():
    assert co._outcome_exec_score("双方达成执行和解，申请执行人撤回执行申请") >= 2


def test_judgment_polish_strips_execution():
    raw = "被告应偿还借款。执行过程中查封财产，终结本次执行程序。"
    polished = co._polish_judgment_clause(raw)
    assert "执行" not in polished
    assert polished.startswith("法院判决")


def test_synthesize_bankruptcy_practice_form():
    j = "法院判决被告向原告偿还借款本金及利息。"
    e = "裁定受理被执行人破产清算，本案移送破产审查，终结本次执行程序。"
    merged = co.synthesize_outcome_narrative(j, e)
    assert "破产" in merged
    assert "移送破产" in merged
    assert merged.startswith("法院判决")


def test_withdraw_no_exec_prefix():
    j = "法院判决被告向原告支付货款。"
    e = "申请执行人申请撤回执行申请，本院裁定准许。"
    merged = co.synthesize_outcome_narrative(j, e)
    assert "撤回" in merged
    assert "执行过程中，申请执行人" not in merged


def test_general_skipped_when_bankruptcy_in_pdf():
    """全文含破产时，不应仅用「无财产终本」兜底而漏写破产。"""
    fields = {"结案小结": "法院判决被告偿还借款。", "审（办）结果": "法院判决被告偿还借款。"}
    pdf_text = (
        "民事判决书……判决被告偿还借款。"
        "执行裁定书……因被执行人无其他可供执行财产，终结本次执行程序。"
        "后裁定受理被执行人破产清算，本案移送破产审查。"
    )
    out = co.ensure_outcome_covers_execution(fields, pdf_text)
    assert "破产" in out["结案小结"], out["结案小结"]


def test_zhiben_practice_template():
    blurb = "执行裁定书……查封、拍卖部分财产……无其他可供执行财产……终结本次执行程序。"
    clause = co.format_execution_for_practice(blurb, "zhiben")
    assert "终结本次执行" in clause
    assert "查封" in clause or "拍卖" in clause


def test_extract_judgment_operative_strips_appeal():
    text = (
        "民事判决书\n判决如下：\n"
        "一、被告向原告偿还借款本金100万元及利息；\n"
        "二、案件受理费由被告负担。\n"
        "如不服本判决，可以在判决书送达之日起十五日内上诉。\n"
        "审判员 张三"
    )
    out = co.extract_judgment_operative(text)
    assert "借款" in out
    assert "如不服" not in out
    assert out.startswith("法院判决")


def test_extract_judgment_operative_mediation():
    text = (
        "民事调解书\n调解协议内容如下：\n"
        "被告分期偿还原告货款50万元。\n"
        "本调解书经双方当事人签收后生效。"
    )
    out = co.extract_judgment_operative(text)
    assert "货款" in out or "偿还" in out


def test_no_forced_zhiben_without_execution_units():
    fields = {"结案小结": "法院判决被告偿还借款。", "审（办）结果": "法院判决被告偿还借款。"}
    pdf_text = "民事判决书……判决被告偿还借款。执行裁定书……终结本次执行程序。"
    units = []
    out = co.ensure_outcome_covers_execution(fields, pdf_text, units=units)
    assert "终结本次" not in out["结案小结"], out["结案小结"]


def test_detect_outcome_warning_fake_zhiben():
    fields = {"结案小结": "法院判决偿还借款。执行过程中，无财产可供执行，终结本次执行程序。"}
    warnings = co.detect_outcome_warnings(fields, units=[], pdf_text="")
    assert any("seq15" in w or "执行文书" in w for w in warnings)


def test_build_outcome_from_units_judgment_only():
    class _U:
        def __init__(self, seq, path="a.pdf", sp=0, ep=0):
            self.catalog_seq = seq
            self.source_path = path
            self.start_page = sp
            self.end_page = ep

    j_text = "民事判决书\n判决如下：\n被告向原告支付货款30万元。\n如不服本判决"
    pages = {"a.pdf": [j_text]}
    units = [_U(14)]
    fields = co.build_outcome_from_units(
        {"结案小结": "错误归纳"},
        units,
        {"a.pdf": [j_text]},
    )
    assert "货款" in fields.get("结案小结", "")
    assert "终结本次" not in fields.get("结案小结", "")


def test_build_outcome_from_units_with_execution():
    class _U:
        def __init__(self, seq, path="a.pdf", sp=0, ep=0):
            self.catalog_seq = seq
            self.source_path = path
            self.start_page = sp
            self.end_page = ep

    j_text = "民事判决书\n判决如下：\n被告向原告偿还借款。\n如不服"
    e_text = "执行裁定书……无其他可供执行财产，终结本次执行程序。"
    units = [_U(14, sp=0, ep=0), _U(15, sp=1, ep=1)]
    page_texts = {"a.pdf": [j_text, e_text]}
    fields = co.build_outcome_from_units({}, units, page_texts)
    out = fields.get("结案小结", "")
    assert "偿还" in out
    assert "终结本次" in out or "执行" in out


def test_apply_outcome_type_none_strips_execution():
    fields = {
        "结案小结": "法院判决被告偿还借款。执行过程中，无财产可供执行，终结本次执行程序。",
    }
    out = co.apply_outcome_type_override(fields, "none")
    assert "终结本次" not in out["结案小结"]
    assert "偿还" in out["结案小结"]


def test_apply_outcome_type_withdraw():
    fields = {"结案小结": "法院判决被告支付货款。"}
    out = co.apply_outcome_type_override(fields, "withdraw")
    assert "撤回" in out["结案小结"]


def test_execution_not_completed_when_text_says_not_fully_performed():
    text = (
        "被执行人未履行完毕生效法律文书确定的义务，法院采取预查封、冻结措施，"
        "未发现其他可供执行财产，裁定终结本次执行程序。"
    )
    assert co.classify_execution_outcome(text) == "zhiben"


def test_long_judgment_reserves_space_for_real_execution_measures():
    judgment = (
        "被告聂彦龙应于本判决发生法律效力之日起十日内向原告某银行偿还"
        "借款本金44496.97元、利息2717.31元、罚息1952.19元及复利270.42元。"
    )
    execution = (
        "执行过程中，法院预查封被执行人共有房产份额，冻结网络支付账户，"
        "通过网络查控未发现其他可供执行财产，并采取限制消费措施，"
        "裁定终结本次执行程序。"
    )
    out = co.synthesize_outcome_narrative(judgment, execution)
    assert out.startswith("法院判决")
    assert "预查封" in out and "冻结" in out and "网络查控" in out
    assert "终结本次执行" in out
    assert "拍卖" not in out
    assert len(out) <= co.CASE_OUTCOME_MAX_LEN


def test_settlement_agreement_does_not_imply_performance():
    out = co.format_execution_for_practice("双方达成执行和解协议。")
    assert "达成执行和解协议" in out
    assert "履行" not in out
    assert "终结" not in out


def test_participation_application_does_not_imply_payment():
    out = co.format_execution_for_practice("申请执行人已提交参与分配申请，尚未受偿。")
    assert "申请" in out and "尚未受偿" in out
    assert "依法受偿" not in out
    assert "财产不足以清偿全部债务" not in out


def test_execution_excerpt_preserves_negative_and_planned_measures():
    out = co.format_execution_for_practice(
        "法院已冻结账户，申请执行人申请拍卖房产但尚未拍卖，裁定终结本次执行程序。",
        "zhiben",
    )
    assert "已冻结账户" in out
    assert "申请拍卖房产但尚未拍卖" in out
    assert "采取冻结、拍卖" not in out
    assert "无其他可供执行财产" not in out


def test_actual_performance_and_receipt_are_preserved():
    source = "双方达成执行和解协议，被执行人已按协议履行，申请执行人已受偿2万元。"
    out = co.format_execution_for_practice(source)
    assert "已按协议履行" in out and "已受偿2万元" in out


def test_bankruptcy_and_withdraw_applications_do_not_imply_court_approval():
    for source in ("申请人提出破产申请，法院尚未受理。", "申请执行人申请撤回执行，法院尚未裁定。"):
        out = co.format_execution_for_practice(source)
        assert "尚未" in out
        assert "裁定准许" not in out
        assert "终结" not in out


def test_special_extraction_retains_negation_before_keyword():
    text = "双方未能达成执行和解协议，仍未履行。"
    excerpt = co.extract_special_execution_blurb(text)
    assert "未能达成" in excerpt
    assert "未能达成" in co.format_execution_for_practice(excerpt)


def test_long_sentence_is_not_cut_before_late_qualification():
    source = "双方达成执行和解协议，" + "约定分期给付事项" * 20 + "，但尚未履行。"
    assert co.format_execution_for_practice(source) == ""
    combined = co.synthesize_outcome_narrative("法院判决被告支付货款。", source)
    assert "达成执行和解" not in combined


def test_ocr_wrapped_negation_before_settlement_is_preserved():
    text = "双方尚未\n达成执行和解协议，仍在协商。"
    excerpt = co.extract_special_execution_blurb(text)
    assert "尚未" in excerpt and "达成执行和解" in excerpt
    assert "尚未" in co.format_execution_for_practice(excerpt)


def test_manual_type_selection_never_fabricates_court_approval():
    out = co.apply_outcome_type_override({"结案小结": "法院判决被告支付货款。"}, "withdraw")
    assert "撤回执行" in out["结案小结"]
    assert "经办人标注" in out["结案小结"]
    assert "待核对" in out["结案小结"]
    assert "裁定准许" not in out["结案小结"]


def test_unit_based_outcome_keeps_distribution_pending():
    from types import SimpleNamespace

    units = [SimpleNamespace(catalog_seq=15, source_path="fictional.pdf", start_page=0, end_page=0)]
    result = co.build_outcome_from_units(
        {}, units, {"fictional.pdf": ["申请执行人申请参与分配，尚未受偿。"]},
    )
    assert "尚未受偿" in result["结案小结"]
    assert "依法受偿" not in result["结案小结"]


def test_ruling_withdrawal_keeps_ruling_through_every_polish_stage():
    from types import SimpleNamespace
    text = "某某人民法院\n民事裁定书\n裁定如下：准许原告虚构甲公司撤诉。\n审判员 虚构乙"
    unit = SimpleNamespace(catalog_seq=14, doc_type="ruling", source_path="fictional.pdf", start_page=0, end_page=0)
    result = co.build_outcome_from_units({}, [unit], {"fictional.pdf":[text]})
    result = co.ensure_outcome_covers_execution(result, text, units=[unit])
    result = co.unify_case_outcome_fields(result)
    assert result["结案小结"] == "法院裁定准许原告虚构甲公司撤诉。"
    assert result["结案小结"] == result["审（办）结果"] == result["审办结果"]
    assert "法院判决" not in result["结案小结"]


def test_ordinary_judgment_still_uses_judgment_prefix():
    text = "民事判决书\n判决如下：被告虚构甲向原告虚构乙支付货款八万元。\n如不服本判决，依法上诉。"
    assert co.extract_judgment_operative(text) == "法院判决被告虚构甲向原告虚构乙支付货款八万元"


def test_ruling_does_not_turn_denied_withdrawal_into_approval():
    text = "民事裁定书\n裁定如下：不准许原告虚构甲公司撤诉。\n如不服本裁定，依法处理。"
    result = co.extract_judgment_operative(text)
    assert result == "法院裁定不准许原告虚构甲公司撤诉"
    assert "法院判决" not in result


def test_withdrawal_request_alone_does_not_infer_ruling_or_approval():
    text = "原告虚构甲公司申请撤诉，法院尚未准许。"
    assert co.extract_judgment_operative(text) == ""
    polished = co._polish_judgment_clause(text)
    assert "法院裁定" not in polished and "尚未准许" in polished


def test_mediation_keeps_identity_after_repeated_polish():
    text = "民事调解书\n调解协议内容如下：被告分期偿还原告货款五万元。\n本调解书经双方签收生效。"
    result = co.extract_judgment_operative(text)
    assert result == "经调解被告分期偿还原告货款五万元"
    assert co.synthesize_outcome_narrative(result, "") == result + "。"
    assert co.polish_outcome_for_practice({"结案小结":result})["结案小结"] == result + "。"


def test_ruling_header_beats_quoted_judgment_and_unit_misclassification():
    text = "民事裁定书\n原审判决如下：被告支付十万元。\n本院裁定如下：撤销原判，发回重审。\n审判员 虚构甲"
    result = co.extract_judgment_operative(text, doc_type="judgment")
    assert result == "法院裁定撤销原判，发回重审"
    assert "支付十万元" not in result


def test_unit_type_supplies_identity_when_marker_is_generic():
    from types import SimpleNamespace
    unit = SimpleNamespace(catalog_seq=14, doc_type="ruling", source_path="fictional.pdf", start_page=0, end_page=0)
    text = "裁判结果如下：不准许原告虚构甲公司撤诉。"
    result = co.build_outcome_from_units({}, [unit], {"fictional.pdf":[text]})
    assert result["结案小结"] == "法院裁定不准许原告虚构甲公司撤诉。"


def test_two_different_decision_units_are_not_relabelled_as_one_kind():
    from types import SimpleNamespace
    units = [SimpleNamespace(catalog_seq=14, doc_type=kind, source_path="fictional.pdf", start_page=i, end_page=i)
             for i,kind in enumerate(("judgment","ruling"))]
    pages = ["民事判决书\n判决如下：被告支付货款一万元。", "民事裁定书\n裁定如下：准许原告虚构甲撤诉。"]
    result = co.build_outcome_from_units({}, units, {"fictional.pdf":pages})
    assert result["结案小结"] == "法院判决被告支付货款一万元。法院裁定准许原告虚构甲撤诉。"


def test_existing_court_ruling_prefix_is_not_changed_to_judgment():
    for text in ("法院裁定不准许撤诉", "本院裁定不准许撤诉", "裁定不准许撤诉"):
        assert co._polish_judgment_clause(text) == "法院裁定不准许撤诉"


def test_strict_outcome_preserves_complete_obligation_and_late_negative_condition():
    value = "本院裁定不准许撤诉。" + "虚构当事人分期偿还本金和利息的约定事项；" * 20 + "但尚未实际履行，不认定已经清偿。"
    raw = {"结案小结": value, "审（办）结果": "", "审办结果": "另一人工核对值", "_provenance": {}}
    result = co.preserve_accepted_outcomes(raw)
    assert result == raw and result is not raw
    assert len(result["结案小结"]) > co.CASE_OUTCOME_MAX_LEN


@pytest.mark.parametrize("raw", [{}, {"结案小结":""}, {"审（办）结果":None}, {"结案小结":"", "审办结果":""}])
def test_strict_missing_outcome_stays_missing_with_a_fixed_review_warning(raw):
    result = co.preserve_accepted_outcomes(raw)
    assert all(result[key] == value for key, value in raw.items())
    assert all(key in raw or key not in result for key in co.OUTCOME_FIELDS)
    assert result["_outcome_warnings"]


@pytest.mark.parametrize("value", [
    "裁定如下：不准许原告虚构甲撤诉。",
    "判决如下：被告虚构乙偿还本金八万元；已实际偿还部分应予扣除。",
    "双方达成分期调解协议，但尚未履行；尚无执行完毕证据。",
])
def test_strict_accepted_result_does_not_add_prefix_or_alias(value):
    result = co.preserve_accepted_outcomes({"审（办）结果":value})
    assert result == {"审（办）结果":value}
