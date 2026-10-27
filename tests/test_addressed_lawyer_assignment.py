"""Same-page assignment evidence only; synthetic text, no model or file access."""
import pytest

from fact_evidence import validate_fact


FIRM = "岭南演示律师事务所"
OTHER_FIRM = "江海演示律师事务所"
CLIENT = "演示甲有限公司"
LAWYER = "陈演示"
ASSIGNMENT = f"贵所指派{LAWYER}为本案承办律师"
TRUSTEE = f"受托人：{FIRM}指派的{LAWYER}"
NOTICE = (f"委托代理通知书。致：{FIRM}。委托人：{CLIENT}。"
          f"本公司委托贵所代理本案。{ASSIGNMENT}。")
POWER = f"授权委托书。委托人：{CLIENT}。{TRUSTEE}。委托事项：代理本公司参加本案诉讼。"


@pytest.mark.parametrize("quote,page", [
    (ASSIGNMENT, NOTICE),
    (NOTICE, NOTICE),
    (TRUSTEE, POWER),
    (POWER, POWER),
    (ASSIGNMENT, NOTICE.replace("指派", "已指派")),
])
def test_explicit_same_page_relationship_accepts_literal_lawyer(quote, page):
    # A quote must still be literal: align the deliberately varied verb.
    if "已指派" in page:
        quote = quote.replace("指派", "已指派")
    assert validate_fact("承办律师", LAWYER, quote, page)


def test_ocr_whitespace_is_allowed_without_rewriting_the_name():
    page = NOTICE.replace(LAWYER, "陈 演 示").replace("。", "。\n")
    assert validate_fact("承办律师", LAWYER, ASSIGNMENT, page)
    assert not validate_fact("承办律师", "陈演", ASSIGNMENT, page)


@pytest.mark.parametrize("page", [
    ASSIGNMENT + "。",
    NOTICE.replace(f"致：{FIRM}。", ""),
    NOTICE.replace(f"委托人：{CLIENT}。", ""),
    NOTICE.replace("本公司委托贵所代理本案。", ""),
    NOTICE.replace("本公司委托贵所代理本案。", "本公司拟请贵所代理本案。"),
    NOTICE.replace("本公司委托贵所代理本案。", "对方称本公司委托贵所代理本案。"),
    NOTICE.replace(f"致：{FIRM}。", f"致：{FIRM}。受托人：{OTHER_FIRM}。"),
    NOTICE.replace(f"委托人：{CLIENT}。", f"委托人：{CLIENT}。委托人：演示乙有限公司。"),
    NOTICE.replace(ASSIGNMENT, "拟请" + ASSIGNMENT),
    NOTICE.replace(ASSIGNMENT, "尚未由" + ASSIGNMENT),
    NOTICE.replace(ASSIGNMENT, "并非由" + ASSIGNMENT),
    NOTICE.replace(ASSIGNMENT, "希望" + ASSIGNMENT),
    NOTICE.replace(ASSIGNMENT, "对方称：" + ASSIGNMENT),
    NOTICE.replace(ASSIGNMENT, "第三人陈述：" + ASSIGNMENT),
    NOTICE.replace(ASSIGNMENT, "仅名义上由" + ASSIGNMENT),
    "填写示例。" + NOTICE,
    "另案材料摘录。" + NOTICE,
    "第三人提交的材料。" + NOTICE,
    "对方声称。" + NOTICE,
])
def test_addressing_does_not_bypass_missing_binding_or_qualifiers(page):
    # The submitted quote omits the adverse prefix; the full source still wins.
    assert not validate_fact("承办律师", LAWYER, ASSIGNMENT, page)


