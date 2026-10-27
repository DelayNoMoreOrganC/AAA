"""Existing saved wording must not change when editing an unrelated field."""
from copy import deepcopy
from types import SimpleNamespace
import hashlib
import pytest
from app.services import archive_service
from app.services.analysis_snapshot import save_snapshot,load_snapshot_data
from app.services.task_workflow import analysis_issues
from tests.test_form_drafts import prepared


def setup_old_task(tmp_path,monkeypatch,*,orphan=False,conflict=False):
    analysis,manifest=prepared(tmp_path)
    archive_service.refresh_form_drafts(analysis,{},manifest)
    # An earlier generator used a different, still evidence-backed wording.
    field='案件或项目名称';value='虚构甲公司虚构合同争议'
    analysis.fields[field]=value
    meta=analysis.fields['_form_drafts'];meta['version']=10
    meta['fields'][field]['value_digest']=hashlib.sha256(value.encode()).hexdigest()
    for ref in analysis.fields['_provenance'][field]:ref['value']=value
    if orphan:analysis.fields['_form_draft_sources'][field].append({'field':'案由','source_path':'outside.pdf','page':1})
    if conflict:analysis.fields['_field_conflicts']=[{'field':'委托人','values':['虚构甲公司','虚构乙公司']}]
    work=tmp_path/'work';save_snapshot(str(work),analysis,base_name='fiction')
    task=SimpleNamespace(id=101,fields=deepcopy(analysis.fields),manual_fields={},source_manifest=manifest,
        issues=analysis_issues(analysis,manifest),revision=1,output_pdf='old.pdf',
        artifacts={'valid':True},confirmation={'confirmed':True})
    monkeypatch.setattr(archive_service,'_work_dir_for',lambda *_:str(work))
    return task,work


@pytest.mark.asyncio
async def test_unrelated_edit_preserves_saved_wording_provenance_and_explains_generator_version(tmp_path,monkeypatch):
    task,work=setup_old_task(tmp_path,monkeypatch)
    before=deepcopy(task.fields)
    result=await archive_service.update_task_fields(task,'synthetic-org',{'立卷人':'虚构验收员'},actor_id='tester')
    assert {k for k in set(before)|set(result) if not k.startswith('_') and before.get(k)!=result.get(k)}=={'立卷人'}
    for field in ('案件或项目名称','案情简介','法院文件清单','委托人联系地址及电话'):
        assert result['_provenance'].get(field)==before['_provenance'].get(field)
        assert result['_form_draft_sources'][field]==before['_form_draft_sources'][field]
    assert result['_form_drafts']['fields']['案件或项目名称']['generator_version']==10
    assert task.revision==2 and task.confirmation is None
    assert load_snapshot_data(str(work))['fields']==result


@pytest.mark.asyncio
async def test_relevant_identity_edit_recomputes_dependent_name_and_summary(tmp_path,monkeypatch):
    task,_=setup_old_task(tmp_path,monkeypatch)
    result=await archive_service.update_task_fields(task,'synthetic-org',{'委托人':'虚构乙公司'},actor_id='tester')
    assert result['案件或项目名称']=='虚构乙公司：虚构合同争议'
    assert '虚构乙公司' in result['案情简介'] and '虚构甲公司' not in result['案情简介']


@pytest.mark.asyncio
async def test_explicit_manual_clear_wins_over_old_generated_name(tmp_path,monkeypatch):
    task,_=setup_old_task(tmp_path,monkeypatch)
    result=await archive_service.update_task_fields(task,'synthetic-org',{'案件或项目名称':''},actor_id='tester')
    assert result['案件或项目名称']==''
    assert result['_form_drafts']['fields']['案件或项目名称']['status']=='human_modified'


@pytest.mark.asyncio
async def test_old_unsupported_reference_does_not_receive_preservation_exception(tmp_path,monkeypatch):
    task,_=setup_old_task(tmp_path,monkeypatch,orphan=True)
    result=await archive_service.update_task_fields(task,'synthetic-org',{'立卷人':'虚构验收员'},actor_id='tester')
    assert result['案件或项目名称']=='虚构甲公司：虚构合同争议'
    assert all(ref.get('source_path')!='outside.pdf' for ref in result['_form_draft_sources']['案件或项目名称'])


@pytest.mark.asyncio
async def test_unresolved_conflict_prevents_restoring_nonempty_old_draft(tmp_path,monkeypatch):
    task,_=setup_old_task(tmp_path,monkeypatch,conflict=True)
    result=await archive_service.update_task_fields(task,'synthetic-org',{'立卷人':'虚构验收员'},actor_id='tester')
    assert not result.get('案件或项目名称')
    assert result['_form_drafts']['fields']['案件或项目名称']['status']=='insufficient'


@pytest.mark.asyncio
async def test_later_relevant_change_after_unrelated_save_still_recomputes(tmp_path,monkeypatch):
    task,_=setup_old_task(tmp_path,monkeypatch)
    await archive_service.update_task_fields(task,'synthetic-org',{'立卷人':'虚构验收员'},actor_id='tester')
    result=await archive_service.update_task_fields(task,'synthetic-org',{'案由':'虚构咨询事项'},actor_id='tester')
    assert result['案件或项目名称']=='虚构甲公司：虚构咨询事项'
    assert result['立卷人']=='虚构验收员' and task.revision==3
