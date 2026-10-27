"""Native-form inputs, provenance links and review state share report validity."""
from copy import deepcopy
from pathlib import Path
import runpy
from types import SimpleNamespace
import pytest
from app.core.v4_bridge import load
from app.services.field_assurance import field_assurance
from app.services.evidence_links import supporting_refs
from app.services.original_template_service import _values
from app.services.party_binding_state import reconcile_party_bindings
from app.services.outcome_state import refresh_missing_outcome, MISSING_OUTCOME_WARNING

load('court_report_summary')
RUN=runpy.run_path(str(Path(__file__).resolve().parents[3]/'tests/test_court_report_summary.py'))['run']
MANIFEST=[{'path':name+'.pdf','file_id':name,'filename':name+'.pdf','pages':2} for name in ('judgment','notice')]


def test_report_enters_both_original_forms_with_all_source_anchors():
    fields,_,_,_=RUN();value=fields['结案小结']
    for form in ('结案报告表','档案卷宗'):
        assert _values(form,fields,'',{})['结案小结' if form=='结案报告表' else '审（办）结果']==value
    assurance=field_assurance('结案小结',value,fields,source_manifest=MANIFEST)
    assert assurance['status']=='source_supported' and assurance['source_count']==4
    module=load('form_drafts')
    accepted,refs=module._accepted(fields,'结案小结',{},module._scope(MANIFEST))
    assert accepted==value and len(supporting_refs(refs[0],fields,MANIFEST))==3
    analysis=SimpleNamespace(fields=fields,case_type='民事',outcome_warnings=[MISSING_OUTCOME_WARNING])
    refresh_missing_outcome(analysis,{},MANIFEST,[])
    assert MISSING_OUTCOME_WARNING not in analysis.outcome_warnings


@pytest.mark.parametrize('change',['identity','source_page','primary_hash','continuation','missing_file'])
def test_stale_report_cannot_clear_warning_or_keep_badge(change):
    fields,_,_,_=RUN();ref=fields['_provenance']['结案小结'][-1];manifest=deepcopy(MANIFEST)
    if change=='identity':fields['执行案号']='（2026）粤0000执89号'
    if change=='source_page':ref['page']=3
    if change=='primary_hash':ref['source_sha256']='changed'
    if change=='continuation':ref['documents'][1]['pages'].pop()
    if change=='missing_file':manifest=manifest[:1]
    assert field_assurance('结案小结',fields['结案小结'],fields,source_manifest=manifest)['status']=='unverified'
    analysis=SimpleNamespace(fields=fields,case_type='民事',outcome_warnings=[MISSING_OUTCOME_WARNING])
    refresh_missing_outcome(analysis,{},manifest,[])
    assert MISSING_OUTCOME_WARNING in analysis.outcome_warnings
    assert reconcile_party_bindings(fields,{},manifest)['结案小结']==''


def test_manual_report_remains_editable_and_is_not_replaced_by_invalidated_draft():
    fields,_,_,_=RUN();fields['案号']='（2026）粤0000民初999号'
    result=reconcile_party_bindings(fields,{'结案小结':'人工填写的报告'},MANIFEST)
    assert result['结案小结']=='人工填写的报告'


def test_form_derivation_can_reference_report_without_losing_its_evidence():
    fields,_,_,_=RUN()
    for key in ('委托人','案由','对方当事人','案号'):
        fields['_provenance'][key]=[{'method':'human','value':fields[key]}]
    derived=load('form_drafts').derive_form_drafts(fields,[],source_manifest=MANIFEST)
    assert field_assurance('案情简介',derived['案情简介'],derived,source_manifest=MANIFEST)['status']=='derived_draft'
    for ref in derived['_form_draft_sources']['案情简介']:
        if ref['field']=='结案小结':assert supporting_refs(ref,derived,MANIFEST) is not None
