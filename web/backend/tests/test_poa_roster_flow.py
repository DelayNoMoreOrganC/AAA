"""Fictional source roster through fields, drafts, evidence and review queue."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core.v4_bridge import load
from app.services.field_assurance import field_assurance
from app.services.evidence_links import supporting_refs
from app.services.task_workflow import analysis_issues

PAGE = '''授权委托书
委托人：星河演示公司
受委托人姓名：虚构程甲
工作单位：虚构明理律师事务所
职务：律师
姓名：虚构程乙
工作单位：虚构明理律师事务所
职务：律师
现委托上列受委托人在委托人与虚构对方的纠纷一案中，作为我方诉讼代理人。
'''
MANIFEST = [{'path':'fictional.pdf','pages':4,'file_id':'fictional','filename':'fictional.pdf'}]


def fixture():
    fields={};provenance={};conflicts=[]
    reviews=[{'field':'承办律师','source_path':'fictional.pdf','page':4,
              'reason_code':'local_evidence_rejected'}]
    load('source_fact_recall').recall_cached_source_facts(fields,provenance,conflicts,
        page_cache={('fictional.pdf',4):PAGE},allowed_sources={('fictional.pdf',4)},fact_review=reviews)
    fields.update(_provenance=provenance,_field_conflicts=conflicts,_fact_review=reviews)
    return fields


def issues(fields,manifest):
    analysis=SimpleNamespace(fields=fields,doc_spans=[],low_confidence_items=[],
                             missing_items=[],case_type='民事')
    return analysis_issues(analysis,manifest)


def test_complete_roster_accepted_without_a_false_literal_substring_requirement():
    fields=fixture()
    assert fields['承办律师'] not in PAGE
    drafts=load('form_drafts')
    value,refs=drafts._accepted(fields,'承办律师',set(),drafts._scope(MANIFEST))
    assert value==fields['承办律师'] and refs[0]['derivation']=='labelled_poa_roster'
    for field in ('委托人','承办律师','律师事务所'):
        assert field_assurance(field,fields[field],fields,source_manifest=MANIFEST)['status']=='source_supported'
    assert not any(row['kind']=='fact_review' for row in issues(fields,MANIFEST))
    assert fields['_fact_review'][0]['reason_code']=='local_evidence_rejected'


@pytest.mark.parametrize('change',['client','conflict','quote','source','page','hash','value'])
def test_no_false_assurance_or_review_suppression_after_evidence_changes(change):
    fields=fixture();ref=fields['_provenance']['承办律师'][0]
    if change=='client':fields['委托人']='另一虚构公司'
    if change=='conflict':fields['_field_conflicts']=[{'field':'委托人','values':['甲','乙']}]
    if change=='quote':ref['quote']=PAGE.replace('虚构程乙','虚构程丙')
    if change=='source':ref['source_path']='another.pdf'
    if change=='page':ref['page']=5
    if change=='hash':ref['source_sha256']='different'
    if change=='value':fields['承办律师']='虚构程甲'
    assert field_assurance('承办律师',fields['承办律师'],fields,source_manifest=MANIFEST)['status']=='unverified'
    assert any(row['kind']=='fact_review' for row in issues(fields,MANIFEST))


def test_draft_source_is_invalidated_when_represented_client_changes():
    fields=fixture()
    fields['案由']='买卖合同纠纷'
    fields['_provenance']['案由']=[{'method':'human','value':fields['案由']}]
    fields=load('form_drafts').derive_form_drafts(fields,[],source_manifest=MANIFEST)
    value=fields['案件或项目名称']
    assert value
    assert field_assurance('案件或项目名称',value,fields,source_manifest=MANIFEST)['status']=='derived_draft'
    fields['委托人']='另一虚构公司'
    assert field_assurance('案件或项目名称',value,fields,source_manifest=MANIFEST)['status']=='unverified'
    for ref in fields['_provenance']['案件或项目名称']:
        if ref.get('derivation')=='labelled_poa_roster':
            assert supporting_refs(ref,fields,MANIFEST) is None


def test_source_deletion_manual_blank_and_supplement_context_do_not_repopulate():
    fields=fixture()
    assert any(row['kind']=='fact_review' for row in issues(fields,[]))
    fields['承办律师']=''
    fields['_provenance']['承办律师'].append({'method':'human','value':''})
    assert field_assurance('承办律师','',fields,source_manifest=MANIFEST)['status']=='human_confirmed'
    before=deepcopy(fields)
    load('source_fact_recall').recall_cached_source_facts(fields,fields['_provenance'],[],
        page_cache={('fictional.pdf',4):PAGE},allowed_sources={('fictional.pdf',4)},
        fact_review=[],local_recall_context={})
    assert fields==before
