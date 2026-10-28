from copy import deepcopy
from types import SimpleNamespace as NS
import hashlib
from case_fact_ledger import build, civil_candidates, public
from form_synthesis import generate, current_support, collect_sources, validate_candidate

def sources():
    texts=[('complaint','民事起诉状\n原告：虚构银行，住所甲地。\n被告：虚构乙，男。\n诉讼请求：判令被告向原告清偿贷款本金100.9元及利息、罚息、复利；享有优先受偿权；本案全部诉讼费用。\n事实与理由：个人房屋按揭贷款合同。借款本金：500元。被告逾期还款时间：2024年1月20日。尚欠本金：100.09元。原告曾多次向被告催收，但被告拒不偿还。'),
      ('judgment','民事判决书\n（2025）粤0101民初1号\n原告虚构银行诉被告虚构乙。判决如下：被告偿还借款本金100.09元、利息、罚息、复利。原告享有优先受偿权；三、驳回原告虚构银行其他诉讼请求。\n二〇二五年三月十八日'),
      ('execution','执行裁定书\n（2025）粤0101执2号\n虚构银行与虚构乙，执行依据（2025）粤0101民初1号。裁定如下：拍卖被执行人虚构乙名下房产。\n二〇二五年十月十四日'),
      ('execution','结案通知书\n（2025）粤0101执2号\n被执行人虚构乙已向申请人虚构银行全面履行本案，本案已执行完毕。\n二〇二六年一月十六日')]
    return [dict(id=f'S{i}',source_path='private.pdf',doc_id=str(i),kind=k,page=i+1,text=t) for i,(k,t) in enumerate(texts)]

def test_stage_roles_amount_conflict_and_unknown_date_not_guessed():
    s=sources();ledger=build(s)
    assert len(ledger['conflicts'])==1
    assert ledger['conflicts'][0]['code']=='pleading_principal_difference'
    assert ledger['undated_documents']==['0']
    assert [x['date']['value'] for x in ledger['dated_documents']]==['2025-03-18','2025-10-14','2026-01-16']
    assert 'private.pdf' not in str(public(ledger))
    assert ledger['field_sources']['案情简介']==['S0']

def test_different_fields_keep_facts_requests_adverse_result_and_actual_status():
    s=sources();rows=civil_candidates(s,build(s))
    assert len(rows)==4 and all(validate_candidate(k,v,s) for k,v in rows.items())
    brief=''.join(c['text'] for c in rows['案情简介']['claims'])
    assert '500元' in brief and '2024年1月20日' in brief
    assert '100.9' not in brief and '100.09' not in brief
    assert rows['案情简介']['missing']==['conflicting_sources']
    result=''.join(c['text'] for c in rows['审（办）结果']['claims'])
    assert '驳回其他' in result and '已执行完毕' in result and '裁定拍卖' in result
    assert 'missing_work' in rows['结案小结']['missing']

def test_same_parties_different_execution_is_not_current_result():
    s=sources();s[-1]['text']=s[-1]['text'].replace('执2号','执99号')
    rows=civil_candidates(s,build(s))
    assert '已执行完毕' not in str(rows)
    assert 'missing_result' in rows['审（办）结果']['missing']

def test_multiple_judgments_or_wrong_identity_do_not_auto_merge():
    s=sources();s.append(dict(s[1],doc_id='new',id='S9'))
    assert civil_candidates(s,build(s))=={}
    s=sources()
    assert civil_candidates(s,build(s),{'委托人':'另案银行'})=={}
    s[0]['text']+='\n被告二：另一被告，住所乙地。'
    assert civil_candidates(s,build(s))=={}

def test_caption_cause_requires_exact_same_pleading_roles():
    from case_fact_ledger import caption_title_supported
    s=sources();s[1]['text']=s[1]['text'].replace('原告虚构银行诉被告虚构乙。','原告虚构银行诉被告虚构乙金融借款合同纠纷一案。')
    row=civil_candidates(s,build(s))['案件或项目名称']
    assert row['claims'][0]['text']=='虚构银行诉虚构乙金融借款合同纠纷。'
    assert validate_candidate('案件或项目名称',row,s)
    broken=deepcopy(row['claims'][0]);broken['text']='虚构银行诉另一被告金融借款合同纠纷。'
    assert not caption_title_supported(broken,s)

def test_contract_header_recall_does_not_invent_fees_or_replace_manual_blank():
    from source_contract_roster import recall
    text='委托代理合同\n委托方（甲方）：虚构公司\n住所：甲地\n受托方（乙方）：虚构律师事务所\n住所：乙地'
    u=NS(source_path='x.pdf',doc_type='contract',confidence=.99,start_page=0)
    f={};p={};c=[]
    recall(f,p,c,page_cache={('x.pdf',1):text},allowed_sources={('x.pdf',1)},document_units=[u])
    assert f=={'委托人':'虚构公司','律师事务所':'虚构律师事务所'}
    f={'委托人':''};p={}
    recall(f,p,[],page_cache={('x.pdf',1):text},allowed_sources={('x.pdf',1)},document_units=[u],manual_fields=['委托人'])
    assert f['委托人']==''

def test_printed_page_number_does_not_hide_court_but_body_prefix_stays_rejected():
    from source_court_evidence import extract_court_header_candidate
    page='虚构市人民法院\n民事判决书\n（2025）粤0101民初1号\n原告：虚构银行。'
    assert extract_court_header_candidate('1\n'+page,'（2025）粤0101民初1号')['value']=='虚构市人民法院'
    assert extract_court_header_candidate('1\n参考案例\n'+page,'（2025）粤0101民初1号') is None

def test_contract_ids_do_not_use_the_adjacent_law_firm_code():
    from source_party_evidence import _client_identifiers
    page='委托代理合同\n委托方（甲方）：虚构公司\n住所：甲地\n负责人：虚构甲\n统一社会信用代码：_911111111111111111\n受托方（乙方）：虚构律师事务所\n统一社会信用代码：222222222222222222'
    assert _client_identifiers(page,'虚构公司')=={'统一社会信用代码':'911111111111111111'}
    assert _client_identifiers(page.replace('911111111111111111','不清楚'),'虚构公司') is None

def test_actual_generate_zero_requests_preserves_human_and_source_hash(tmp_path):
    p=tmp_path/'fictional.pdf';p.write_bytes(b'fictional')
    s=sources();units=[];cache={}
    for i,row in enumerate(s):
        units.append(NS(source_path=str(p),doc_id=i,doc_type=row['kind'],confidence=.99,start_page=i,end_page=i))
        cache[str(p),i+1]=row['text']
    class NoNetwork:
        def complete(self,*args):raise AssertionError('must use no provider')
    fields={'案情简介':''};provenance={}
    status=generate(NoNetwork(),fields,provenance,[],units,cache,set(cache),case_type='civil',manual_fields=['案情简介'])
    assert status['requests']==0 and status['strategy']=='structured_source_rules'
    assert fields['案情简介']==''
    for key,refs in provenance.items():assert current_support(refs[-1],fields) is not None

def test_partial_source_candidates_do_not_pretend_full_volume_read():
    s=sources()[:2];ledger=build(s,{'scope':'available_read_pages_not_full_volume'})
    assert ledger['coverage']['scope']=='available_read_pages_not_full_volume'
    assert 'missing_result' in civil_candidates(s,ledger)['审（办）结果']['missing']
