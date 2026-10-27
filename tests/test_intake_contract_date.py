from copy import deepcopy
import pytest
from intake_contract_date import FIELD, KEY, dates, recall, current_support, presentation
from pdf_doc_locator import DocumentUnit

PAGE='委托代理合同\n委托人（甲方）：虚构银行。受托人：虚构律师事务所。\n代理虚构银行诉虚构甲公司金融借款合同纠纷。律师费5000元。\n合同载明签订日期：2026年1月5日。\n甲乙双方签字盖章区域未提供。'


def run(page=PAGE,fields=None,refs=None,extra_pages=()):
    fields=deepcopy(fields if fields is not None else {'委托人':'虚构银行','对方当事人':'虚构甲公司','案由':'金融借款合同纠纷'})
    refs=deepcopy(refs or {});conflicts=[]
    cache={('contract.pdf',i+1):p for i,p in enumerate([page,*extra_pages])}
    units=[DocumentUnit(0,'contract',0,len(cache)-1,source_path='contract.pdf',confidence=.96)]
    count=recall(fields,refs,conflicts,page_cache=cache,allowed_sources=set(cache),document_units=units)
    fields.update(_provenance=refs,_field_conflicts=conflicts)
    return fields,count,cache,units


def test_explicit_contract_date_is_separate_default_with_source_and_marker():
    fields,count,_,_=run()
    assert count==1 and fields[FIELD]=='2026年1月5日' and '收案日期' not in fields
    assert current_support(fields['_provenance'][FIELD][0],fields)==[]
    assert '按合同日期默认' in presentation(fields)['value']
    assert '不证明已签署' in presentation(fields)['note']


@pytest.mark.parametrize('statement',['本合同于2026年1月5日签订。','双方于2026-1-5签订本合同。','合同签订时间：2026/1/5。'])
def test_explicit_narrative_and_alternate_date_format(statement):
    fields,count,_,_=run(PAGE.replace('合同载明签订日期：2026年1月5日。',statement))
    assert count==1 and fields[FIELD]=='2026年1月5日'


@pytest.mark.parametrize('label',['合同签订\n日期','合同载明签\n订时间','合 同 签 署 日 期'])
def test_wrapped_date_label_preserves_exact_source_and_default_only(label):
    page=PAGE.replace('合同载明签订日期',label)
    fields,count,_,_=run(page)
    assert count==1 and fields[FIELD]=='2026年1月5日'
    assert fields['_provenance'][FIELD][0]['quote']==page
    assert current_support(fields['_provenance'][FIELD][0],fields)==[]
    assert '收案日期' not in fields


@pytest.mark.parametrize('prefix',['预计','计划','拟','借款','贷款','担保','抵押','质押','生效'])
def test_wrapping_does_not_drop_date_qualifier(prefix):
    page=PAGE.replace('合同载明签订日期',prefix+'\n合同签订\n日期')
    fields,count,_,_=run(page)
    assert not count and FIELD not in fields


@pytest.mark.parametrize('replacement',[
    '拟签订日期：2026年1月5日。','预计签约日期：2026年1月5日。',
    '合同填写日期：2026年1月5日。','法院立案日期：2026年1月5日。',
    '合同生效日期：2026年1月5日。','借款合同签订日期：2026年1月5日。',
    '签订日期：2026年2月30日。','签订日期：2026年1月5日或6日。',
    '签订日期：2026年1月5日至6日。','签订日期：2026年1月5日（暂定）。',
    '合同签订日期：2026年1月5日。尚未签署。',
    '合同签订日期：2026年1月5日。本件为合同草稿。',
    '签订日期：____年__月__日。'])
def test_non_dates_proposals_unsigned_and_ambiguity_do_not_become_defaults(replacement):
    fields,count,_,_=run(PAGE.replace('合同载明签订日期：2026年1月5日。',replacement))
    assert count==0 and FIELD not in fields


def test_continuation_date_keeps_header_and_date_page_sources():
    fields,count,_,_=run(PAGE.replace('合同载明签订日期：2026年1月5日。',''),extra_pages=['签订日期：2026-01-05。'])
    assert count==1
    ref=fields['_provenance'][FIELD][0]
    assert ref['page']==2 and [p['page'] for p in current_support(ref,fields)]==[1]


def test_two_distinct_contract_dates_raise_conflict_instead_of_first_wins():
    fields,count,_,_=run(extra_pages=['签订日期：2026年1月6日。'])
    assert not count and FIELD not in fields
    assert fields['_field_conflicts'][0]['values']==['2026年1月5日','2026年1月6日']


@pytest.mark.parametrize('key',['委托人','对方当事人','案由'])
def test_unrelated_engagement_cannot_default_this_case(key):
    fields={'委托人':'虚构银行','对方当事人':'虚构甲公司','案由':'金融借款合同纠纷',key:'其他主体或案件'}
    assert run(fields=fields)[1]==0


@pytest.mark.parametrize('key',[FIELD,'收案日期'])
@pytest.mark.parametrize('value',['','2025年2月1日'])
def test_human_value_and_blank_win_including_legacy_field(key,value):
    fields={'委托人':'虚构银行','对方当事人':'虚构甲公司','案由':'金融借款合同纠纷',key:value}
    actual,count,_,_=run(fields=fields,refs={key:[{'method':'human','value':value}]})
    assert not count and actual[key]==value


def test_recall_idempotent_and_source_loss_invalidates_default_binding():
    fields,_,cache,units=run()
    ref=deepcopy(fields['_provenance'][FIELD][0])
    assert recall(fields,fields['_provenance'],fields['_field_conflicts'],page_cache=cache,allowed_sources=set(cache),document_units=units)==0
    assert fields['_provenance'][FIELD]==[ref] and current_support(ref,fields) is not None
    recall(fields,fields['_provenance'],fields['_field_conflicts'],page_cache={},allowed_sources=set(),document_units=units)
    assert current_support(ref,fields) is None


@pytest.mark.parametrize('mutation',['client','quote','scope','conflict'])
def test_stale_binding_rejected(mutation):
    fields,*_=run();ref=fields['_provenance'][FIELD][0]
    if mutation=='client':fields['委托人']='其他银行'
    if mutation=='quote':fields[KEY]['documents'][0]['pages'][0]['quote']='签订日期：2026年1月5日。'
    if mutation=='scope':ref['source_path']='elsewhere.pdf'
    if mutation=='conflict':fields['_field_conflicts']=[{'field':FIELD}]
    assert current_support(ref,fields) is None and presentation(fields) is None


def test_missing_date_has_one_form_reminder_but_retained_original_or_manual_blank_does_not():
    from form_drafts import derive_form_drafts, draft_review_summary
    fields,_,_,units=run(PAGE.replace('合同载明签订日期：2026年1月5日。',''))
    fields['案件类别']='民事'
    draft=derive_form_drafts(fields,units,source_manifest=[])
    assert draft_review_summary(draft)['insufficient_fields'].count(FIELD)==1
    draft['_original_forms']={'立案审批表':[{'source_path':'original.pdf','page':1}]}
    assert FIELD not in draft_review_summary(draft)['insufficient_fields']
    fields[FIELD]='';fields['_provenance'][FIELD]=[{'method':'human','value':''}]
    assert FIELD not in draft_review_summary(derive_form_drafts(fields,units,source_manifest=[]))['insufficient_fields']
