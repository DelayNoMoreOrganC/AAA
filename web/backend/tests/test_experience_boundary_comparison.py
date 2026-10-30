"""Isolated storage/trace/API protocol tests, not case or model accuracy tests."""
import asyncio
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace as NS

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base, get_db
from app.models import Org, User, Role, Case, CaseFile, ArchiveTask, TaskStatus
from app.services import experience_boundary_comparison as service
from app.services.experience_rules import ExperienceError, freeze
from app.services.experience_sources import human_field_record
from app.services.experience_store import create_draft, transition, _receipt_passes
from app.services.task_sources import source_version
from agent_trace import digest, SCHEMA, TRACE_CURRENT, TRACE_RUNS

RULE = {'case_types':['civil'], 'document_kinds':['evidence'],
        'required_signals':['independent_title'], 'excluded_signals':['explicit_component_link'],
        'action':'separate_document', 'target_fields':[]}


def fields(manifest, snapshot, ranges):
    source=manifest[0]; path=source['path']
    payload={'_experience_policy':{'snapshot_sha256':snapshot['sha256']}, '_visual_boundary_review':[]}
    docs={f'd{i}':{'page_ids':[f'p{n}' for n in range(a,b+1)],'local_doc_id':i}
          for i,(a,b) in enumerate(ranges,1)}
    body={'schema':SCHEMA,'scope':{'sources':{path:{'sha256':source['sha256'],'page_count':4}},
        'pages':{f'p{n}':{'source_path':path,'page':n} for n in range(1,5)},'documents':docs},'payload':payload}
    mapping={key:doc['local_doc_id'] for key,doc in docs.items()}
    run={'run_id':digest(body),'body':body,'archive_document_ids_at_merge':mapping,'mapping_sha256':digest(mapping)}
    return {**deepcopy(payload),TRACE_CURRENT:run['run_id'],TRACE_RUNS:[run],
        '_agent_summary':{'provider':'deepseek','model':'deepseek-flash','workflow':'document_two_stage','analysis_version':'protocol-only'}}


