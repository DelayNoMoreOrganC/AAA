import pytest

from tests.test_file_import_api import upload_context, upload
from tests.test_document_classification import fixture_task
from app.models import ArchiveTask, TaskStatus
from app.routers import tasks
from app.services.preview_fields import build_preview
from app.services.analysis_snapshot import load_analysis, save_snapshot


def test_deliberate_blank_does_not_resurrect_alias():
    data = {"法院收案号": "", "案号": "旧案号",
            "_provenance": {"法院收案号": [{"method": "human", "value": ""}]}}
    fields = build_preview("送达材料清单", data)["fields"]
    assert next(f for f in fields if f["key"] == "法院收案号")["value"] == ""


@pytest.mark.asyncio
async def test_intake_date_save_is_scoped_and_survives_reload(upload_context, monkeypatch):
    ctx=upload_context
    task_id,work,_=await fixture_task(ctx,monkeypatch)
    url=f'/api/tasks/{task_id}/preview-fields/立案审批表'
    saved=await ctx.client.put(url,json={'expected_revision':1,'values':{'收案日期':'2026年1月5日'}})
    assert saved.status_code==200,saved.text
    assert saved.json()['fields']['立案审批日期']=='2026年1月5日'
    assert not saved.json()['fields'].get('收案日期')
    form=(await ctx.client.get(url)).json()
    row=next(r for r in form['fields'] if r['key']=='立案审批日期')
    assert row['value']=='2026年1月5日' and row['assurance']['status']=='human_confirmed'
    cover=(await ctx.client.get(f'/api/tasks/{task_id}/preview-fields/档案卷宗')).json()
    assert next(r for r in cover['fields'] if r['key']=='收案日期')['value']==''
    cleared=await ctx.client.put(url,json={'expected_revision':2,'values':{'立案审批日期':''}})
    assert cleared.status_code==200,cleared.text
    analysis,_=load_analysis(work)
    assert analysis.fields['立案审批日期']==''
    assert any(r['method']=='human' and r['value']=='' for r in analysis.fields['_provenance']['立案审批日期'])


@pytest.mark.asyncio
async def test_form_edit_compare_and_swap_preserves_unsent_metadata(upload_context, monkeypatch):
    ctx = upload_context
    task_id, work, _ = await fixture_task(ctx, monkeypatch)
    analysis, snap = load_analysis(work)
    styles = {"立案审批表": {"field:合同号": {"fontSize": "12pt"}}}
    customs = {"立案审批表": {"p0-b0-r6-c0": "旧人工内容"}}
    analysis.fields.update(_preview_styles=styles, _preview_custom_values=customs)
    save_snapshot(work, analysis, base_name="虚构测试", metadata=snap.get("workflow"))
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, task_id)
        task.fields = analysis.fields
        await db.commit()
    url = f"/api/tasks/{task_id}/preview-fields/立案审批表"
    initial = await ctx.client.get(url)
    assert initial.status_code == 200
    assert initial.json()["revision"] == 1 and initial.json()["editable"]
    saved = await ctx.client.put(url, json={"expected_revision": 1, "values": {"合同号": ""}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, task_id)
        assert task.fields["合同号"] == ""
        assert task.fields["_preview_styles"] == styles
        assert task.fields["_preview_custom_values"] == customs
    stale = await ctx.client.put(url, json={"expected_revision": 1, "values": {"合同号": "过期值"}})
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_form_history_and_running_states_are_readonly(upload_context, monkeypatch):
    ctx = upload_context
    task_id, _, _ = await fixture_task(ctx, monkeypatch)
    url = f"/api/tasks/{task_id}/preview-fields/立案审批表"
    monkeypatch.setattr(tasks.task_manager, "is_running", lambda *_: True)
    assert not (await ctx.client.get(url)).json()["editable"]
    assert (await ctx.client.put(url, json={"expected_revision": 1, "values": {"合同号": "x"}})).status_code == 409
    assert (await ctx.client.patch(f"/api/tasks/{task_id}/fields", json={"fields": {"合同号": "x"}})).status_code == 409
    monkeypatch.setattr(tasks.task_manager, "is_running", lambda *_: False)
    async with ctx.sessions() as db:
        db.add(ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.awaiting_review, parent_task_id=task_id))
        await db.commit()
    assert not (await ctx.client.get(url)).json()["editable"]
    assert (await ctx.client.put(url, json={"expected_revision": 1, "values": {"合同号": "x"}})).status_code == 409


@pytest.mark.asyncio
async def test_form_source_change_prevents_edit(upload_context, monkeypatch):
    ctx = upload_context
    task_id, _, _ = await fixture_task(ctx, monkeypatch)
    monkeypatch.setattr(tasks, "_source_changed", _changed)
    url = f"/api/tasks/{task_id}/preview-fields/立案审批表"
    assert not (await ctx.client.get(url)).json()["editable"]
    assert (await ctx.client.put(url, json={"expected_revision": 1, "values": {"合同号": "x"}})).status_code == 409


async def _changed(*_):
    return True


@pytest.mark.asyncio
async def test_first_clear_of_empty_canonical_overrides_nonempty_alias(upload_context, monkeypatch):
    ctx = upload_context
    task_id, work, _ = await fixture_task(ctx, monkeypatch)
    analysis, snap = load_analysis(work)
    analysis.fields.update({"委托人": "", "委托人名称": "虚构旧别名"})
    save_snapshot(work, analysis, base_name="虚构测试", metadata=snap.get("workflow"))
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, task_id)
        task.fields = analysis.fields
        await db.commit()
    url = f"/api/tasks/{task_id}/preview-fields/立案审批表"
    before = (await ctx.client.get(url)).json()
    assert next(f for f in before["fields"] if f["key"] == "委托人")["value"] == "虚构旧别名"
    saved = await ctx.client.put(url, json={"expected_revision": 1, "values": {"委托人": ""}})
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    after = (await ctx.client.get(url)).json()
    assert next(f for f in after["fields"] if f["key"] == "委托人")["value"] == ""
