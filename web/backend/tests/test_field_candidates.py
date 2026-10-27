"""Candidate decisions must resolve actual facts without changing source history."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from app.schemas import FieldDecisionRequest
from app.services.field_decisions import field_candidates, prepare_accept_current, fact_conflict_resolved, FieldDecisionError
from app.services import archive_service
from app.services.analysis_snapshot import load_snapshot_data
from tests.test_form_conflict_resolution import fixture, saved_task, CLIENT


def setup(tmp_path):
    analysis, manifest, conflict = fixture(tmp_path)
    detail = analysis.fields['_field_conflicts'][0]
    detail['sources'] = [dict(value=CLIENT, source_path=manifest[0]['path'], page=1, quote='委托人：'+CLIENT),
                         dict(value='另一虚构候选', source_path=manifest[0]['path'], page=1, quote='委托人：另一虚构候选')]
    conflict['detail'] = deepcopy(detail)
    analysis.fields['委托人'] = ''
    task, work = saved_task(tmp_path, analysis, manifest, conflict)
    body = FieldDecisionRequest(action='accept_candidate',field='委托人',current_value='',selected_value=CLIENT,
        expected_revision=1,source_version=task.source_version,request_id='fictional-candidate-v72')
    return task, work, body


@pytest.mark.asyncio
async def test_candidate_applies_once_and_preserves_sources_and_snapshot(tmp_path, monkeypatch):
    task, work, body = setup(tmp_path)
    before = deepcopy(task.fields['_field_conflicts'][0])
    monkeypatch.setattr(archive_service,'_work_dir_for',lambda *_:str(work))
    assert len(field_candidates(task,'委托人')) == 2
    receipt,replay = prepare_accept_current(task,body,actor_id='tester',org_id='org')
    assert not replay and receipt['operation']=='accept_candidate' and receipt['selected_sources'][0]['page']==1
    fields=await archive_service.update_task_fields(task,'org',{'委托人':CLIENT},actor_id='tester',accept_current=receipt)
    assert fields['委托人']==task.manual_fields['委托人']==CLIENT
    assert all(fields['_field_conflicts'][0][k]==v for k,v in before.items())
    assert fact_conflict_resolved(task,fields['_field_conflicts'][0])
    assert task.revision==2 and task.confirmation is None and task.artifacts is None
    assert fields==load_snapshot_data(str(work))['fields']
    assert prepare_accept_current(task,body,actor_id='tester',org_id='org')[1]
    assert field_candidates(task,'委托人')==[]
    with pytest.raises(FieldDecisionError):
        prepare_accept_current(task,body.model_copy(update={'selected_value':'另一虚构候选'}),actor_id='tester',org_id='org')


@pytest.mark.parametrize('change',['value','revision','version','current','field'])
def test_stale_or_forged_choice_rejected_without_mutation(tmp_path,change):
    task,work,body=setup(tmp_path)
    changes={'value':{'selected_value':'任意伪造值'},'revision':{'expected_revision':2},'version':{'source_version':'b'*64},
             'current':{'current_value':'不是当前值'},'field':{'field':'案号'}}
    before=deepcopy(vars(task))
    with pytest.raises(FieldDecisionError):
        prepare_accept_current(task,body.model_copy(update=changes[change]),actor_id='tester',org_id='org')
    assert vars(task)==before


@pytest.mark.parametrize('change',['page','path','id','quote','hash'])
def test_invalid_candidate_source_is_not_selectable(tmp_path,change):
    task,work,body=setup(tmp_path)
    for detail in [task.fields['_field_conflicts'][0],task.issues[0]['detail']]:
        ref=detail['sources'][0]
        ref.update({'page':{'page':2},'path':{'source_path':'Z:/outside.pdf'},'id':{'file_id':'other'},
                    'quote':{'quote':''},'hash':{'source_sha256':'b'*64}}[change])
    assert all(r['value']!=CLIENT for r in field_candidates(task,'委托人'))
    with pytest.raises(FieldDecisionError):
        prepare_accept_current(task,body,actor_id='tester',org_id='org')


def test_schema_requires_explicit_candidate_and_nonblank_current_accept(tmp_path):
    _,_,body=setup(tmp_path)
    for changes in [{'selected_value':None},{'selected_value':' '},{'action':'accept_current'},{'action':'accept_current','current_value':'x'}]:
        with pytest.raises(ValidationError):
            FieldDecisionRequest.model_validate(dict(body.model_dump(),**changes))
