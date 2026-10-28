"""Fictional court rosters: representation comes from evidence, never a default."""
from copy import deepcopy
import pytest
from court_roster_details import candidates,current_detail_support
from source_fact_recall import recall_cached_source_facts

NUMBER='（2026）粤0000民初123号'
CLIENT='星河演示公司'
POA='''授权委托书
委托人：星河演示公司
受委托人姓名：虚构程甲
工作单位：虚构明理律师事务所
职务：律师
现委托上列受委托人在委托人与虚构对方的纠纷一案中，作为我方诉讼代理人。
'''
COURT=f'''虚构市示例区人民法院
民事判决书
{NUMBER}
原告：{CLIENT}，住所地虚构市示例区演示路一号。电话：00000000000。
负责人：虚构负责人。
委托诉讼代理人：虚构程甲，联系电话：99999999999。
被告：虚构乙，住所地虚构市另一街二号。
被告：虚构丙，住所地虚构市另一街三号。
第三人：虚构丁，住所地虚构市另一街四号。
原告{CLIENT}诉被告虚构乙、虚构丙买卖合同纠纷一案，本院受理后依法审理。
'''


def fixture(court=COURT,extra_fields=None):
    fields={'案号':NUMBER,**(extra_fields or {})}
    refs={'案号':[{'method':'local_agent','value':NUMBER,'quote':NUMBER,'source_path':'court.pdf','page':1}]}
    cache={('poa.pdf',1):POA,('court.pdf',1):court};conflicts=[];review=[]
    recall_cached_source_facts(fields,refs,conflicts,page_cache=cache,allowed_sources=set(cache),fact_review=review)
    fields.update(_provenance=refs,_field_conflicts=conflicts)
    return fields,cache


def test_closed_roster_extracts_both_opponents_and_only_client_contact():
    fields,_=fixture()
    assert fields['对方当事人']=='虚构乙、虚构丙'
    assert fields['地址']=='虚构市示例区演示路一号'
    assert fields['委托人电话']=='00000000000'
    for key in ('对方当事人','地址','委托人电话'):
        ref=fields['_provenance'][key][0]
        assert ref['quote']==COURT
        supports=current_detail_support(ref,fields)
        assert {item['field'] for item in supports}=={'当事人','委托人','案号'}


def test_last_counsel_before_next_party_is_not_lost_with_delimiter():
    page=COURT.replace('委托诉讼代理人：虚构程甲，联系电话：99999999999。',
        '委托诉讼代理人：虚构程甲，虚构明理律师事务所律师。\n委托诉讼代理人：虚构程乙，虚构明理律师事务所律师。')
    values={r['field']:r['value'] for r in candidates(page,CLIENT,NUMBER)}
    assert values['承办律师']=='虚构程甲、虚构程乙'


def test_defendant_client_does_not_make_codefendant_an_opponent():
    page=COURT.replace(f'原告：{CLIENT}',f'原告：虚构戊').replace('被告：虚构乙',f'被告：{CLIENT}')
    values={x['field']:x['value'] for x in candidates(page,CLIENT,NUMBER)}
    assert values['对方当事人']=='虚构戊'
    assert values['地址']=='虚构市另一街二号'
    assert '委托人电话' not in values


@pytest.mark.parametrize('page,number',[
    (COURT.split('\n原告星河')[0],NUMBER),  # Unfinished list may continue next page.
    ('参考案例\n'+COURT,NUMBER),
    (COURT+'本案反诉被告：虚构丙。',NUMBER),
    (COURT.replace('民初','民终'),'（2026）粤0000民终123号'),
    (COURT,NUMBER.replace('123','124')),
    (COURT.replace('被告：虚构丙','被告：虚构丙、其他人'),NUMBER),
])
def test_ambiguous_incomplete_other_case_or_appellate_roster_stays_for_review(page,number):
    assert candidates(page,CLIENT,number)==[]


def test_duplicate_opponent_names_do_not_discard_independent_client_contact():
    fields={row['field'] for row in candidates(COURT.replace('被告：虚构丙','被告：虚构乙'),CLIENT,NUMBER)}
    assert fields=={'地址','委托人电话'}


@pytest.mark.parametrize('change',['client','number','party','client_conflict','party_conflict','field_conflict','quote','support','missing_provenance'])
def test_saved_detail_becomes_invalid_when_its_support_changes(change):
    fields,_=fixture();ref=deepcopy(fields['_provenance']['对方当事人'][0])
    if change=='client':fields['委托人']='不同公司'
    if change=='number':fields['案号']=NUMBER.replace('123','124')
    if change=='party':fields['当事人']='不同公司'
    if change=='client_conflict':fields['_field_conflicts']=[{'field':'委托人'}]
    if change=='party_conflict':fields['_field_conflicts']=[{'field':'当事人'}]
    if change=='field_conflict':fields['_field_conflicts']=[{'field':'对方当事人'}]
    if change=='quote':ref['quote']=COURT.replace('被告：虚构丙','被告：虚构戊')
    if change=='support':ref['supporting_sources'][0]['page']=2
    if change=='missing_provenance':fields['_provenance']['当事人']=[]
    assert current_detail_support(ref,fields) is None


def test_recall_keeps_human_blank_and_existing_values_and_does_not_read_new_pages():
    fields,cache=fixture();fields['地址']=''
    refs=fields['_provenance'];refs['地址'].append({'method':'human','value':''})
    before=deepcopy(fields)
    metrics=recall_cached_source_facts(fields,refs,fields['_field_conflicts'],page_cache=cache,
        allowed_sources=set(cache),fact_review=[])
    assert fields==before
    assert metrics['additional_model_requests']==metrics['additional_page_reads']==0
