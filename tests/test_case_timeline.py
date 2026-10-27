"""Fictional procedural documents; no cloud calls or customer fixtures."""
from copy import deepcopy
import pytest
from case_timeline import events_for, collect, current_support, resolved_conflict_supported
from pdf_doc_locator import DocumentUnit

NUMBER='(2026)粤0604执123号'

def document(body, page=1, title='执行裁定书', suffix=''):
    return dict(kind='execution',doc_id=str(page),source_path='fictional.pdf',start_page=page,end_page=page,
        pages=[dict(page=page,quote=f'虚构区人民法院\n{title}\n{NUMBER}{suffix}\n{body}')])

def test_suffixed_orders_are_distinct_events_not_conflicting_outcomes():
    order=document('本院裁定如下：拍卖被执行人名下房产。',suffix='之一')
    ending=document(f'本院裁定如下：本院{NUMBER}案终结本次执行程序。',2,suffix='之三')
    fields={'执行案号':NUMBER}; provenance={}; conflicts=[]
    docs=[order,ending]
    units=[DocumentUnit(i,'execution',d['start_page']-1,d['end_page']-1,confidence=.95,
        catalog_seq=15,source_path=d['source_path']) for i,d in enumerate(docs)]
    cache={(d['source_path'],d['start_page']):d['pages'][0]['quote'] for d in docs}
    assert collect(fields,provenance,conflicts,page_cache=cache,allowed_sources=set(cache),document_units=units)==2
    assert '裁定拍卖' in fields['结案小结']
    assert '已拍卖' not in fields['结案小结']
    assert '终结本次' in fields['审（办）结果']
    assert fields['审（办）结果'] != fields['结案小结']
    ref=provenance['结案小结'][-1]
    assert current_support(ref,fields)
    changed=deepcopy(fields);changed['执行案号']='(2026)粤0604执999号'
    assert current_support(ref,changed) is None
    changed=deepcopy(fields);changed['_case_timeline']['documents'][0]['pages'][0]['quote']+='更改'
    assert current_support(ref,changed) is None

@pytest.mark.parametrize('text',['本院拟拍卖财产。','本院未拍卖成交。','申请人称本院已拍卖。','若本院拍卖成交，可支付申请人。'])
def test_notices_do_not_turn_plans_negations_or_claims_into_completed_sales(text):
    doc=document(text,title='执行情况告知书')
    assert not any(e['code']=='auction_completed' for e in events_for(doc,{'执行案号':NUMBER}))

def test_actual_sale_supported_by_court_accounting_statement():
    doc=document('本院依法拍卖被执行人名下房产得款1000元。',title='执行情况告知书')
    assert [e['code'] for e in events_for(doc,{'执行案号':NUMBER})]==['auction_completed']
    assert events_for(doc,{'执行案号':'(2026)粤0604执999号'})==[]

def test_manual_blank_alias_is_not_overwritten():
    d=document('本院裁定如下：终结本次执行程序。')
    unit=DocumentUnit(0,'execution',0,0,confidence=.95,catalog_seq=15,source_path='fictional.pdf')
    fields={'执行案号':NUMBER,'审办结果':''};refs={'审办结果':[{'method':'human','value':''}]}
    cache={('fictional.pdf',1):d['pages'][0]['quote']}
    collect(fields,refs,[],page_cache=cache,allowed_sources=set(cache),document_units=[unit])
    assert '审（办）结果' not in fields
    assert fields['审办结果']==''

def test_bogus_resolved_conflict_cannot_disappear():
    assert not resolved_conflict_supported({'resolution_method':'case_timeline_summary','resolved':True},{})


def test_judgment_and_execution_synthesis_requires_each_conflict_value_in_its_original_source():
    trial='(2026)粤0604民初123号'
    docs=[dict(kind='judgment',source_path='fictional.pdf',start_page=1,end_page=1,
               pages=[dict(page=1,quote=f'虚构区人民法院\n民事判决书\n{trial}\n本院受理后公开开庭进行审理。判决如下：被告偿还借款本金1000元。')]),
          document('本院裁定如下：终结本次执行程序。',2)]
    fields={'案号':trial,'执行案号':NUMBER}
    values=['被告偿还借款本金1000元。','终结本次执行程序。']
    provenance={'结案小结':[dict(method='visual_agent_local_evidence',value=v,quote=v,source_path='fictional.pdf',page=i+1) for i,v in enumerate(values)]}
    conflicts=[dict(field='结案小结',values=values)]
    units=[DocumentUnit(i,d['kind'],i,i,confidence=.95,catalog_seq=14+i,source_path='fictional.pdf') for i,d in enumerate(docs)]
    cache={('fictional.pdf',i+1):d['pages'][0]['quote'] for i,d in enumerate(docs)}
    assert collect(fields,provenance,conflicts,page_cache=cache,allowed_sources=set(cache),document_units=units)==2
    fields['_provenance']=provenance
    assert '开庭' in fields['结案小结'] and '终结本次' in fields['结案小结']
    assert '已清偿' not in fields['审（办）结果'] and resolved_conflict_supported(conflicts[0],fields)
    changed=deepcopy(fields);changed['_provenance']['结案小结'][0]['page']=2
    assert not resolved_conflict_supported(conflicts[0],changed)