@pytest.mark.parametrize("page", [
    POWER.replace("授权委托书。", "证据摘录。"),
    POWER.replace(f"委托人：{CLIENT}。", ""),
    POWER.replace(f"委托人：{CLIENT}。", f"对方委托人：{CLIENT}。"),
    POWER.replace(f"委托人：{CLIENT}。", f"委托人：{CLIENT}。委托人：演示乙有限公司。"),
    POWER.replace(TRUSTEE, "拟定" + TRUSTEE),
    POWER.replace(TRUSTEE, "名义" + TRUSTEE),
    POWER.replace(TRUSTEE, "对方" + TRUSTEE),
    POWER.replace(TRUSTEE, "引用：" + TRUSTEE),
    POWER.replace(TRUSTEE, f"受托人：拟请{FIRM}指派的{LAWYER}"),
    POWER.replace(TRUSTEE, f"受托人：对方{FIRM}指派的{LAWYER}"),
    POWER.replace(TRUSTEE, TRUSTEE + f"。受托人：{OTHER_FIRM}指派的李演示"),
    POWER.replace(TRUSTEE, f"致：{OTHER_FIRM}。" + TRUSTEE),
    "参考模板。" + POWER,
    "第三人转述。" + POWER,
])
def test_named_trustee_is_not_any_nearby_law_firm_or_quoted_assignment(page):
    assert not validate_fact("承办律师", LAWYER, TRUSTEE, page)


@pytest.mark.parametrize("prefix", ["拟请", "对方", "名义", "并非", "希望"])
def test_qualifier_inside_trustee_label_is_not_part_of_the_firm_name(prefix):
    quote = f"受托人：{prefix}{FIRM}指派的{LAWYER}"
    assert not validate_fact("承办律师", LAWYER, quote, POWER.replace(TRUSTEE, quote))


@pytest.mark.parametrize("suffix", ["上述指派尚未生效。", "本次指派不存在。", "该指派已撤销。"])
def test_explicit_invalidation_is_not_hidden_by_a_short_quote(suffix):
    assert not validate_fact("承办律师", LAWYER, ASSIGNMENT, NOTICE + suffix)
    assert not validate_fact("承办律师", LAWYER, TRUSTEE, POWER + suffix)


@pytest.mark.parametrize("replacement", [
    f"受托人：{FIRM}拟指派的{LAWYER}",
    f"受托人：{FIRM}未指派的{LAWYER}",
    f"受托人：{FIRM}指派的{LAWYER}助理",
    f"受托人：{FIRM}指派的{LAWYER}某",
    f"受托人：{FIRM}指派的{LAWYER}、李演示",
])
def test_no_negation_name_substring_or_partial_lawyer_list(replacement):
    page = POWER.replace(TRUSTEE, replacement)
    assert not validate_fact("承办律师", LAWYER, replacement, page)


@pytest.mark.parametrize("suffix", ["助理", "某", "、李演示"])
def test_short_quote_cannot_hide_trustee_name_suffix_in_the_original_page(suffix):
    page = POWER.replace(TRUSTEE, TRUSTEE + suffix)
    assert not validate_fact("承办律师", LAWYER, TRUSTEE, page)


def test_short_quote_cannot_hide_assistant_role_in_the_original_page():
    page = NOTICE.replace(ASSIGNMENT, ASSIGNMENT + "助理")
    assert not validate_fact("承办律师", LAWYER, ASSIGNMENT, page)


@pytest.mark.parametrize("candidate", [LAWYER + "助理", LAWYER + "实习律师", "待定", "未指定"])
def test_non_lawyer_or_placeholder_is_not_accepted_as_a_complete_candidate(candidate):
    quote = TRUSTEE.replace(LAWYER, candidate)
    assert not validate_fact("承办律师", candidate, quote, POWER.replace(LAWYER, candidate))


def test_one_page_cannot_borrow_another_pages_binding():
    assert not validate_fact("承办律师", LAWYER, ASSIGNMENT, ASSIGNMENT)
    assert not validate_fact("承办律师", LAWYER, TRUSTEE, TRUSTEE)


@pytest.mark.parametrize("page,quote", [(NOTICE, ASSIGNMENT), (POWER, TRUSTEE)])
def test_new_assignment_does_not_prove_date_payment_or_signature(page, quote):
    page += "填写日期：2026年5月10日。委托人签字盖章栏：空白。约定律师费6000元。"
    assert validate_fact("承办律师", LAWYER, quote, page)
    assert not validate_fact("收案日期", "2026年5月10日", page, page)
    assert not validate_fact("已收业务费", "6000元", page, page)
    assert not validate_fact("结案小结", "已签署委托合同", page, page)
