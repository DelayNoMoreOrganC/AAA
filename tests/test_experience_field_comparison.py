"""Field-record protocol checks, never real model/Word accuracy evidence."""
from copy import deepcopy
import pytest
from agent_trace import digest, TRACE_RUNS, TRACE_CURRENT, RESERVED_KEYS
from agent_experience import ExperienceError
from machine_field_candidates import capture, KEY
from experience_field_comparison import project, compare, references
from tests.test_experience_boundary_comparison import sample


def recorded(value='', *, page=1, human=False, stale=False):
    fields,manifest=sample([[1,4]])
    source=manifest[0]
    metadata={'_provenance':{'委托人':[{'value':value,'source_path':source['path'],'page':page,
        'source_sha256':'b'*64 if stale else source['sha256'],'method':'human' if human else 'visual_agent_local_evidence'}]}}
    original={'委托人':value,'合同号':'historical-number-not-for-output'}
    record=capture(original,metadata,{source['path']:{'sha256':source['sha256'],'page_count':4}},case_type='civil')
    run=fields[TRACE_RUNS][0];run['body']['payload'][KEY]=record
    run['run_id']=digest(run['body']);fields[TRACE_CURRENT]=run['run_id'];fields[KEY]=deepcopy(record)
    fields.update(original)
    return fields,manifest


def label(field='委托人', mode='exact'):
    return {'baseline_task_id':1,'baseline_revision':1,'candidate_task_id':2,'candidate_revision':1,
        'expected_applicable':True,'reference_reviewed':True,'cells':[{'field':field,'mode':mode,
            'accepted_values':['protocol-party'] if mode=='exact' else [],
            'allowed_sources':[] if mode=='blank' else [{'file_id':'file','page':1}]}]}


def test_machine_output_remains_distinct_from_subsequent_manual_value():
    before,manifest=recorded()
    after,_=recorded('protocol-party')
    before['委托人']='protocol-party'  # Must not turn the old model blank into success.
    result=compare(label(),project(before,manifest,'e'*64),project(after,manifest,'e'*64),manifest)
    assert not result['baseline_checks_match'] and result['candidate_checks_match']
    assert result['evaluated_fields']==['委托人'] and result['not_evaluated_fields']
    assert 'protocol-party' not in str(result)
    assert KEY in RESERVED_KEYS


@pytest.mark.parametrize('kwargs,failed_check',[
    ({'page':2},'source_requirement'),({'page':99},'source_scope_valid'),
    ({'human':True},'not_human_influenced'),({'stale':True},'source_scope_valid')])
def test_correct_text_cannot_hide_wrong_source_or_human_answer(kwargs,failed_check):
    before,manifest=recorded('protocol-party')
    after,_=recorded('protocol-party',**kwargs)
    result=compare(label(),project(before,manifest,'e'*64),project(after,manifest,'e'*64),manifest)
    assert result['new_errors'] and not result['candidate_checks_match']
    assert result['cells'][0]['candidate']['checks'][failed_check] is False


def test_reserved_contract_number_stays_blank_without_erasing_original_candidate():
    fields,manifest=recorded('protocol-party')
    observed=project(fields,manifest,'e'*64)
    assert observed['cells']['合同号']['value']=='historical-number-not-for-output'
    result=compare(label('合同号','blank'),observed,observed,manifest)
    assert result['candidate_checks_match']
    assert fields['合同号']=='historical-number-not-for-output'


def test_record_is_copied_not_mutated_by_later_edits():
    fields,manifest=recorded('protocol-party')
    fields[KEY]['cells']['委托人']['value']='altered'
    with pytest.raises(ExperienceError):project(fields,manifest,'e'*64)


def test_old_result_without_original_candidates_is_not_backfilled_from_current_fields():
    fields,manifest=sample([[1,4]])
    fields['委托人']='protocol-party'
    with pytest.raises(ExperienceError):project(fields,manifest,'e'*64)


def test_grounded_nonempty_does_not_claim_semantic_completeness():
    fields,manifest=recorded('protocol-party')
    observed=project(fields,manifest,'e'*64)
    result=compare(label(mode='grounded_nonempty'),observed,observed,manifest)
    assert result['candidate_checks_match']
    assert not result['semantic_completeness_verified'] and not result['native_output_verified']


def test_unknown_source_annotation_and_changed_policy_are_rejected():
    fields,manifest=recorded('protocol-party');observed=project(fields,manifest,'e'*64)
    bad=label();bad['cells'][0]['allowed_sources'][0]['file_id']='foreign'
    with pytest.raises(ExperienceError):compare(bad,observed,observed,manifest)
    changed=deepcopy(observed);changed['cell_policy_digest']='x'*64
    with pytest.raises(ExperienceError,match='FIELD_POLICY_MISMATCH'):compare(label(),observed,changed,manifest)
    bad=label();bad['passed']=True
    with pytest.raises(ExperienceError):references(bad)
