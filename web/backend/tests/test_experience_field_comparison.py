"""Field comparison endpoint and immutable machine-record integration only."""
import asyncio
from copy import deepcopy
import pytest
from tests.test_experience_boundary_comparison import scenario
from app.models import ArchiveTask,User
from app.services.experience_boundary_comparison import run_comparison
from app.services.experience_store import _receipt_passes
from app.services.experience_rules import ExperienceError
from agent_trace import digest,TRACE_CURRENT,TRACE_RUNS
from machine_field_candidates import capture,KEY

RULE={'case_types':['civil'],'document_kinds':['evidence'],'required_signals':['field_reference'],
      'excluded_signals':[],'action':'read_for_field','target_fields':['parties']}


async def configure(db,refs):
    for task_id in (20,21,30,31):
        task=await db.get(ArchiveTask,task_id)
        source=task.source_manifest[0];value='protocol-party' if task_id==21 else ''
        metadata={'_provenance':{'委托人':[{'method':'visual_agent_local_evidence',
            'value':value,'source_path':source['path'],'page':1}]}}
        current=deepcopy(task.fields)
        captured=capture({'委托人':value},metadata,{source['path']:{'sha256':source['sha256'],'page_count':4}},case_type='civil')
        run=current[TRACE_RUNS][0];run['body']['payload'][KEY]=captured
        run['run_id']=digest(run['body']);current[TRACE_CURRENT]=run['run_id'];current[KEY]=deepcopy(captured)
        current['委托人']='manual-display-value-must-not-be-used'
        task.fields=current
    for ref in refs:
        file_id=ref.pop('documents')[0]['file_id']
        ref['cells']=[{'field':'委托人','mode':'exact' if ref['expected_applicable'] else 'blank',
            'accepted_values':['protocol-party'] if ref['expected_applicable'] else [],
            'allowed_sources':[{'file_id':file_id,'page':1}] if ref['expected_applicable'] else []}]
    await db.flush()


def test_field_comparison_checks_selected_cells_but_cannot_publish(tmp_path,monkeypatch):
    async def check(db,rule,refs):
        await configure(db,refs)
        receipt=await run_comparison(db,'admin',rule.id,revision=1,references=refs,comparison='fields')
        assert receipt.result['all_selected_field_checks_match']
        assert not receipt.result['any_new_field_check_failures']
        assert receipt.result['samples'][0]['comparison']['baseline_checks_match'] is False
        assert not receipt.result['native_output_verified'] and not _receipt_passes(receipt,rule)
        assert not receipt.result['field_accuracy_verified'] and rule.state=='draft'
        assert 'protocol-party' not in str(receipt.result)
    asyncio.run(scenario(tmp_path,monkeypatch,check,RULE))


def test_missing_machine_record_does_not_accept_current_manual_field(tmp_path,monkeypatch):
    async def check(db,rule,refs):
        await configure(db,refs)
        task=await db.get(ArchiveTask,21);current=deepcopy(task.fields)
        current.pop(KEY);run=current[TRACE_RUNS][0];run['body']['payload'].pop(KEY)
        run['run_id']=digest(run['body']);current[TRACE_CURRENT]=run['run_id'];task.fields=current
        await db.flush()
        with pytest.raises(ExperienceError,match='FIELD_RESULT_INVALID'):
            await run_comparison(db,'admin',rule.id,revision=1,references=refs,comparison='fields')
    asyncio.run(scenario(tmp_path,monkeypatch,check,RULE))


def test_field_http_route_does_not_accept_evaluator_or_pass_override(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from httpx import AsyncClient,ASGITransport
    from app.routers.experiences import router
    from app.database import get_db
    from app.deps import get_current_user
    async def check(db,rule,refs):
        await configure(db,refs)
        app=FastAPI();app.include_router(router)
        async def session():yield db
        async def user():return await db.get(User,'admin')
        app.dependency_overrides[get_db]=session;app.dependency_overrides[get_current_user]=user
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            body={'revision':1,'references':refs}
            response=await client.post(f'/api/experiences/{rule.id}/field-comparison',json=body)
            assert response.status_code==200,response.text
            assert response.json()['result']['kind']=='real_case_field_comparison'
            response=await client.post(f'/api/experiences/{rule.id}/field-comparison',json={**body,'comparison':'boundary'})
            assert response.status_code==422
    asyncio.run(scenario(tmp_path,monkeypatch,check,RULE))
