from copy import deepcopy
import pytest
from engagement_intake import evaluate, recall, current_support, KEY
from types import SimpleNamespace as NS


def source():
    pages=[
        'ABCD202601010001\n委托代理合同\n（适用风险代理）\n委托人（甲方）：虚构银行。',
        '鉴于甲方与虚构丙等11户的需要。\n第四条律师代理的方式、费用、支付条件和方式\n'
        '一、本合同代理方式为风险代理，并按下列第1项执行：\n1.甲方不支付基础代理费。\n'
        '二、甲方按下列第4点向乙方计付律师代理费用：\n（4）其他付款条件：（1）无基础费用。'
        '（2）现金回款计费2.5%；调解另按1%；以物抵债另有约定。\n第五条其他事项',
        '合同各方签章：\n甲方（盖章）：\n2026年1月5日\n乙方（盖章）：\n2026年1月5日\n附件：清单',
    ]
    pleading={'doc_id':'1','pages':[{'source_path':'pleading.pdf','page':1,'quote':
        '民事起诉状\n原告：虚构银行。\n被告：虚构甲。\n诉讼请求：判令被告在继承虚构丙遗产的范围内偿还借款。\n事实与理由：借款未还。'}]}
    return dict(pages=[dict(source_path='contract.pdf',page=i+1,quote=t) for i,t in enumerate(pages)],pleadings=pleading,
                scope={'contract.pdf':3,'pleading.pdf':1})


def test_selected_complex_terms_are_not_flattened_to_one_rate_and_date_is_not_filing():
    s=source();result=evaluate(s,'虚构银行')
    assert result['收费标准']['value']=='无基础费\n风险费依合同'
    assert '2.5%' in result['收费标准']['terms'] and '1%' in result['收费标准']['terms']
    assert result['立案审批日期']['value']=='2026年1月5日'
    assert '不证明' in result['立案审批日期']['note']


@pytest.mark.parametrize('change', ['other_client','other_subject','quoted_heading','partial_pages','different_subjects'])
def test_unknown_or_other_case_engagement_cannot_supply_intake_defaults(change):
    s=source();client='虚构银行'
    if change=='other_client':client='虚构另一银行'
    if change=='other_subject':s['pages'][1]['quote']=s['pages'][1]['quote'].replace('虚构丙','虚构丁')
    if change=='quoted_heading':s['pages'][0]['quote']='证据清单\n'+s['pages'][0]['quote']
    if change=='partial_pages':s['pages'].pop(1)
    if change=='different_subjects':
        second=deepcopy(s['pleadings']);second['pages'][0].update(source_path='other.pdf',quote=second['pages'][0]['quote'].replace('虚构丙','虚构丁'))
        s['pleadings']={**s['pleadings'],'documents':[deepcopy(s['pleadings']),second]}
    assert evaluate(s,client) is None


@pytest.mark.parametrize('signature', ['甲方（盖章）：2026年1月5日\n乙方（盖章）：2026年1月6日',
    '甲方（盖章）：2026年1月5日','甲方（盖章）：预计2026年1月5日\n乙方（盖章）：2026年1月5日'])
def test_signature_dates_must_be_present_and_agree(signature):
    s=source();s['pages'][2]['quote']='合同各方签章：\n'+signature
    assert '立案审批日期' not in evaluate(s,'虚构银行')


def test_unselected_fee_option_is_not_accepted():
    s=source();s['pages'][1]['quote']=s['pages'][1]['quote'].replace('按下列第1项','按下列第2项')
    assert '收费标准' not in evaluate(s,'虚构银行')


def prepared(manual=()):
    s=source();fields={'委托人':'虚构银行','_pleading_parties_source':s['pleadings']}
    cache={(p['source_path'],p['page']):p['quote'] for p in s['pages']+s['pleadings']['pages']}
    refs={};conflicts=[];units=[NS(doc_type='contract',source_path='contract.pdf',start_page=0,end_page=2)]
    recall(fields,refs,conflicts,page_cache=cache,allowed_sources=set(cache),document_units=units,manual_fields=manual,method='local_agent')
    fields.update(_provenance=refs,_field_conflicts=conflicts)
    return fields


def test_human_blanks_and_changed_bundle_remain_protected():
    assert '收费标准' not in prepared({'收费标准':''})
    f=prepared();ref=f['_provenance']['收费标准'][0]
    assert len(current_support(ref,f))==4
    f[KEY]['pages'][1]['quote']+='变更'
    assert current_support(ref,f) is None
