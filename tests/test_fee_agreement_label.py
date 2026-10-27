import pytest
from fact_evidence import validate_fact

TERMS = '一审基础律师费5000元；另按实际收回款项的2%收取风险代理费。基础费于合同订立后十日内支付，风险费于实际回款后结算。'
PAGE = '委托代理合同\n收费约定：' + TERMS + '\n合同签订日期：2026年1月5日。'


def test_complete_agreement_keeps_stage_rate_basis_and_payment_conditions():
    assert validate_fact('收费标准', TERMS, '收费约定：' + TERMS, PAGE)
    assert not validate_fact('实收律师费', '5000元', '收费约定：' + TERMS, PAGE)


@pytest.mark.parametrize('value', ['5000元', '5000元；另按实际收回款项的2%收取风险代理费。', '2%'])
def test_cropped_agreement_is_not_a_complete_fee_standard(value):
    assert not validate_fact('收费标准', value, '收费约定：' + TERMS, PAGE)


@pytest.mark.parametrize('prefix', ['拟', '未约定', '对方', '原告诉称：'])
def test_alias_does_not_remove_proposal_negation_opposing_role_or_allegation(prefix):
    page = PAGE.replace('收费约定：', prefix + '收费约定：')
    assert not validate_fact('收费标准', TERMS, '收费约定：' + TERMS, page)
