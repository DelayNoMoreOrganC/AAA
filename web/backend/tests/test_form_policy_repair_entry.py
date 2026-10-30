"""Entry/restart contracts only. No real-case, provider or OCR accuracy tests."""
from copy import deepcopy
from types import SimpleNamespace as NS
import pytest
from sqlalchemy import select
from tests.test_file_import_api import upload_context, upload
from tests.test_task_workflow import capture_start, wire_storage, fixture_analysis
from tests.test_form_synthesis_integration import make
from app.models import ArchiveTask, CaseFile, TaskStatus
from app.routers import tasks
from app.services import form_policy_repair as repair, execution_profile
from app.services.analysis_snapshot import save_snapshot, task_work_dir
from app.services.task_sources import source_version, build_source_manifest
from app import config
import form_synthesis as synthesis


def parent_fixture(tmp_path, monkeypatch):
    fields, manifest, units = make(tmp_path)
    manifest[0].update(doc_type='default',filename='protocol.pdf')
    from case_outcome import STRICT_EVIDENCE_VERSION
    from visual_archive_agent import VISUAL_ANALYSIS_VERSION
    fields['_field_normalization_version'] = STRICT_EVIDENCE_VERSION
    fields['_agent_summary'] = dict(visual=True,model='deepseek-flash',workflow='document_two_stage',
                                    analysis_version=VISUAL_ANALYSIS_VERSION)
    profile = dict(version=1, processing_mode='deepseek_cloud',provider='deepseek',
                   model='deepseek-flash',workflow='document_two_stage')
    parent = NS(id=1,revision=1,case_id='fixture',fields=fields,manual_fields={},issues=[],order_mode='catalog',
                execution_profile=profile,source_manifest=manifest,source_version=source_version(manifest,'nonlit'))
    analysis=fixture_analysis(manifest[0]['path'],deepcopy(fields));analysis.case_type='nonlit';analysis.doc_spans=units
    monkeypatch.setattr(config,'ORGS_DIR',tmp_path/'orgs')
    save_snapshot(task_work_dir('org1','fixture',1),analysis,base_name='protocol',
                  metadata={'source_version':parent.source_version})
    original=synthesis._cell_contract
    monkeypatch.setattr(synthesis,'_cell_contract',lambda key,kind:
        {**original(key,kind),'revision_test':2} if key=='结案小结' else original(key,kind))
    return parent


def test_budget_incomplete_parent_cannot_offer_a_fresh_repair_budget(tmp_path,monkeypatch):
    parent=parent_fixture(tmp_path,monkeypatch)
    assert repair.load_repair_parent(parent,'org1',case_type='nonlit') is not None
    parent.fields['_request_budget_stop']={'status':'incomplete','phase':'form_synthesis',
        'budget':{'max_requests':20,'reserved_requests':20}}
    from app.services.analysis_snapshot import update_snapshot_fields
    update_snapshot_fields(task_work_dir('org1','fixture',1),parent.fields)
    assert repair.load_repair_parent(parent,'org1',case_type='nonlit') is None
    assert parent.fields['_request_budget_stop']['budget']['reserved_requests']==20


def test_readonly_plan_checks_actual_snapshot_and_preserves_manual_blank(tmp_path,monkeypatch):
    parent=parent_fixture(tmp_path,monkeypatch);before=deepcopy(parent.fields)
    saved=repair.load_repair_parent(parent,'org1',case_type='nonlit')
    assert saved is not None and parent.fields==before
    assert synthesis.policy_repair_targets(saved[0].fields,{},parent.source_manifest,saved[0].doc_spans)==['结案小结']
    parent.manual_fields={'结案小结':''}
    assert repair.load_repair_parent(parent,'org1',case_type='nonlit') is None


def test_public_plan_token_tracks_fields_revision_and_current_rule(tmp_path,monkeypatch):
    parent=parent_fixture(tmp_path,monkeypatch)
    saved=repair.load_repair_parent(parent,'org1',case_type='nonlit')
    first=repair.public_repair_plan(parent,saved)
    assert first['fields']==['结案小结'] and len(first['token'])==64
    assert repair.public_repair_plan(parent,saved)==first
    parent.revision+=1
    second=repair.public_repair_plan(parent,saved)
    assert second['token']!=first['token']
    parent.fields['承办律师']='human edit'
    assert repair.public_repair_plan(parent,saved)['token']!=second['token']


