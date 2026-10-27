"""Synthetic local-role evidence, with the v9 red failures retained separately.

The first two source/quote pairs retain the frozen civil fixture wording.
Other examples are synthetic contrasts, not model-output/OCR reproductions.
"""
from types import SimpleNamespace

import pytest

from fact_evidence import validate_fact
from visual_document_workflow import _verify_facts


CLIENT = "虚构星禾农业有限公司"
OTHER = "虚构青禾设备有限公司"
FIRM = "虚构明序律师事务所"


@pytest.mark.parametrize("quote,page", [
    (
        f"委托人：{CLIENT}。本公司是本案被告。",
        f"委托代理通知书\n致：{FIRM}。 委托人：{CLIENT}。本公司是本案被告。 "
        f"本公司委托贵所代理与原告{OTHER}之间的买卖合同纠纷一审案件。 "
        "贵所指派虚构律师甲为本案承办律师。案号：（2026）粤0999民初1001号。 "
        "通知日期：2026年4月2日。本通知不附委托代理合同。 委托人盖章栏：空白。",
    ),
    (
        f"委托人：{CLIENT}，诉讼身份为被告。",
        f"授权委托书\n委托人：{CLIENT}，诉讼身份为被告。 "
        f"受托人：{FIRM}指派的虚构律师甲。 "
        "委托事项：代理本公司参加（2026）粤0999民初1001号买卖合同纠纷一审诉讼。 "
        "授权范围：代为提交答辩意见、提交证据及参加庭审；特别授权事项未列明。 "
        "填写日期：2026年4月3日。委托人签字盖章栏：空白。",
    ),
], ids=["same_company_current_defendant", "attached_litigation_role"])
def test_same_local_client_role_keeps_original_value_and_quote(quote, page):
    assert validate_fact("委托人", CLIENT, quote, page)
    assert validate_fact("当事人", CLIENT, quote, page)
    reads = []

    def read(key):
        assert key == "f1p1"
        reads.append(key)
        return page

    pages = SimpleNamespace(pages={"f1p1": ("synthetic-civil.pdf", 0)}, read=read)
    verified, rejected, duplicates, _ = _verify_facts([
        {"field": "当事人", "value": CLIENT, "quote": quote, "page_id": "f1p1"}
    ], pages, {"f1p1"}, {"f1p1"}, set(), set())
    assert verified == [("当事人", CLIENT, {
        "source_path": "synthetic-civil.pdf", "page": 1,
        "quote": quote, "value": CLIENT, "method": "visual_agent_local_evidence",
    })]
    assert not rejected and duplicates == 0 and reads == ["f1p1"]


@pytest.mark.parametrize("page", [
    f"委托人：{CLIENT}。",
    f"委托人：{CLIENT}。本公司代{OTHER}委托辩护，后者是本案被告。",
    f"委托人：{CLIENT}。本公司并非本案被告。",
    f"委托人：{CLIENT}，诉讼身份并非被告。",
    f"参考案例：委托人：{CLIENT}。本公司是本案被告。",
    f"委托人：{CLIENT}。以下为另案摘录：本公司是本案被告。",
    f"如法院追加当事人，委托人：{CLIENT}。本公司是本案被告。",
    f"委托人：{CLIENT}。如法院追加，本公司将成为本案被告。",
    f"委托人：{CLIENT}、{OTHER}。本公司是本案被告。",
    f"委托人：{CLIENT}。{OTHER}是本案被告。",
    f"委托人：{CLIENT}。受托人：{OTHER}。本公司是本案被告。",
    f"委托人：{CLIENT}。\n\n受托方：{OTHER}。\n本公司是本案被告。",
    f"委托人：{CLIENT}。受托人：{FIRM}。本所是本案被告。",
    f"委托人：{CLIENT}。本公司是另案被告。",
    f"委托人：{CLIENT}，诉讼身份为被告的代理人。",
], ids=["client_only", "engagement_for_another", "negated_company_role", "negated_attached_role",
        "reference_header", "other_case_excerpt", "condition_before_identity", "conditional_future_role",
        "multiple_clients", "different_company", "intervening_company", "paragraph_subject_changed",
        "law_firm_self_reference", "other_case_role", "party_representative_not_party"])
def test_client_label_needs_unambiguous_current_party_role(page):
    # Submit the full source quote; do not trim away an adverse qualifier.
    assert not validate_fact("当事人", CLIENT, page, page)


@pytest.mark.parametrize("prefix", ["参考案例：", "拟定方案：", "如法院追加当事人："])
def test_short_quote_cannot_conceal_adverse_context_on_the_original_page(prefix):
    quote = f"委托人：{CLIENT}。本公司是本案被告。"
    assert not validate_fact("当事人", CLIENT, quote, prefix + quote)


def test_existing_explicit_same_person_two_roles_remains_supported():
    page = f"委托人暨本案被告：{CLIENT}。"
    assert validate_fact("委托人", CLIENT, page, page)
    assert validate_fact("当事人", CLIENT, page, page)


def test_role_outside_submitted_quote_is_not_silently_used():
    quote = f"委托人：{CLIENT}。"
    assert not validate_fact("当事人", CLIENT, quote, quote + "本公司是本案被告。")


def test_wrapped_branch_name_cannot_be_cropped_before_role():
    page = f"委托人：{CLIENT}\n广州分公司。本公司是本案被告。"
    assert not validate_fact("当事人", CLIENT, page, page)
    assert validate_fact("当事人", CLIENT + "广州分公司", page, page)


def test_same_local_company_can_also_be_the_explicit_plaintiff():
    page = f"委托人：{OTHER}。本公司是本案原告。"
    assert validate_fact("当事人", OTHER, page, page)


@pytest.mark.parametrize("suffix,include_in_quote", [
    ("上述内容仅为填写示例。", True),
    ("以上身份仅为假设，尚未成为本案被告。", False),
])
def test_postposed_identity_qualification_is_checked_on_original_page(suffix, include_in_quote):
    identity = f"委托人：{CLIENT}。本公司是本案被告。"
    page = identity + suffix
    quote = page if include_in_quote else identity
    assert not validate_fact("当事人", CLIENT, quote, page)


@pytest.mark.parametrize("suffix", [
    "本公司尚未付款。",
    "送达材料尚未签收。",
    "委托人签字盖章栏：空白，合同尚未签署。",
    "上述身份已确认，但尚未支付律师费。",
    "以下付款条款仅为填写示例：如未付款，应补交凭证。",
])
def test_unrelated_payment_signature_or_receipt_qualification_does_not_erase_party(suffix):
    identity = f"委托人：{CLIENT}。本公司是本案被告。"
    assert validate_fact("当事人", CLIENT, identity, identity + suffix)
