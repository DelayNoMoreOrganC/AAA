"""Fictional complete sources; distinguish contract scope and documented work."""
from copy import deepcopy
import pytest
from case_timeline import events_for,collect,current_support,summaries
from pdf_doc_locator import DocumentUnit

IDENTITY={'案号':'(2026)粤0999民初71号','执行案号':'','委托人':'虚构甲银行','对方当事人':'虚构乙公司、虚构丙',
          '案由':'金融借款合同纠纷','律师事务所':'虚构明序律师事务所','承办律师':'虚构律师甲'}
CONTRACT=('委托代理合同\n委托人（甲方）：虚构甲银行。受托人（乙方）：虚构明序律师事务所。\n'
          '甲方委托乙方代理其诉虚构乙公司、虚构丙金融借款合同纠纷一审案件。\n'
          '签字盖章区域未提供。')
COURT=('虚构人民法院\n民事判决书\n(2026)粤0999民初71号\n'
       '原告：虚构甲银行，住所地虚构甲地。\n'
       '委托诉讼代理人：虚构律师甲，虚构明序律师事务所律师。\n'
       '被告：虚构乙公司，住所地虚构乙地。\n被告：虚构丙，住所地虚构丙地。\n'
       '本院受理后公开开庭进行审理。原告虚构甲银行的委托诉讼代理人虚构律师甲到庭参加诉讼。\n'
       '判决：被告虚构乙公司偿还借款本金1000元，虚构丙承担连带责任，驳回其余诉讼请求。')


def document(kind,text,page=1):
    return {'kind':kind,'doc_id':str(page),'source_path':'fictional.pdf','start_page':page,'end_page':page,
            'pages':[{'page':page,'quote':text}]}


def synthesize(text=CONTRACT,court=COURT,fields=None,refs=None,conflicts=None):
    fields=deepcopy(fields if fields is not None else IDENTITY)
    refs=deepcopy(refs or {});conflicts=deepcopy(conflicts or [])
    docs=[document('contract',text),document('judgment',court,2)]
    units=[DocumentUnit(i,d['kind'],i,i,source_path='fictional.pdf',confidence=.95) for i,d in enumerate(docs)]
    cache={('fictional.pdf',i+1):d['pages'][0]['quote'] for i,d in enumerate(docs)}
    count=collect(fields,refs,conflicts,page_cache=cache,allowed_sources=set(cache),document_units=units)
    fields['_provenance']=refs
    return fields,refs,count


def test_contract_scope_and_actual_counsel_work_are_separate_from_outcome():
    fields,refs,count=synthesize()
    assert count==2
    full=fields['结案小结'];brief=fields['审（办）结果']
    assert '委托合同载明本案一审代理事项' in full
    assert '法院记载委托方代理律师到庭参加诉讼' in full
    assert '1000元' in full and '驳回其余诉讼请求' in full
    assert '代理事项' not in brief and '1000元' in brief
    assert not any(word in full for word in ('已签署','已付款','已回款','已生效','胜诉','整理证据'))
    assert current_support(refs['结案小结'][-1],fields)


@pytest.mark.parametrize('before,after',[
    ('虚构甲银行','另一银行'),('虚构明序律师事务所','另一律师事务所'),
    ('虚构乙公司、虚构丙','虚构乙公司'),('金融借款合同纠纷','买卖合同纠纷'),
    ('甲方委托乙方','甲方拟委托乙方'),('甲方委托乙方','甲方不委托乙方'),
    ('一审案件','一审或二审案件'),('一审案件','一审案件，执行阶段不包括'),
    ('委托代理合同','委托代理合同草稿'),
])
def test_unrelated_ambiguous_or_planned_engagement_is_not_stated_as_scope(before,after):
    assert events_for(document('contract',CONTRACT.replace(before,after)),IDENTITY)==[]