def test_successful_past_repair_does_not_disable_later_rule_updates(tmp_path,monkeypatch):
    parent=parent_fixture(tmp_path,monkeypatch)
    parent.fields['_form_policy_repair']={'status':'generated','unaccepted_targets':[]}
    from app.services.analysis_snapshot import update_snapshot_fields
    update_snapshot_fields(task_work_dir('org1','fixture',1),parent.fields)
    assert repair.load_repair_parent(parent,'org1',case_type='nonlit') is not None
    parent.fields['_form_policy_repair']['status']='partially_repaired'
    update_snapshot_fields(task_work_dir('org1','fixture',1),parent.fields)
    assert repair.load_repair_parent(parent,'org1',case_type='nonlit') is None


def test_saved_partial_update_offers_only_newly_changed_rejected_rule(tmp_path,monkeypatch):
    from tests.test_form_policy_repair_job import Writer
    from app.services.task_workflow import mark_snapshot_metrics_reused
    from app.services.analysis_snapshot import update_snapshot_fields
    parent=parent_fixture(tmp_path,monkeypatch)
    parent.created_by='user1'
    analysis,manual,issues=repair.load_repair_parent(parent,'org1',case_type='nonlit')
    old_contract=synthesis._cell_contract
    monkeypatch.setattr(synthesis,'_cell_contract',lambda field,kind:{**old_contract(field,kind),'revision':2})
    mark_snapshot_metrics_reused(analysis)
    cfg={'extraction':{'mode':'visual_agent'},'vision':{'provider':'deepseek','model':'deepseek-flash','workflow':'document_two_stage'},
         'privacy':{'mode':'cloud','cloud_authorized':True}}
    monkeypatch.setattr(repair,'_client',lambda _:Writer())
    result=repair.repair_policy_cells(analysis,parent,cfg,'org1',manual,issues)
    assert result['status']=='partially_repaired'
    parent.fields=deepcopy(analysis.fields)
    update_snapshot_fields(task_work_dir('org1','fixture',1),parent.fields)
    assert repair.load_repair_parent(parent,'org1',case_type='nonlit') is None
    monkeypatch.setattr(synthesis,'_cell_contract',lambda field,kind:{**old_contract(field,kind),
        'revision':3 if field=='审（办）结果' else 2})
    saved=repair.load_repair_parent(parent,'org1',case_type='nonlit')
    assert saved is not None
    assert repair.public_repair_plan(parent,saved)['fields']==['审（办）结果']
    parent.manual_fields['审（办）结果']=''
    assert repair.load_repair_parent(parent,'org1',case_type='nonlit') is None


@pytest.mark.parametrize('reason',['old_algorithm','other_case_type','changed_snapshot','attempted','wrong_org'])
def test_plan_never_widens_to_reclassification(tmp_path,monkeypatch,reason):
    parent=parent_fixture(tmp_path,monkeypatch)
    if reason=='old_algorithm':
        parent.fields['_agent_summary']['analysis_version']='old'
        from app.services.analysis_snapshot import update_snapshot_fields
        update_snapshot_fields(task_work_dir('org1','fixture',1),parent.fields)
    if reason=='changed_snapshot':parent.fields['委托人']='manually changed without commit'
    if reason=='attempted':parent.fields['_form_policy_repair']={'status':'provider_failed'}
    assert repair.load_repair_parent(parent,'wrong' if reason=='wrong_org' else 'org1',
        case_type='civil' if reason=='other_case_type' else 'nonlit') is None


