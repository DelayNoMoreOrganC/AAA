"""Do not lose supported pleading facts when punctuation occurs inside clauses."""
import pytest
from complaint_brief import summarize
from case_timeline import events_for


def source(facts, requests):
    text=('民事起诉状\n原告：虚构银行。被告：虚构甲、虚构乙。\n'
          '诉讼请求：'+requests+'\n事实与理由：'+facts+'此致虚构法院。')
    return {'pages':[dict(source_path='fiction.pdf',page=1,quote=text)]}


FACTS='双方订立借款合同（本金1000元；期限一年），原告主张已放款。被告未按约还款，乙提供保证。'
REQUESTS='一、判令甲偿还本金1000元（其中500元到期；其余500元以到期为限）。二、乙仅在保证范围内承担责任。'


def test_balanced_internal_semicolons_preserve_all_claims_and_qualifiers():
    value=summarize(source(FACTS,REQUESTS))
    assert value and FACTS in value
    assert '其余500元以到期为限' in value and '乙仅在保证范围内承担责任' in value
    assert '诉请摘录' in value and len(value)<=260


@pytest.mark.parametrize('left,right',[('（','）'),('(',')'),('【','】')])
def test_nested_clause_and_decimal_amount_are_not_cut(left,right):
    facts=f'双方订立合同{left}本金1000.50元；另附【还款约定；保证条款】{right}。甲未还款。'
    value=summarize(source(facts,'判令甲偿还本金1000.50元；乙承担连带责任。'))
    assert value and facts in value and '1000.50元' in value


def test_unclosed_bracket_is_not_accepted_as_complete_summary():
    assert summarize(source(FACTS.replace('）',''),REQUESTS)) is None


def test_same_source_facts_reach_case_timeline_without_becoming_court_findings():
    data=source(FACTS,REQUESTS)
    document=dict(kind='complaint',source_path='fiction.pdf',start_page=1,end_page=1,pages=data['pages'])
    events=events_for(document,{'委托人':'虚构银行','对方当事人':'虚构甲、虚构乙'})
    assert len(events)==1 and FACTS in events[0]['summary']
    assert events[0]['status']=='allegation'


def test_fixed_four_item_loan_pattern_must_not_erase_negative_relief():
    requests=('判令被告偿还借款本金1000元及利息、罚息、复利（计算方式为按合同约定计算，'
              '暂计至起诉日，此后按实际未清偿本金计算至清偿之日；上述金额应以本案明细为准），但不请求复利；'
              '2、判令被告向原告支付律师费100元；'
              '3、判令原告对被告提供抵押的房屋处置款享有优先受偿权；'
              '4、判令被告承担本案全部诉讼费用。')
    value=summarize(source('原告主张已放款，被告未按约还款。',requests))
    assert value is None or '不请求复利' in value