@pytest.mark.parametrize('before,after',[
    ('到庭参加诉讼','拟到庭参加诉讼'),('到庭参加诉讼','未到庭参加诉讼'),
    ('原告虚构甲银行的委托诉讼代理人虚构律师甲到庭','原告称委托诉讼代理人虚构律师甲到庭'),
    ('原告虚构甲银行的委托诉讼代理人虚构律师甲到庭','被告虚构乙公司的委托诉讼代理人虚构律师甲到庭'),
    ('虚构明序律师事务所律师','另一律师事务所律师'),
    ('委托诉讼代理人：虚构律师甲','委托诉讼代理人：另一律师'),
    ('民初71号','民初72号'),
])
def test_hearing_notice_claim_or_opposing_counsel_does_not_prove_our_work(before,after):
    events=events_for(document('judgment',COURT.replace(before,after)),IDENTITY)
    assert not any(e['code']=='counsel_attendance' for e in events)


@pytest.mark.parametrize('key,value', [('委托人','其他客户'),('律师事务所','其他所'),('承办律师','其他律师'),('案由','其他纠纷')])
def test_identity_change_invalidates_generated_narrative_support(key,value):
    fields,refs,_=synthesize();fields[key]=value
    assert current_support(refs['结案小结'][-1],fields) is None


def test_manual_summary_and_manual_blank_are_not_replaced():
    for value in ('人工核实的小结',''):
        fields,refs,count=synthesize(fields={**IDENTITY,'结案小结':value},refs={'结案小结':[{'method':'human','value':value}]})
        assert fields['结案小结']==value and refs['结案小结']==[{'method':'human','value':value}]


def test_source_order_does_not_put_scope_after_judgment():
    contract=events_for(document('contract',CONTRACT),IDENTITY)
    court=events_for(document('judgment',COURT),IDENTITY)
    result=summaries(court+contract)['结案小结']
    assert result.index('委托合同')<result.index('法院判决')


def test_explicit_combined_stages_are_preserved_not_reduced_to_the_last_stage():
    events=events_for(document('contract',CONTRACT.replace('一审案件','一审和二审案件')),IDENTITY)
    assert events[0]['summary']=='委托合同载明本案一审、二审代理事项。'


def test_incomplete_contract_or_missing_court_page_is_not_used():
    doc=document('contract',CONTRACT);doc['end_page']=2
    assert not events_for(doc,IDENTITY)
    fields=deepcopy(IDENTITY);refs={}
    assert collect(fields,refs,[],page_cache={('fictional.pdf',1):CONTRACT},allowed_sources={('fictional.pdf',1)},
        document_units=[DocumentUnit(0,'contract',0,1,source_path='fictional.pdf',confidence=.99)])==0


def test_conflicting_engagement_scopes_invalidate_old_auto_support():
    fields,refs,_=synthesize()
    texts=[CONTRACT,COURT,CONTRACT.replace('一审案件','二审案件')]
    units=[DocumentUnit(i,kind,i,i,source_path='fictional.pdf',confidence=.95) for i,kind in enumerate(('contract','judgment','contract'))]
    cache={('fictional.pdf',i+1):text for i,text in enumerate(texts)}
    collect(fields,refs,[],page_cache=cache,allowed_sources=set(cache),document_units=units)
    assert current_support(refs['结案小结'][-1],fields) is None


def test_contract_named_counsel_and_compact_court_record_jointly_prove_attendance():
    contract=CONTRACT.replace('签字盖章区域未提供。','指派承办律师：虚构律师甲。签字盖章区域未提供。')
    court=COURT.replace('委托诉讼代理人：虚构律师甲，虚构明序律师事务所律师。\n','')
    court=court.replace('本院受理后公开开庭进行审理。原告虚构甲银行的委托诉讼代理人虚构律师甲到庭参加诉讼。',
        '本院于2026年5月20日公开开庭审理本案，原告委托诉讼代理人虚构律师甲到庭。')
    fields,refs,_=synthesize(text=contract,court=court)
    assert '法院记载委托方代理律师到庭参加诉讼' in fields['结案小结']
    assert current_support(refs['结案小结'][-1],fields)
    for broken in (contract.replace('虚构律师甲','其他律师'),contract.replace('指派承办律师','拟指派承办律师')):
        result,_,_=synthesize(text=broken,court=court)
        assert '代理律师到庭' not in result['结案小结']
    for broken in (court.replace('原告委托诉讼代理人','被告委托诉讼代理人'),court.replace('到庭。','拟到庭。')):
        result,_,_=synthesize(text=contract,court=broken)
        assert '代理律师到庭' not in result['结案小结']