async def api_parent(ctx,monkeypatch):
    wire_storage(ctx,monkeypatch);await upload(ctx)
    async with ctx.sessions() as db:
        files=(await db.scalars(select(CaseFile))).all();manifest=build_source_manifest(files)
        version=source_version(manifest,'civil')
        profile=dict(version=1,processing_mode='deepseek_cloud',provider='deepseek',model='deepseek-flash',
            workflow='document_two_stage',cloud_consent=True,authorized_source_version=version,authorized_by='test-user')
        parent=ArchiveTask(case_id='case-a',status=TaskStatus.awaiting_review,source_manifest=manifest,
            source_version=version,created_by='test-user',execution_profile=profile,fields={},manual_fields={'合同号':''},
            idempotency_key='original',confirmation={'revision':1},phase='needs_input')
        db.add(parent);await db.commit()
    async def settings(*args):return {'processing_mode':'deepseek_cloud'}
    monkeypatch.setattr(tasks,'load_user_settings',settings)
    monkeypatch.setattr(execution_profile,'load_user_settings',settings)
    monkeypatch.setattr(execution_profile,'external_ai_allowed',lambda:True)
    # Separate tests above exercise actual source/field eligibility. Here only
    # scheduling, consent, idempotency and persistence are under test.
    monkeypatch.setattr(repair,'load_repair_parent',lambda *a,**kw: ('eligible',{},[]))
    monkeypatch.setattr(repair,'public_repair_plan',lambda *a,**kw:{'available':True,'token':'a'*64,'fields':['结案小结']})
    return parent


@pytest.mark.asyncio
async def test_generate_stale_forms_creates_one_child_and_preserves_parent(upload_context,monkeypatch,capture_start):
    ctx=upload_context;parent=await api_parent(ctx,monkeypatch)
    body={'cloud_consent':True,'expected_processing_mode':'deepseek_cloud','form_policy_token':'a'*64,'idempotency_key':'repair-new'}
    response=await ctx.client.post('/api/cases/case-a/generate',json=body)
    assert response.status_code==201,response.text
    child_id=response.json()['id'];assert child_id!=parent.id
    for key in ['repair-new','another-click']:
        again=await ctx.client.post('/api/cases/case-a/generate',json={**body,'idempotency_key':key})
        assert again.json()['id']==child_id
    assert capture_start==[child_id]
    async with ctx.sessions() as db:
        old=await db.get(ArchiveTask,parent.id);child=await db.get(ArchiveTask,child_id)
        assert child.requested_operation==repair.OPERATION and child.parent_task_id==old.id
        assert child.execution_profile['_form_policy_plan']=={'token':'a'*64,'fields':['结案小结']}
        assert child.manual_fields=={'合同号':''} and child.confirmation is None
        assert old.confirmation=={'revision':1} and old.status==TaskStatus.awaiting_review


@pytest.mark.asyncio
async def test_no_new_cloud_consent_no_job_and_old_idempotency_still_returns_old(upload_context,monkeypatch,capture_start):
    ctx=upload_context;parent=await api_parent(ctx,monkeypatch)
    response=await ctx.client.post('/api/cases/case-a/generate',json={'expected_processing_mode':'deepseek_cloud','form_policy_token':'a'*64})
    assert response.status_code==409,response.text
    repeated=await ctx.client.post('/api/cases/case-a/generate',json={'idempotency_key':'original'})
    assert repeated.status_code==201 and repeated.json()['id']==parent.id
    assert not capture_start


@pytest.mark.asyncio
async def test_resume_requires_new_consent_and_enters_same_bounded_operation(upload_context,monkeypatch,capture_start):
    ctx=upload_context;parent=await api_parent(ctx,monkeypatch)
    url=f'/api/tasks/{parent.id}/resume'
    denied=await ctx.client.post(url,json={'expected_processing_mode':'deepseek_cloud','form_policy_token':'a'*64})
    assert denied.status_code==409 and not capture_start
    response=await ctx.client.post(url,json={'cloud_consent':True,'expected_processing_mode':'deepseek_cloud','form_policy_token':'a'*64})
    assert response.status_code==200,response.text
    assert response.json()['parent_task_id']==parent.id and capture_start==[response.json()['id']]
    again=await ctx.client.post(url,json={'cloud_consent':True,'expected_processing_mode':'deepseek_cloud','form_policy_token':'a'*64})
    assert again.json()['id']==response.json()['id'] and len(capture_start)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[TaskStatus.done,TaskStatus.failed,TaskStatus.awaiting_review])
