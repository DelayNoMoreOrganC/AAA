from complaint_brief import summarize
from case_timeline import events_for,summaries
import pytest

def source(facts='双方签订借款合同，被告未按约还款。',heading='事实与理由'):
    return {'pages':[{'source_path':'fiction.pdf','page':1,'quote':
        '民事起诉状\n原告：虚构银行。被告：虚构甲、虚构乙。\n诉请事项：判令被告一清偿贷款本金100000元及利息、罚息、复利（上述数据暂计至某日，此后至实际清偿之日，罚息以本金为基数按合同约定利率计算，复利以逾期利息为基数按合同约定利率计算，具体明细另附）。2、支付律师费。3、被告二承担连带清偿责任。4、承担诉讼费用。\n'+heading+'：'+facts+'此致虚构法院。'}]}

@pytest.mark.parametrize('heading',['事实与理由','事实和理由','事实理由'])
def test_loan_relief_keeps_guarantor_and_facts_despite_long_formula(heading):
    value=summarize(source(heading=heading))
    assert value and '未按约还款' in value and '连带' in value and '律师费' in value and '原告诉称' in value
    assert len(value)<=260 and '判决确定' not in value

def test_complex_conditional_relief_is_not_flattened():
    data=source();data['pages'][0]['quote']=data['pages'][0]['quote'].replace('2、支付律师费','2、不请求支付律师费')
    assert summarize(data) is None

def test_pleading_is_allegation_and_wrong_party_cannot_enter_timeline():
    data=source();doc=dict(kind='complaint',source_path='fiction.pdf',start_page=1,end_page=1,pages=data['pages'])
    events=events_for(doc,{'委托人':'虚构银行','对方当事人':'虚构甲、虚构乙'})
    assert events and events[0]['status']=='allegation' and summaries(events) is None
    assert events_for(doc,{'委托人':'其他客户','对方当事人':'虚构甲'})==[]
