import pytest
from fact_evidence import validate_fact
from fee_display import summarize

TERMS='基础代理费5000元，按实际回款金额另收2%。'
PAGE='委托代理合同\n委托人：虚构甲。受托人：虚构律师事务所。\n'+TERMS

def test_full_base_and_recovery_terms_are_supported_and_fit_display():
    assert validate_fact('收费标准',TERMS,TERMS,PAGE)
    assert summarize(TERMS)['value']=='基础5000元\n回款2%详合同'

def test_following_contract_date_is_not_part_of_fee_period():
    page=PAGE+'合同签订日期：2026年1月5日。'
    assert validate_fact('收费标准',TERMS,TERMS,page)

@pytest.mark.parametrize('value', ['5000元','基础代理费5000元','2%','按实际回款金额另收2%'])
def test_one_piece_cannot_replace_complete_fee(value):
    assert not validate_fact('收费标准',value,value,PAGE)

@pytest.mark.parametrize('lead', ['拟约定','若胜诉，','原告主张','对方要求','另案约定'])
def test_proposals_conditions_and_other_party_terms_are_not_agreed_fee(lead):
    assert not validate_fact('收费标准',TERMS,TERMS,PAGE.replace(TERMS,lead+TERMS))

@pytest.mark.parametrize('header', ['民事判决书','借款合同','民事起诉状'])
def test_unlabelled_full_sentence_needs_engagement_document(header):
    assert not validate_fact('收费标准',TERMS,TERMS,PAGE.replace('委托代理合同',header))

@pytest.mark.parametrize('tail', ['但收费总额不超过8000元。','若未收回款项则减免基础费。','另加差旅费。'])
def test_display_does_not_hide_additional_fee_conditions(tail):
    assert summarize(TERMS+tail) is None
    assert not validate_fact('收费标准',TERMS,TERMS,PAGE+tail)

def test_actual_payment_is_not_a_fee_schedule():
    value='已收基础代理费5000元，按实际回款金额另收2%。'
    assert not validate_fact('收费标准',value,value,PAGE.replace(TERMS,value))
