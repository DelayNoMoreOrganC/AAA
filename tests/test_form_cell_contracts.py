from types import SimpleNamespace
from form_cell_contracts import writing_rules, source_plan
from form_synthesis import collect_sources
from source_contract_roster import recall_contacts, header_contacts
from fact_evidence import validate_fact


HEADER='''委托代理合同
委托方（甲方）：虚构甲公司
住所：示例路1号
电话：0757-12345678 传真：0757-87654321
受托方（乙方）：虚构律师事务所
住所：示例路2号
电话：0757-22222222 传真：0757-33333333'''


def test_contacts_do_not_cross_contracting_party_boundary():
    contacts=header_contacts(HEADER)
    assert contacts['委托人电话']=='0757-12345678'
    assert validate_fact('委托人传真','0757-87654321',HEADER,HEADER)
    assert not validate_fact('委托人电话','0757-22222222',HEADER,HEADER)
    assert not header_contacts(HEADER.replace('受托方（乙方）','收件人'))


def test_contact_recall_requires_identity_preserves_manual_and_collects_conflict():
    unit=SimpleNamespace(doc_type='contract',confidence=.99,source_path='virtual.pdf',start_page=0)
    args=dict(page_cache={('virtual.pdf',1):HEADER},allowed_sources={('virtual.pdf',1)},document_units=[unit])
    f={'委托人':'其他公司'};assert recall_contacts(f,{},[],**args)==0
    f={'委托人':'虚构甲公司','委托人电话':''};p={'委托人电话':[{'method':'human','value':''}]}
    assert recall_contacts(f,p,[],**args)==1  # Fax only.
    assert f['委托人电话']==''
    f={'委托人':'虚构甲公司','委托人电话':'0757-99999999'};conflicts=[]
    recall_contacts(f,{},conflicts,**args)
    assert f['委托人电话']=='0757-99999999'
    assert conflicts[0]['reason_code']=='client_contact_conflict'


def test_long_document_tail_is_not_starved_and_missing_pages_explicit():
    unit=SimpleNamespace(doc_type='judgment',confidence=.99,source_path='virtual.pdf',start_page=0,end_page=9,doc_id=1)
    cache={('virtual.pdf',n):str(n)*10 for n in range(1,11)}
    rows,coverage=collect_sources([unit],cache,set(cache),max_chars=50)
    assert 10 in {r['page'] for r in rows}
    assert coverage['documents'][0]['missing_or_partial_pages']
    assert coverage['scope']=='available_read_pages_not_full_volume'


def test_business_rules_do_not_conflate_family_and_accused_or_scope_and_work():
    rules=writing_rules('刑事',['案情简介','结案小结'])
    assert '委托人与被追诉人分别列明' in rules['案情简介']['content_components']
    assert '家属' in rules['结案小结']['content_components'][0]
    counsel=writing_rules('顾问',['案情简介'])['案情简介']
    assert any('不写成本期已完成' in c for c in counsel['content_components'])
    plan=source_plan([{'id':'S1','kind':'judgment'},{'id':'S2','kind':'contract'}], 'civil',['案情简介'])
    assert plan['案情简介']['source_ids']==['S2']


def test_contact_cell_keeps_complete_telephone_without_repeated_label():
    from form_drafts import _contact
    fields={'委托人':'虚构公司','地址':'广东省佛山市虚构区示例五路示例大厦','委托人电话':'0757-12345678'}
    text,_,reasons=_contact(fields,set(fields),{})
    assert '0757-12345678' in text and '地址见立案审批表' in text
    assert 'draft_too_long_for_original_cell' not in reasons
