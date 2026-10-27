"""Fictional, local semantic regressions: no model, file or account access."""
import pytest

from fact_evidence import validate_fact


FIRM = "虚构明序律师事务所"
LAWYER = "虚构律师乙"


@pytest.mark.parametrize("page", [
    f"委托代理合同。受托人：{FIRM}。本所指派{LAWYER}为本案承办律师。",
    f"刑事辩护委托合同。受托人：{FIRM}。本所接受虚构甲的委托，指派{LAWYER}担任本案辩护人。",
    f"辩护词。{FIRM}接受被告人虚构甲委托，指派{LAWYER}担任本案一审辩护人。",
    f"法律服务合同。乙方（受托人）：{FIRM}。乙方指派{LAWYER}为本项目承办律师。",
    f"法律服务合同。受托人（乙方）：{FIRM}。乙方指派{LAWYER}办理本项目。",
    f"本所接受该公司委托，指派{LAWYER}办理本项目。",
    f"本所接受虚构公司聘请，指派{LAWYER}担任本单位法律顾问律师。",
    f"{FIRM}接受聘请，指派{LAWYER}作为本单位顾问律师。",
])
def test_explicit_firm_assignment_accepts_the_named_lawyer(page):
    assert validate_fact("承办律师", LAWYER, page, page)


@pytest.mark.parametrize("page", [
    f"受托人：{FIRM}。",
    f"乙方（受托人）：{FIRM}。",
    f"受托人（乙方）：{FIRM}。",
    f"受聘方：{FIRM}。",
])
def test_explicit_entrusted_firm_label_is_literal_evidence(page):
    assert validate_fact("律师事务所", FIRM, page, page)


@pytest.mark.parametrize("page", [
    f"乙方指派{LAWYER}为本案承办律师。",
    f"乙方：虚构交易公司。乙方指派{LAWYER}为本案承办律师。",
    f"对方受托人：{FIRM}。乙方指派{LAWYER}为本案承办律师。",
    f"受托人（甲方）：{FIRM}。乙方指派{LAWYER}为本案承办律师。",
    f"乙方（受托人）：{FIRM}。乙方：虚构交易公司。乙方指派{LAWYER}为本案承办律师。",
    f"对方委托{FIRM}指派{LAWYER}担任本案辩护人。",
    f"对方律师事务所指派{LAWYER}为本案承办律师。",
    f"本所计划指派{LAWYER}为本案承办律师。",
    f"本所未接受委托，指派{LAWYER}担任本案辩护人。",
    f"参考案例。本所接受虚构甲委托，指派{LAWYER}担任本案辩护人。",
    f"辩护人：{LAWYER}，{FIRM}律师。",
])
def test_missing_opposing_proposed_or_cited_assignment_remains_unaccepted(page):
    assert not validate_fact("承办律师", LAWYER, page, page)


@pytest.mark.parametrize("prefix", ["对方", "拟", "尚未确定", "参考案例。"])
def test_firm_label_cannot_hide_its_qualifier(prefix):
    quote = f"受托人：{FIRM}"
    assert not validate_fact("律师事务所", FIRM, quote, prefix + quote)


@pytest.mark.parametrize("label", ["案件或项目名称", "项目名称", "案件名称"])
def test_explicit_project_name_preserves_literal_name(label):
    value = "虚构星桥采购合同审查项目"
    text = f"{label}：{value}。"
    assert validate_fact("案件或项目名称", value, text, text)
    assert not validate_fact("结案小结", value, text, text)
    assert not validate_fact("案件或项目名称", value, text, "拟" + text)


@pytest.mark.parametrize("value,text", [
    ("6000元", "约定律师费6000元，未附收款凭证。"),
    ("6000元", "约定律师费为人民币6000元，未附收款凭证。"),
    ("5000元", "约定辩护费5000元，未附收款凭证。"),
    ("10000元", "法律顾问费：10000元，收款情况未载明。"),
    ("12000元", "约定顾问费12000元，未附支付凭证。"),
    ("律师费6000元", "双方约定律师费6000元。"),
])
def test_explicit_fee_is_an_agreed_standard_not_payment(value, text):
    assert validate_fact("收费标准", value, text, text)
    assert not validate_fact("已收业务费", value, text, text)
    assert not validate_fact("结案小结", "已支付" + value, text, text)


@pytest.mark.parametrize("text", [
    "采购合同金额6000元。", "律师费另议，采购合同金额6000元。",
    "拟约定律师费6000元。", "尚未约定律师费6000元。",
    "对方律师费6000元。", "参考案例：约定律师费6000元。",
])
def test_trade_price_or_unagreed_fee_does_not_become_our_fee(text):
    assert not validate_fact("收费标准", "6000元", text, text)


def test_assignment_expansion_does_not_infer_filing_date():
    page = f"受托人：{FIRM}。本所指派{LAWYER}为本案承办律师。合同填写日期：2026年5月10日。"
    assert not validate_fact("收案日期", "2026年5月10日", page, page)


@pytest.mark.parametrize("label", ["聘方住所", "聘方联系地址", "联系地址"])
def test_employer_address_requires_explicit_client_identity_on_same_page(label):
    address = "虚构市样例区演示路88号"
    quote = f"{label}：{address}"
    page = "聘方暨委托人：虚构星岚公司。" + quote
    assert validate_fact("地址", address, quote, page)


@pytest.mark.parametrize("page", [
    "聘方名称：虚构星岚公司。联系地址：虚构地址。",
    "本材料由聘方向律所提供，用于年度法律顾问工作。联系地址：虚构地址。",
    "拟聘方暨委托人：虚构星岚公司。联系地址：虚构地址。",
    "对方聘方暨委托人：虚构星岚公司。联系地址：虚构地址。",
    "聘方暨委托人：虚构星岚公司。受聘方联系地址：虚构地址。",
    "聘方暨委托人：虚构星岚公司。对方住所：虚构地址。",
    "聘方暨委托人：虚构星岚公司。律师事务所联系地址：虚构地址。",
    "聘方暨委托人：虚构星岚公司。受聘方：虚构律师事务所。联系地址：虚构地址。",
    "聘方暨委托人：虚构甲公司。聘方暨委托人：虚构乙公司。联系地址：虚构地址。",
])
def test_unbound_or_other_partys_address_is_not_the_client_address(page):
    assert not validate_fact("地址", "虚构地址", "联系地址：虚构地址" if "联系地址" in page else "对方住所：虚构地址", page)


@pytest.mark.parametrize("old_heading", ["原审判决如下", "一审判决如下", "上一次裁定如下", "前次裁决如下"])
def test_prior_operative_result_does_not_replace_current_disposition(old_heading):
    old = "被告支付货款20000元"
    current = "撤销原判，驳回原告全部诉讼请求"
    page = f"民事判决书\n（2026）粤0101民终20号\n{old_heading}：{old}。\n本院判决如下：{current}。"
    assert not validate_fact("结案小结", old, f"{old_heading}：{old}。", page)
    assert not validate_fact("结案小结", old, old, page)
    assert validate_fact("结案小结", current, current, page)


def test_current_revocation_of_prior_judgment_is_not_mistaken_for_a_citation():
    value = "撤销原审判决，驳回原告全部诉讼请求"
    page = "原审判决如下：被告支付20000元。本院判决如下：" + value + "。"
    assert validate_fact("结案小结", value, value, page)