async def setup(db,tmp_path,payload=None):
    db.add_all([Org(id='o',name='protocol'),Org(id='other',name='protocol')]);await db.flush()
    for name,org,role in [('admin','o',Role.admin),('ordinary','o',Role.lawyer),('outsider','other',Role.admin)]:
        db.add(User(id=name,org_id=org,username=name,hashed_password='unused',role=role,is_active=True))
    await db.flush()
    manifests=[]
    for i in range(1,4):
        # These bytes only exercise immutable source binding. No PDF parsing,
        # recognition or business truth is represented by this fixture.
        path=tmp_path/f'source-{i}.bin';path.write_bytes(f'protocol-source-{i}'.encode())
        manifest=[{'file_id':f'f{i}','path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                   'pages':4,'doc_type':'default','filename':'protocol-only.bin'}]
        manifests.append(manifest)
        db.add(Case(id=f'c{i}',org_id='o',title='protocol',case_type='civil',created_by='admin'))
        await db.flush()
        db.add(CaseFile(id=f'f{i}',case_id=f'c{i}',filename='protocol-only.bin',stored_name=path.name,doc_type='default'))
    version=source_version(manifests[0],'civil')
    record=human_field_record(NS(id=1,case_id='c1',revision=1,source_version=version),
        '案情简介','',actor_id='admin',org_id='o',edited_at='protocol-only')
    db.add(ArchiveTask(id=1,case_id='c1',created_by='admin',revision=2,status=TaskStatus.done,
        source_manifest=manifests[0],source_version=version,
        fields={'案情简介':'','_provenance':{'案情简介':[record]}},manual_fields={'案情简介':''}))
    await db.flush()
    rule=await create_draft(db,'admin',task_id=1,task_revision=2,decision_key='案情简介',
        source_kind='field',payload=payload or RULE,scope='firm')
    refs=[]
    for i in (2,3):
        manifest=manifests[i-1];version=source_version(manifest,'civil')
        expected=[[1,2],[3,4]] if i==2 else [[1,4]]
        for candidate in (False,True):
            # Candidate context is a protocol fixture, not a published rule or
            # an experimental-execution endpoint on the production station.
            rows=[NS(id=rule.id,revision=rule.revision,scope=rule.scope,payload=rule.payload,
                payload_digest=rule.payload_digest,state='active',org_id='o',case_id='c1')] if candidate else []
            snapshot=freeze(rows,org_id='o',case_id=f'c{i}')
            profile={'version':1,'provider':'deepseek','model':'deepseek-flash','workflow':'document_two_stage',
                'processing_mode':'deepseek_cloud','cloud_consent':True,'authorized_by':'admin',
                'authorized_source_version':version,'experience_snapshot':snapshot}
            db.add(ArchiveTask(id=i*10+int(candidate),case_id=f'c{i}',created_by='admin',revision=1,status=TaskStatus.done,
                source_manifest=manifest,source_version=version,execution_profile=profile,
                fields=fields(manifest,snapshot,expected if candidate else [[1,4]]),manual_fields={}))
        refs.append({'baseline_task_id':i*10,'baseline_revision':1,'candidate_task_id':i*10+1,'candidate_revision':1,
            'expected_applicable':i==2,'reference_reviewed':True,'documents':[{'file_id':f'f{i}','ranges':expected}]})
    await db.commit()
    return rule,refs


async def scenario(tmp_path,monkeypatch,check,payload=None):
    monkeypatch.setattr('app.config.ORGS_DIR',tmp_path)
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    try:
        async with engine.begin() as connection:await connection.run_sync(Base.metadata.create_all)
        sessions=async_sessionmaker(engine,expire_on_commit=False)
        async with sessions() as db:
            rule,refs=await setup(db,tmp_path,payload)
            await check(db,rule,refs)
    finally:await engine.dispose()


def test_computes_actual_boundaries_idempotently_without_publishing(tmp_path,monkeypatch):
    async def check(db,rule,refs):
        result=await service.run_comparison(db,'admin',rule.id,revision=1,references=refs)
        await db.commit()
        assert result.result['all_candidate_boundaries_resolved']
        assert result.result['samples'][0]['comparison']['improved_to_reference']
        assert not result.result['any_new_boundary_errors']
        assert not _receipt_passes(result,rule) and not result.result['publish_eligible']
        assert 'protocol-only.bin' not in json.dumps(result.result) and str(tmp_path) not in json.dumps(result.result)
        again=await service.run_comparison(db,'admin',rule.id,revision=1,references=refs)
        assert again.id==result.id
        with pytest.raises(ExperienceError,match='HELDOUT_VALIDATION_REQUIRED'):
            await transition(db,'admin',rule.id,target='validated',revision=1)
        assert rule.state=='draft'
    asyncio.run(scenario(tmp_path,monkeypatch,check))


@pytest.mark.parametrize('attack,code',[
    ('permission','FORBIDDEN'),('org','NOT_FOUND'),('revision','STALE_SOURCE'),
    ('consent','AUTHORIZATION_REQUIRED'),('profile','PROFILE_MISMATCH'),('policy','POLICY_MISMATCH'),
    ('running','TASK_NOT_READY'),('same_task','BOUNDARY_RESULT_INVALID'),('caller_pass','BOUNDARY_RESULT_INVALID')])
def test_rejects_invalid_comparisons_before_source_reads(tmp_path,monkeypatch,attack,code):
    async def check(db,rule,refs):
        who='ordinary' if attack=='permission' else 'outsider' if attack=='org' else 'admin'
        task=await db.get(ArchiveTask,21)
        if attack=='revision':refs[0]['candidate_revision']=99
        elif attack=='consent':task.execution_profile={**task.execution_profile,'cloud_consent':False}
        elif attack=='profile':task.execution_profile={**task.execution_profile,'_request_budget':{'version':1,'max_requests':9}}
        elif attack=='policy':
            baseline=await db.get(ArchiveTask,20)
            task.execution_profile={**task.execution_profile,'experience_snapshot':baseline.execution_profile['experience_snapshot']}
        elif attack=='running':task.status=TaskStatus.running
        elif attack=='same_task':refs[0]['candidate_task_id']=20
        elif attack=='caller_pass':refs[0]['passed']=True
        await db.flush()
        async def forbidden(*args):pytest.fail('invalid comparison must not read sources')
        monkeypatch.setattr(service,'_source_set',forbidden)
        with pytest.raises(ExperienceError,match=code):
            await service.run_comparison(db,who,rule.id,revision=1,references=refs)
    asyncio.run(scenario(tmp_path,monkeypatch,check))


def test_changed_source_bytes_reject_receipt(tmp_path,monkeypatch):
    async def check(db,rule,refs):
        (tmp_path/'source-2.bin').write_bytes(b'changed-protocol-bytes')
        with pytest.raises(ExperienceError,match='STALE_SOURCE'):
            await service.run_comparison(db,'admin',rule.id,revision=1,references=refs)
    asyncio.run(scenario(tmp_path,monkeypatch,check))


def test_task_edit_during_source_hashing_rejects_stale_result(tmp_path,monkeypatch):
    from sqlalchemy import update
    async def check(db,rule,refs):
        original=service._source_set
        async def change_during_read(db,task,case):
            result=await original(db,task,case)
            if task.id==31:
                await db.execute(update(ArchiveTask).where(ArchiveTask.id==21).values(revision=2)
                                 .execution_options(synchronize_session=False))
            return result
        monkeypatch.setattr(service,'_source_set',change_during_read)
        with pytest.raises(ExperienceError,match='STALE_SOURCE'):
            await service.run_comparison(db,'admin',rule.id,revision=1,references=refs)
    asyncio.run(scenario(tmp_path,monkeypatch,check))


def test_duplicate_source_bytes_cannot_masquerade_as_independent_case(tmp_path,monkeypatch):
    async def check(db,rule,refs):
        data=(tmp_path/'source-2.bin').read_bytes();(tmp_path/'source-3.bin').write_bytes(data)
        for task_id in (30,31):
            task=await db.get(ArchiveTask,task_id)
            task.source_manifest=[{**task.source_manifest[0],'sha256':hashlib.sha256(data).hexdigest()}]
            task.source_version=source_version(task.source_manifest,'civil')
            task.execution_profile={**task.execution_profile,'authorized_source_version':task.source_version}
            task.fields=fields(task.source_manifest,task.execution_profile['experience_snapshot'],[[1,4]])
        await db.flush()
        with pytest.raises(ExperienceError,match='OVERLAPPING_MATERIALS'):
            await service.run_comparison(db,'admin',rule.id,revision=1,references=refs)
    asyncio.run(scenario(tmp_path,monkeypatch,check))


def test_permission_revoked_during_hashing_cannot_install_comparison(tmp_path,monkeypatch):
    from sqlalchemy import update
    async def check(db,rule,refs):
        original=service._source_set
        async def revoke(db,task,case):
            result=await original(db,task,case)
            if task.id==31:
                await db.execute(update(User).where(User.id=='admin').values(is_active=False)
                                 .execution_options(synchronize_session=False))
            return result
        monkeypatch.setattr(service,'_source_set',revoke)
        with pytest.raises(ExperienceError,match='FORBIDDEN'):
            await service.run_comparison(db,'admin',rule.id,revision=1,references=refs)
    asyncio.run(scenario(tmp_path,monkeypatch,check))


def test_http_uses_existing_trace_comparison_and_rejects_pass_flag(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from httpx import AsyncClient,ASGITransport
    from app.routers.experiences import router
    from app.deps import get_current_user
    async def check(db,rule,refs):
        app=FastAPI();app.include_router(router)
        async def session():yield db
        async def user():return await db.get(User,'admin')
        app.dependency_overrides[get_db]=session;app.dependency_overrides[get_current_user]=user
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            response=await client.post(f'/api/experiences/{rule.id}/boundary-comparison',json={'revision':1,'references':refs})
            assert response.status_code==200,response.text
            assert response.json()['result']['all_candidate_boundaries_match']
            response=await client.post(f'/api/experiences/{rule.id}/boundary-comparison',json={'revision':1,'references':refs,'passed':True})
            assert response.status_code==422
    asyncio.run(scenario(tmp_path,monkeypatch,check))
