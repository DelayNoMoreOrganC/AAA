"""Trace protocol checks only; no PDF, model, OCR or case-accuracy claims."""
from copy import deepcopy
from pathlib import Path
import pytest

from agent_trace import digest, SCHEMA, TRACE_CURRENT, TRACE_RUNS
from agent_experience import ExperienceError
from experience_boundary_comparison import project, compare, references


def sample(ranges, *, experience='e'*64):
    path = str(Path('protocol-source-only').absolute())
    manifest = [{'file_id':'file', 'path':path, 'pages':4, 'sha256':'a'*64}]
    pages = {f'p{n}':{'source_path':path, 'page':n} for n in range(1,5)}
    docs = {f'd{i}':{'page_ids':[f'p{n}' for n in range(start,end+1)], 'local_doc_id':i}
            for i,(start,end) in enumerate(ranges,1)}
    payload = {'_experience_policy':{'snapshot_sha256':experience}, '_visual_boundary_review':[]}
    body = {'schema':SCHEMA, 'scope':{'sources':{path:{'sha256':'a'*64, 'page_count':4}},
        'pages':pages, 'documents':docs}, 'payload':payload}
    mapping = {key:value['local_doc_id'] for key,value in docs.items()}
    run = {'run_id':digest(body), 'body':body, 'archive_document_ids_at_merge':mapping, 'mapping_sha256':digest(mapping)}
    return {**deepcopy(payload), TRACE_CURRENT:run['run_id'], TRACE_RUNS:[run]}, manifest


def label(ranges=None):
    return {'baseline_task_id':1,'baseline_revision':1,'candidate_task_id':2,'candidate_revision':1,
            'expected_applicable':True,'reference_reviewed':True,
            'documents':[{'file_id':'file','ranges':ranges or [[1,2],[3,4]]}]}


def test_actual_trace_boundaries_compare_without_using_manual_projection():
    before,manifest = sample([[1,4]])
    after,_ = sample([[1,2],[3,4]])
    before['doc_spans'] = [{'start_page':0,'end_page':1},{'start_page':2,'end_page':3}]
    before['_document_classifications'] = {'not_a_model_result':'manual correction'}
    result = compare(label(),project(before,manifest,'e'*64),project(after,manifest,'e'*64),manifest)
    assert result['improved_to_reference'] and not result['new_errors']
    assert result['files'][0]['baseline']['missing_boundaries']==[3]


def test_new_split_and_merge_errors_are_not_hidden_by_equal_counts():
    before,manifest=sample([[1,2],[3,4]])
    after,_=sample([[1,1],[2,4]])
    result=compare(label(),project(before,manifest,'e'*64),project(after,manifest,'e'*64),manifest)
    assert result['new_errors'] and not result['candidate_matches_reference']
    assert result['files'][0]['candidate']['missing_boundaries']==[3]
    assert result['files'][0]['candidate']['extra_boundaries']==[2]


@pytest.mark.parametrize('attack',['changed_source','experience','trace_hash','flat_view','missing_page','duplicate_page','cross_document_duplicate','legacy','multiple_runs','budget_stop'])
def test_incomplete_or_unbound_model_result_is_not_evidence(attack):
    fields,manifest=sample([[1,2],[3,4]])
    run=fields[TRACE_RUNS][0]
    if attack=='changed_source':manifest[0]['sha256']='b'*64
    elif attack=='experience':run['body']['payload']['_experience_policy']['snapshot_sha256']='b'*64
    elif attack=='trace_hash':run['run_id']='b'*64
    elif attack=='flat_view':fields['_experience_policy']={}
    elif attack=='missing_page':run['body']['scope']['pages'].pop('p4')
    elif attack=='duplicate_page':run['body']['scope']['pages']['p4']['page']=3
    elif attack=='cross_document_duplicate':run['body']['scope']['documents']['d2']['page_ids']=['p2','p3','p4']
    elif attack=='legacy':run['body']['schema']='legacy-unscoped'
    elif attack=='multiple_runs':fields[TRACE_RUNS].append(deepcopy(run))
    else:run['body']['payload']['_request_budget_stop']={'status':'incomplete'}
    # Shape/coverage checks must still reject invalid data with a valid hash.
    if attack not in {'trace_hash','flat_view','multiple_runs'}:
        run['run_id']=digest(run['body']);fields[TRACE_CURRENT]=run['run_id']
        fields.update(deepcopy(run['body']['payload']))
    with pytest.raises(ExperienceError):project(fields,manifest,'e'*64)


@pytest.mark.parametrize('ranges',[[[1,2],[4,4]],[[1,3],[3,4]],[[1,True]],[[2,4]]])
def test_reference_requires_contiguous_complete_spans(ranges):
    with pytest.raises(ExperienceError):references(label(ranges))


def test_pending_boundary_review_does_not_count_as_resolved_improvement():
    before,manifest=sample([[1,4]])
    after,_=sample([[1,2],[3,4]])
    run=after[TRACE_RUNS][0]
    run['body']['payload']['_visual_boundary_review']=[{'status':'unresolved'}]
    run['run_id']=digest(run['body']);after[TRACE_CURRENT]=run['run_id']
    after.update(deepcopy(run['body']['payload']))
    result=compare(label(),project(before,manifest,'e'*64),project(after,manifest,'e'*64),manifest)
    assert result['candidate_matches_reference'] and not result['improved_to_reference']
    assert result['candidate_unresolved_reviews']==1