async def test_lost_resume_response_recovers_exact_child_without_new_consent_or_execution(upload_context,monkeypatch,capture_start,status):
    ctx=upload_context;parent=await api_parent(ctx,monkeypatch)
    url=f'/api/tasks/{parent.id}/resume'
    response=await ctx.client.post(url,json={'cloud_consent':True,
        'expected_processing_mode':'deepseek_cloud','form_policy_token':'a'*64})
    assert response.status_code==200,response.text
    child_id=response.json()['id']
    async with ctx.sessions() as db:
        child=await db.get(ArchiveTask,child_id)
        child.status=status;child.requested_operation='draft'
        await db.commit()
    recovered=await ctx.client.post(url,json={'cloud_consent':False,
        'expected_processing_mode':'deepseek_cloud','form_policy_token':'a'*64})
    assert recovered.status_code==200,recovered.text
    assert recovered.json()['id']==child_id and recovered.json()['status']==status.value
    assert capture_start==[child_id]
    async with ctx.sessions() as db:
        assert len((await db.scalars(select(ArchiveTask))).all())==2
        assert (await db.get(ArchiveTask,parent.id)).confirmation=={'revision':1}


@pytest.mark.asyncio
@pytest.mark.parametrize('mismatch',['token','parent','source','mode'])
async def test_resume_does_not_recover_unrelated_child_or_start_another(upload_context,monkeypatch,capture_start,mismatch):
    ctx=upload_context;parent=await api_parent(ctx,monkeypatch)
    url=f'/api/tasks/{parent.id}/resume'
    body={'cloud_consent':True,'expected_processing_mode':'deepseek_cloud','form_policy_token':'a'*64}
    response=await ctx.client.post(url,json=body)
    assert response.status_code==200,response.text
    child_id=response.json()['id']
    async with ctx.sessions() as db:
        child=await db.get(ArchiveTask,child_id)
        if mismatch=='parent':child.parent_task_id=None
        if mismatch=='source':child.source_version='different-source'
        if mismatch=='mode':child.execution_profile={**child.execution_profile,'processing_mode':'ollama_local'}
        await db.commit()
    recovered=await ctx.client.post(url,json={**body,'form_policy_token':('b' if mismatch=='token' else 'a')*64})
    assert recovered.status_code==200,recovered.text
    assert recovered.json()['id']==parent.id and capture_start==[child_id]


@pytest.mark.asyncio
async def test_ineligible_snapshot_reuses_old_without_provider_or_new_job(upload_context,monkeypatch,capture_start):
    ctx=upload_context;parent=await api_parent(ctx,monkeypatch)
    monkeypatch.setattr(repair,'load_repair_parent',lambda *a,**kw:None)
    response=await ctx.client.post('/api/cases/case-a/generate',json={})
    assert response.status_code==201 and response.json()['id']==parent.id
    assert not capture_start


@pytest.mark.asyncio
async def test_get_projects_shared_plan_without_starting_or_mutating(upload_context,monkeypatch,capture_start):
    ctx=upload_context;parent=await api_parent(ctx,monkeypatch)
    current=await ctx.client.get(f'/api/tasks/{parent.id}')
    assert current.status_code==200,current.text
    plan=current.json()['form_policy_update']
    assert plan=={'available':True,'token':'a'*64,'fields':['结案小结']}
    assert current.json()['can_resume'] is True
    case=await ctx.client.get('/api/cases/case-a')
    assert case.json()['last_task_summary']['form_policy_update']==plan
    denied=await ctx.client.get(f'/api/tasks/{parent.id}',headers={'X-Test-Org':'org-b'})
    assert denied.status_code==404 and not capture_start
    async with ctx.sessions() as db:
        old=await db.get(ArchiveTask,parent.id)
        assert old.fields=={} and old.confirmation=={'revision':1}
        assert len((await db.scalars(select(ArchiveTask))).all())==1


@pytest.mark.asyncio
@pytest.mark.parametrize('token',[None,'b'*64])
async def test_missing_or_stale_plan_cannot_start_repair(upload_context,monkeypatch,capture_start,token):
    ctx=upload_context;parent=await api_parent(ctx,monkeypatch)
    response=await ctx.client.post(f'/api/tasks/{parent.id}/resume',json={
        'cloud_consent':True,'expected_processing_mode':'deepseek_cloud','form_policy_token':token})
    assert response.status_code==409 and not capture_start


