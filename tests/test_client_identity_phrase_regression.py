"""v9 red-to-green checks for complete identities and independent party roles."""
import pytest

from fact_evidence import validate_fact


COMPANY = "演示星云科技有限公司"


@pytest.mark.parametrize("value,page", [
    (COMPANY + "，诉讼身份为被告", f"委托人：{COMPANY}，诉讼身份为被告。"),
    (COMPANY + "。签署日期：2026年10月1日", f"委托人：{COMPANY}。签署日期：2026年10月1日。"),
    (COMPANY + "（盖章）", f"委托人：{COMPANY}（盖章）。"),
    (COMPANY, f"委托人：{COMPANY}广州分公司。"),
    (COMPANY, f"委托人：{COMPANY}、演示远山公司。"),
    ("演示程乙", "委托人：演示程乙之母演示周丙，为演示程乙委托本所辩护。"),
    ("演示星云", f"{COMPANY}委托本所办理本案。"),
    ("演示程乙", "演示周丙代演示程乙委托本所办理本案。"),
])
def test_client_value_cannot_mix_roles_or_crop_the_actual_subject(value, page):
    assert not validate_fact("委托人", value, page, page)


def test_short_quote_cannot_hide_company_suffix_on_the_source_page():
    quote = f"委托人：{COMPANY}"
    assert not validate_fact("委托人", COMPANY, quote, quote + "广州分公司。")


@pytest.mark.parametrize("value", [COMPANY, COMPANY + "广州分公司", "演示星云（广州）科技有限公司", "演示程乙"])
def test_complete_literal_client_identity_remains_accepted(value):
    page = f"委托人：{value}。"
    assert validate_fact("委托人", value, page, page)


def test_identity_and_role_must_be_separate_values():
    page = f"委托人：{COMPANY}，诉讼身份为被告。"
    assert validate_fact("委托人", COMPANY, page, page)


@pytest.mark.parametrize("annotation", ["（盖章）", "（签字）", "（以下简称甲方）"])
def test_printed_annotation_is_not_part_of_name_or_proof_of_signing(annotation):
    page = f"委托人：{COMPANY}{annotation}。"
    assert validate_fact("委托人", COMPANY, page, page)
    assert not validate_fact("委托人", COMPANY + annotation, page, page)


@pytest.mark.parametrize("suffix", ["（佛山分公司）", "（盖章）广州分公司", "\n广州分公司"])
def test_signature_annotation_rule_cannot_crop_branch_name(suffix):
    page = f"委托人：{COMPANY}{suffix}。"
    assert not validate_fact("委托人", COMPANY, page, page)


def test_complete_parenthesized_branch_name_is_preserved():
    name = COMPANY + "（佛山分公司）"
    page = f"委托人：{name}。"
    assert validate_fact("委托人", name, page, page)


def test_separate_note_label_after_ocr_line_wrap_is_not_a_name_suffix():
    page = f"委托人：{COMPANY}\n材料备注：原件另存。"
    assert validate_fact("委托人", COMPANY, page, page)


def test_separate_filing_date_label_after_line_wrap_is_not_a_name_suffix():
    quote = f"委托人：{COMPANY}"
    page = quote + "\n起诉日期：2026年3月3日。"
    assert validate_fact("委托人", COMPANY, quote, page)


def test_later_filing_date_cannot_hide_a_wrapped_branch_name():
    quote = f"委托人：{COMPANY}"
    page = quote + "\n广州分公司\n起诉日期：2026年3月3日。"
    assert not validate_fact("委托人", COMPANY, quote, page)
    assert validate_fact("委托人", COMPANY + "广州分公司", page, page)


@pytest.mark.parametrize("label", ["委托人", "委托方", "代委托人"])
def test_client_label_alone_does_not_establish_a_party_role(label):
    page = f"{label}：{COMPANY}。"
    assert not validate_fact("当事人", COMPANY, page, page)


@pytest.mark.parametrize("label", ["当事人", "委托人暨本案被告人", "委托人即本案原告"])
def test_explicit_party_or_same_person_two_roles_remains_accepted(label):
    page = f"{label}：演示程乙。"
    assert validate_fact("当事人", "演示程乙", page, page)


def test_explicit_same_person_two_roles_still_supports_client():
    page = "委托人暨本案被告人：演示程乙。"
    assert validate_fact("委托人", "演示程乙", page, page)


@pytest.mark.parametrize("prefix", ["拟", "并非", "对方声称："])
def test_uncertain_same_person_roles_are_not_accepted(prefix):
    page = prefix + "委托人暨本案被告人：演示程乙。"
    assert not validate_fact("当事人", "演示程乙", page, page)
