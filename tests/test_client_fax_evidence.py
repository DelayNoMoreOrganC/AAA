"""A client fax must not be borrowed from a lawyer, court or opposing party."""
import pytest
from fact_evidence import validated_fact_field
from workstation_agent import FIELDS


@pytest.mark.parametrize('label',['委托人传真','委托方传真','委托人联系传真','委托方传真号码'])
def test_client_label_and_literal_number_are_required(label):
    value='0000-12345678';page=f'{label}：{value}。'
    assert '委托人传真' in FIELDS
    assert validated_fact_field('委托人传真',value,page,page)=='委托人传真'


@pytest.mark.parametrize('label',['传真','受委托人传真','受委托方传真','对方委托人传真','法院传真','律师事务所传真','拟委托人传真'])
def test_other_roles_and_ambiguous_fax_labels_are_rejected_even_with_a_cropped_quote(label):
    value='0000-12345678';page=f'{label}：{value}。'
    quote=page[page.find('委托人'):] if '委托人' in page else page
    assert validated_fact_field('委托人传真',value,quote,page) is None


@pytest.mark.parametrize('value',['未知','123','0000-12345678或0000-99999999','0000-12345678901234567890'])
def test_unknown_short_or_ambiguous_values_are_not_filled(value):
    page=f'委托人传真：{value}。'
    assert validated_fact_field('委托人传真',value,page,page) is None
