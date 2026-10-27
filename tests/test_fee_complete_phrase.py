"""Complete fee terms are evidence, not due amounts or payment records."""
import pytest

from fact_evidence import validate_fact


HEADER = "委托代理合同\n委托人：虚构甲公司。受托人：虚构乙律师事务所。\n"


@pytest.mark.parametrize("value,quote,page,expected", [
    ("约定律师费6000元", "约定律师费6000元，收款凭证未附。", None, True),
    ("约定顾问费12000元/年", "约定顾问费12000元/年。", None, True),
    ("约定2026年度顾问费12000元", "约定2026年度顾问费12000元。", None, True),
    ("约定代理费按实际回款金额的5%计收，仅实际回款后支付",
     "约定代理费按实际回款金额的5%计收，仅实际回款后支付。", None, True),
    ("约定一审代理费8000元，二审另行约定", "约定一审代理费8000元，二审另行约定。", None, True),
    ("约定律师费6000元，分两期支付，每期3000元", "约定律师费6000元，分两期支付，每期3000元。", None, True),
    ("6000元", "约定律师费6000元。", None, True),
    ("律师费6000元", "约定律师费6000元。", None, True),
    ("约定律师费6000元", "约定律师费6000元。", "对方与其律师约定律师费6000元。", False),
    ("约定律师费6000元", "约定律师费6000元。", "另案合同摘录：约定律师费6000元。", False),
    ("约定采购价款6000元", "约定采购价款6000元。", None, False),
    ("约定诉讼费6000元", "约定诉讼费6000元。", None, False),
    ("未约定律师费6000元", "未约定律师费6000元。", None, False),
    ("拟约定律师费6000元", "拟约定律师费6000元。", None, False),
    ("约定律师费6000元", "约定律师费6000元。", "本合同尚未约定律师费6000元。", False),
    ("约定代理费按回款金额的5%计收", "约定代理费按回款金额的5%计收",
     "约定代理费按回款金额的5%计收，仅实际回款后支付。", False),
    ("12000元", "约定顾问费12000元", "约定顾问费12000元/年。", False),
    ("6000元", "约定律师费6000元", "约定律师费6000元，分两期支付，每期3000元。", False),
    ("约定律师费6000元，已付3000元", "约定律师费6000元，已付3000元。", None, False),
], ids=[
    "whole-agreement", "yearly-rate", "dated-period", "conditional-rate", "stage-boundary",
    "installments", "legacy-amount", "legacy-fee-phrase", "other-party", "other-case",
    "commercial-price", "litigation-cost", "negated-agreement", "proposed-agreement",
    "cropped-negation", "cropped-condition", "cropped-period", "cropped-installments",
    "receipt-not-agreed-standard",
])
def test_complete_fee_evidence(value, quote, page, expected):
    assert validate_fact("收费标准", value, quote, HEADER + (page or quote)) is expected


def test_workflow_preserves_complete_fee_value_and_quote_without_payment_fields():
    from visual_document_workflow import _verify_facts

    value = "约定代理费按实际回款金额的5%计收，仅实际回款后支付"
    quote = value + "。"

    class Pages:
        pages = {"P1": ("synthetic-fee.pdf", 0)}

        def read(self, key):
            assert key == "P1"
            return HEADER + quote

    fact = {"field": "收费标准", "value": value, "quote": quote, "page_id": "P1"}
    verified, rejected, _, _ = _verify_facts([fact], Pages(), {"P1"}, {"P1"}, set(), set())
    assert rejected == []
    assert len(verified) == 1
    field, saved_value, ref = verified[0]
    assert field == "收费标准"
    assert saved_value == value
    assert ref["quote"] == quote
    assert ref["value"] == value
    assert not any("已收" in key or "应收" in key for key in ref)
