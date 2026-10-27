"""Source-bound court details survive export and invalidate with their evidence."""
from pathlib import Path
import runpy
from types import SimpleNamespace
import pytest
from app.core.v4_bridge import load
from app.services.field_assurance import field_assurance
from app.services.evidence_links import supporting_refs
from app.services.task_workflow import analysis_issues

load('form_drafts')
FIXTURE=runpy.run_path(str(Path(__file__).resolve().parents[3]/'tests/test_court_roster_details.py'))['fixture']
MANIFEST=[{'path':name+'.pdf','file_id':name,'filename':name+'.pdf','pages':1} for name in ('poa','court')]


def prepared():
    fields,_=FIXTURE()
    fields['案由']='买卖合同纠纷'
    fields['_provenance']['案由']=[{'method':'human','value':fields['案由']}]
    fields['_fact_review']=[{'field':'对方当事人','source_path':'court.pdf','page':1,
        'reason_code':'local_evidence_rejected','resolution':'field_supported_by_cached_source'}]
    return fields


def review(fields,manifest):
    return analysis_issues(SimpleNamespace(fields=fields,doc_spans=[],low_confidence_items=[],
        missing_items=[],case_type='民事'),manifest)


def test_roster_and_contact_flow_into_forms_and_remove_only_resolved_review():
    fields=prepared();drafts=load('form_drafts')
    for field in ('对方当事人','地址','委托人电话'):
        assert field_assurance(field,fields[field],fields,source_manifest=MANIFEST)['status']=='source_supported'
        value,refs=drafts._accepted(fields,field,set(),drafts._scope(MANIFEST))
        assert value==fields[field] and refs
        assert supporting_refs(refs[0],fields,MANIFEST) is not None
    assert not any(row['kind']=='fact_review' for row in review(fields,MANIFEST))
    fields=drafts.derive_form_drafts(fields,[],source_manifest=MANIFEST)
    assert '虚构乙、虚构丙' in fields['案情简介']
    assert '00000000000' in fields['委托人联系地址及电话']
    assert field_assurance('委托人联系地址及电话',fields['委托人联系地址及电话'],fields,source_manifest=MANIFEST)['status']=='derived_draft'
    fields['当事人']='不同虚构公司'
    assert field_assurance('委托人联系地址及电话',fields['委托人联系地址及电话'],fields,source_manifest=MANIFEST)['status']=='unverified'


@pytest.mark.parametrize('change',['client','quote','primary_page','primary_hash','support_path','support_page','delete_source'])
def test_badge_and_review_do_not_trust_broken_support(change):
    fields=prepared();ref=fields['_provenance']['对方当事人'][0]
    manifest=[dict(row) for row in MANIFEST]
    if change=='client':fields['委托人']='不同虚构公司'
    if change=='quote':ref['quote']=ref['quote'].replace('虚构乙','虚构戊')
    if change=='primary_page':ref['page']=2
    if change=='primary_hash':ref['source_sha256']='other'
    if change=='support_path':ref['supporting_sources'][0]['source_path']='other.pdf'
    if change=='support_page':ref['supporting_sources'][0]['page']=2
    if change=='delete_source':manifest=manifest[1:]
    assert field_assurance('对方当事人',fields['对方当事人'],fields,source_manifest=manifest)['status']=='unverified'
    assert any(row['kind']=='fact_review' for row in review(fields,manifest))


def test_refresh_clears_stale_automatic_details_but_keeps_human_values():
    from app.services.party_binding_state import reconcile_party_bindings
    fields=prepared();fields['委托人']='不同虚构公司'
    result=reconcile_party_bindings(fields,{},MANIFEST)
    assert result['对方当事人']==result['地址']==result['委托人电话']==''
    assert fields['对方当事人']=='虚构乙、虚构丙'
    manual=reconcile_party_bindings(fields,{'地址':'人工核对的新地址'},MANIFEST)
    assert manual['地址']=='人工核对的新地址'


def test_project_name_includes_current_opponents_only_when_client_is_represented_party():
    fields=prepared();fields['案件类别']='民事'
    drafts=load('form_drafts')
    result=drafts.derive_form_drafts(fields,[],source_manifest=MANIFEST)
    assert result['案件或项目名称']=='星河演示公司与虚构乙、虚构丙买卖合同纠纷'
    assert field_assurance('案件或项目名称',result['案件或项目名称'],result,source_manifest=MANIFEST)['status']=='derived_draft'
    fields['当事人']='另一当事人'
    result=drafts.derive_form_drafts(fields,[],source_manifest=MANIFEST)
    assert result['案件或项目名称']=='星河演示公司：买卖合同纠纷'