@pytest.mark.asyncio
async def test_repair_token_cannot_expand_into_changed_material_recognition(upload_context,monkeypatch,capture_start):
    ctx=upload_context;parent=await api_parent(ctx,monkeypatch)
    await upload(ctx,name='new.pdf')
    response=await ctx.client.post(f'/api/tasks/{parent.id}/resume',json={
        'cloud_consent':True,'expected_processing_mode':'deepseek_cloud','form_policy_token':'a'*64})
    assert response.status_code==409 and not capture_start


@pytest.mark.asyncio
async def test_failed_repair_is_not_silently_replaced_by_full_analysis(upload_context,monkeypatch,capture_start):
    ctx=upload_context;parent=await api_parent(ctx,monkeypatch)
    async with ctx.sessions() as db:
        task=await db.get(ArchiveTask,parent.id);task.status=TaskStatus.failed;task.requested_operation=repair.OPERATION
        await db.commit()
    response=await ctx.client.post('/api/cases/case-a/generate',json={
        'cloud_consent':True,'expected_processing_mode':'deepseek_cloud','form_policy_token':'a'*64})
    assert response.status_code==201 and response.json()['id']==parent.id
    assert not capture_start


@pytest.mark.asyncio
@pytest.mark.parametrize('eligible,plan_changed',[(True,False),(False,False),(True,True)])
async def test_job_dispatch_repairs_or_stops_without_full_recognition(upload_context,monkeypatch,capture_start,eligible,plan_changed):
    from app.services import archive_service
    ctx=upload_context;parent=await api_parent(ctx,monkeypatch)
    response=await ctx.client.post('/api/cases/case-a/generate',json={
        'cloud_consent':True,'expected_processing_mode':'deepseek_cloud','form_policy_token':'a'*64})
    child_id=response.json()['id']
    async with ctx.sessions() as db:files=(await db.scalars(select(CaseFile))).all()
    analysis=fixture_analysis(files[0].abs_path,{'合同号':''})
    monkeypatch.setattr(repair,'load_repair_parent',lambda *a,**kw:(analysis,{'合同号':''},[]) if eligible else None)
    if plan_changed:
        monkeypatch.setattr(repair,'public_repair_plan',lambda *a,**kw:{'available':True,'token':'b'*64,'fields':['结案小结']})
    async def context(*args):return NS(case_type='civil'),files,{}
    async def frozen(*args,**kwargs):return {'extraction':{'mode':'visual_agent'}}
    async def forbidden(*args,**kwargs):pytest.fail('repair must not classify/OCR/recheck model availability')
    monkeypatch.setattr(archive_service,'_load_case_context',context)
    monkeypatch.setattr(archive_service,'task_config',frozen)
    monkeypatch.setattr(archive_service,'run_word',forbidden)
    monkeypatch.setattr(archive_service,'check_readiness',forbidden)
    monkeypatch.setattr(archive_service,'get_settings',lambda:NS(preview_only=True))
    repaired=[];assembled=[]
    def repair_stub(a,*args,**kwargs):
        assert a.fields['_analysis_metrics']['analysis_status']=='snapshot_reused'
        repaired.append(True)
        a.fields['_form_policy_repair']={'status':'generated'}
    async def assemble(*args,**kwargs):assembled.append((args,kwargs))
    monkeypatch.setattr(repair,'repair_policy_cells',repair_stub)
    monkeypatch.setattr(archive_service,'run_assemble',assemble)
    await archive_service.run_archive(child_id,'case-a','org-a','test-user')
    async with ctx.sessions() as db:
        child=await db.get(ArchiveTask,child_id);old=await db.get(ArchiveTask,parent.id)
        assert old.confirmation=={'revision':1} and old.fields=={}
        if eligible and not plan_changed:
            assert child.checkpoint=='analyzed',child.error
            assert repaired==[True] and len(assembled)==1
            assert assembled[0][1]['draft'] is True
            assert child.requested_operation=='draft' and child.manual_fields=={'合同号':''}
            assert child.confirmation is None
        else:
            assert child.status==TaskStatus.failed and not repaired and not assembled
