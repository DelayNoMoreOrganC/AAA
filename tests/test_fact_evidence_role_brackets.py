"""Fictional evidence regressions: explicit same-person roles and year glyphs.

No OCR or model call. These tests do not reconstruct any rejected model action.
"""
import pytest

from fact_evidence import validate_fact, validated_fact_field


@pytest.mark.parametrize("connector", ["暨", "即"])
@pytest.mark.parametrize("role", ["被告人", "原告", "被告", "申请人", "被申请人", "上诉人", "被上诉人"])
def test_explicit_same_subject_client_and_procedural_role(connector, role):
    quote = f"委托人{connector}本案{role}：虚构程乙。"
    assert validate_fact("委托人", "虚构程乙", quote, quote)


@pytest.mark.parametrize("page,quote,value", [
    ("被告人：虚构程乙。", "被告人：虚构程乙。", "虚构程乙"),
    ("委托人：虚构程甲。为被告人虚构程乙委托辩护。", "为被告人虚构程乙委托辩护。", "虚构程乙"),
    ("委托人暨本案被告人之父：虚构程甲。", "委托人暨本案被告人之父：虚构程甲。", "虚构程甲"),
    ("委托人暨本案被告人亲属：虚构程甲。", "委托人暨本案被告人亲属：虚构程甲。", "虚构程甲"),
    ("委托人暨本案被告人：虚构程乙之父。", "委托人暨本案被告人：虚构程乙之父。", "虚构程乙"),
    ("委托人暨本案被告人：虚构程乙甲。", "委托人暨本案被告人：虚构程乙甲。", "虚构程乙"),
    ("委托人暨本案被告人：虚构程乙甲。", "委托人暨本案被告人：虚构程乙", "虚构程乙"),
    ("委托人暨本案被告人：虚构程乙、虚构程甲。", "委托人暨本案被告人：虚构程乙", "虚构程乙"),
    ("委托人暨本案被告人：虚构程乙，虚构程甲。", "委托人暨本案被告人：虚构程乙", "虚构程乙"),
    ("委托人暨本案被告人：虚构程乙,虚构程甲。", "委托人暨本案被告人：虚构程乙", "虚构程乙"),
    ("拟列委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
    ("不是委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
    ("对方委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
    ("引用案例：委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
    ("另案资料。委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
    ("填写示例。委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
    ("对方材料。委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
    ("拟列以下人员。委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
    ("第三人声称：委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
    ("对方声称。委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
    ("第三人转述。委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
    ("被告辩称：委托人暨本案被告人：虚构程乙。", "委托人暨本案被告人：虚构程乙。", "虚构程乙"),
])
def test_same_subject_role_does_not_infer_client_or_drop_qualifiers(page, quote, value):
    assert not validate_fact("委托人", value, quote, page)


def outcome(brackets="〔2026〕", tail="010", amount="9000", name="虚构市监"):
    return (f"本院判决如下：撤销{name}罚字{brackets}第{tail}号行政处罚决定；"
            f"被告于本判决生效之日起三十日内向原告返还罚款{amount}元。")


@pytest.mark.parametrize("source_year,quote_year", [
    ("（2026）", "〔2026〕"), ("(2026)", "〔2026〕"),
    ("〔2026〕", "（2026）"), ("〔2026〕", "(2026)"),
])
def test_paired_legal_number_year_glyphs_compare_without_changing_original_value(source_year, quote_year):
    page = "行政判决书。" + outcome(source_year)
    original = outcome(quote_year)
    # Comparison equivalence must not alter the value/quote destined for display.
    candidate = {"field": "结案小结", "value": original, "quote": original}
    before = candidate.copy()
    assert validated_fact_field(**candidate, page_text=page) == "结案小结"
    assert candidate == before
    assert "三十日内" in candidate["value"] and "9000元" in candidate["value"]


@pytest.mark.parametrize("candidate", [
    outcome("〔2025〕"), outcome(tail="011"), outcome(amount="90000"),
    outcome(name="虚构他市监"), outcome("〔2026)"), outcome("(2026〕"),
    outcome("〔20260〕"),
])
def test_year_bracket_equivalence_never_changes_digits_names_or_unpaired_delimiters(candidate):
    assert not validate_fact("结案小结", candidate, candidate, "行政判决书。" + outcome("（2026）"))


@pytest.mark.parametrize("quoted,page", [
    ("案件名称：项目〔2026〕。", "案件名称：项目（2026）。"),
    ("案件名称：虚构客户〔2026〕第010号。", "案件名称：虚构客户（2026）第010号。"),
    ("案件名称：年度计划〔2026〕。", "案件名称：年度计划（2026）。"),
])
def test_bracket_equivalence_is_not_general_name_or_parenthesis_fuzziness(quoted, page):
    value = quoted.split("：", 1)[1].rstrip("。")
    assert not validate_fact("案件或项目名称", value, quoted, page)


@pytest.mark.parametrize("field,label,suffix", [
    ("委托人", "委托人", "公司"), ("当事人", "当事人", "公司"),
    ("案由", "案由", "纠纷"), ("案件或项目名称", "项目名称", "项目"),
    ("收费标准", "收费标准", "计费9000元"),
])
def test_number_like_names_and_unrelated_fields_still_require_original_brackets(field, label, suffix):
    value = "演示罚字〔2026〕第9号" + suffix
    quoted = label + "：" + value + "。"
    page = quoted.replace("〔2026〕", "（2026）")
    assert not validate_fact(field, value, quoted, page)


@pytest.mark.parametrize("suffix", ["公司", "企业", "（集团）有限公司", "行政处罚决定有限公司"])
def test_number_like_company_name_inside_an_outcome_is_not_a_legal_number(suffix):
    value = "本院判决如下：演示罚字〔2026〕第9号" + suffix + "支付9000元。"
    page = value.replace("〔2026〕", "（2026）")
    assert not validate_fact("结案小结", value, value, page)


def test_visual_fact_assembly_retains_exact_source_value_and_quote():
    from types import SimpleNamespace
    from visual_document_workflow import _verify_facts

    original = outcome("〔2026〕")
    page = "行政判决书。" + outcome("（2026）")
    pages = SimpleNamespace(pages={"f1p1": ("fictional-only.pdf", 0)}, read=lambda key: page)
    candidate = {"field": "结案小结", "value": original, "quote": original, "page_id": "f1p1"}
    verified, rejected, duplicates, seen = _verify_facts([candidate], pages, {"f1p1"}, {"f1p1"}, set(), set())
    assert rejected == [] and duplicates == 0 and len(verified) == 1
    field, stored_value, provenance = verified[0]
    assert field == "结案小结" and stored_value == original
    assert provenance["quote"] == original and provenance["value"] == original
    assert provenance["source_path"] == "fictional-only.pdf" and provenance["page"] == 1


@pytest.mark.parametrize("prefix", ["原告诉称：", "引用案例：", "请求法院", "拟作出"])
def test_number_glyph_equivalence_does_not_turn_prayer_or_reference_into_current_outcome(prefix):
    candidate = outcome("〔2026〕")
    assert not validate_fact("结案小结", candidate, candidate, prefix + outcome("（2026）"))


def test_direct_client_and_literal_outcome_keep_existing_behavior():
    assert validate_fact("委托人", "虚构程乙", "委托人：虚构程乙。", "委托人：虚构程乙。")
    value = outcome()
    assert validate_fact("结案小结", value, value, value)
