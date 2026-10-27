"""Fictional complete rosters and adversarial edits; no external services."""
from copy import deepcopy

import pytest

from fact_evidence import validate_fact
from source_engagement_evidence import poa_candidates, recall_poa_facts
from source_fact_recall import recall_cached_source_facts


PAGE = '''授权委托书
委托人：星河演示公司
受委托人姓名：虚构程甲
工作单位：虚构明理律师事务所
职务：律师
电话：00000000000
代理权限：特别授权
姓名：虚构程乙
工作单位：_虚构明理律师事务所
职务：律师
代理权限：一般授权
现委托上列受委托人在委托人与虚构对方的纠纷一案中，作为我方诉讼代理人。
委托人（盖章）：星河演示公司
'''


def test_full_roster_has_three_source_backed_fields_but_no_payment_or_signature():
    rows=poa_candidates(PAGE)
    assert {r['field']:r['value'] for r in rows} == {
        '委托人':'星河演示公司','承办律师':'虚构程甲、虚构程乙','律师事务所':'虚构明理律师事务所'}
    for row in rows:
        assert row['quote']==PAGE
        assert validate_fact(row['field'],row['value'],row['quote'],PAGE)
    assert not validate_fact('承办律师','虚构程甲、虚构程丙',PAGE,PAGE)
    assert not validate_fact('承办律师','虚构程甲、虚构程乙','姓名：虚构程乙',PAGE)


@pytest.mark.parametrize('page',[
    PAGE.replace('授权委托书','授权委托书示例'),
    '另案材料\n'+PAGE,
    PAGE.replace('现委托','拟委托'),
    PAGE.replace('作为我方诉讼代理人。','作为诉讼代理人。'),
    PAGE.replace('职务：律师','职务：律师助理',1),
    PAGE.replace('职务：律师','职务：实习律师',1),
    PAGE.replace('工作单位：虚构明理律师事务所','工作单位：星河公司',1),
    PAGE.replace('受委托人姓名：','姓名：',1),
    PAGE+'本授权已失效。',
    PAGE+'撤销本授权。',
    PAGE.replace('姓名：虚构程乙','姓名：待定'),
])
def test_incomplete_proposed_nonlawyer_or_revoked_roster_stays_unresolved(page):
    assert poa_candidates(page)==[]


def test_joint_firms_do_not_choose_one_firm_for_the_quality_card():
    page=PAGE.replace('_虚构明理律师事务所','虚构远山律师事务所')
    assert {r['field'] for r in poa_candidates(page)}=={'委托人','承办律师'}


def recall(fields=None,provenance=None,conflicts=None,cache=None,allowed=None,manual=()):
    fields={} if fields is None else fields
    provenance={} if provenance is None else provenance
    conflicts=[] if conflicts is None else conflicts
    cache={('fictional.pdf',4):PAGE} if cache is None else cache
    reviews=[]
    count=recall_poa_facts(fields,provenance,conflicts,page_cache=cache,
        allowed_sources=set(cache) if allowed is None else allowed,
        manual_fields=manual,fact_review=reviews)
    return fields,provenance,conflicts,reviews,count


def test_recall_scopes_sources_preserves_manual_blanks_and_is_idempotent():
    assert not recall(allowed=set())[0]
    assert recall({'委托人':''},{'委托人':[{'method':'human','value':''}]})[0]=={'委托人':''}
    fields,refs,conflicts,_,count=recall()
    assert count==3 and refs['承办律师'][0]['page']==4
    before=deepcopy((fields,refs,conflicts))
    assert recall(fields,refs,conflicts)[-1]==0
    assert (fields,refs,conflicts)==before
    fields={'承办律师':'虚构人工律师'}
    assert recall(fields,manual=('承办律师',))[0]['承办律师']=='虚构人工律师'


def test_different_clients_are_not_merged_and_different_rosters_are_conflicts():
    second=PAGE.replace('星河演示公司','山海演示公司')
    assert not recall(cache={('a.pdf',1):PAGE,('b.pdf',1):second})[0]
    assert recall({'委托人':'山海演示公司'})[0]=={'委托人':'山海演示公司'}
    second=PAGE.replace('虚构程乙','虚构程丙')
    fields,_,conflicts,_,_=recall(cache={('a.pdf',1):PAGE,('b.pdf',1):second})
    assert '承办律师' not in fields
    assert conflicts[0]['field']=='承办律师' and len(conflicts[0]['sources'])==2


def test_initial_cached_recall_restores_missing_fields_and_keeps_original_rejection():
    fields={};refs={};conflicts=[]
    review=[{'field':'承办律师','source_path':'fictional.pdf','page':4,'reason_code':'local_evidence_rejected'}]
    metrics=recall_cached_source_facts(fields,refs,conflicts,page_cache={('fictional.pdf',4):PAGE},
        allowed_sources={('fictional.pdf',4)},fact_review=review)
    assert fields['承办律师']=='虚构程甲、虚构程乙'
    assert review[0]['resolution']=='field_supported_by_cached_source'
    assert review[0]['reason_code']=='local_evidence_rejected'
    assert metrics['additional_model_requests']==metrics['additional_page_reads']==0


def test_poa_client_can_be_linked_to_current_court_party_without_using_lawyer_ids():
    from source_party_evidence import _client_identifiers
    fields={'案号':'（2026）粤0000民初123号'}
    judgment=('虚构市示例区人民法院\n民事判决书\n'+fields['案号']+
              '\n原告：星河演示公司，住所地虚构路一号。\n被告：虚构对方，住所地虚构路二号。')
    refs={'案号':[{'method':'local_agent','value':fields['案号'],'quote':fields['案号'],
                     'source_path':'fictional.pdf','page':5}]}
    cache={('fictional.pdf',4):PAGE,('fictional.pdf',5):judgment}
    recall_cached_source_facts(fields,refs,[],page_cache=cache,allowed_sources=set(cache),fact_review=[])
    assert _client_identifiers(PAGE,'星河演示公司')=={}
    assert _client_identifiers(PAGE+'统一社会信用代码：FAKE123456','星河演示公司') is None
    assert fields['当事人']=='星河演示公司'
    assert refs['当事人'][0]['binding']=='client_court_party'
    assert refs['当事人'][0]['role']=='原告'
    assert '对方当事人' not in fields  # A party roster is not yet an opponent mapping.
