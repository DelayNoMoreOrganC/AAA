"""Synthetic ASGI tests: model selection is mocked; adoption uses real persistence."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_case_assistant import context
from tests.test_file_import_api import upload_context, upload
from app.models import ArchiveTask, Case, CaseFile, TaskStatus
from app.security import _create_token, decode_token
from app.services import case_assistant as service
from app.services import assistant_proposal as proposals
from app.services.analysis_snapshot import load_snapshot_data, snapshot_path, _atomic_write


def command(field="合同号", value="虚构合同2"):
    return {"tool": proposals.PROPOSAL_TOOL, "field": field, "query": "", "value": value}


async def suggest(ctx, monkeypatch, selected=None, message="请把合同号改为虚构合同2"):
    monkeypatch.setattr(service, "select_tool", lambda *_: selected or command())
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()["proposal"]


async def apply(ctx, proposal, **kwargs):
    return await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant/proposals/apply",
        json={"proposal_token": proposal["proposal_token"], "expected_revision": proposal["revision"]}, **kwargs)


@pytest.mark.asyncio
async def test_real_adoption_updates_snapshot_manual_provenance_and_invalidates_confirmation(context, monkeypatch):
    ctx = context
    old_output = ctx.work / "previous-published.pdf"
    old_output.write_bytes(b"synthetic old result must remain")
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        task.output_pdf = str(old_output)
        task.confirmation = {"revision": 3, "source_version": task.source_version}
        task.artifacts = {"valid": True}
        await db.commit()
    original = load_snapshot_data(str(ctx.work))
    proposal = await suggest(ctx, monkeypatch)
    assert proposal["before"] == "虚构合同1" and proposal["after"] == "虚构合同2"
    assert "人工" in proposal["reason"]
    assert load_snapshot_data(str(ctx.work)) == original
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        assert task.fields == ctx.original_fields and task.revision == 3
    # Adoption must not make a second model request.
    monkeypatch.setattr(service, "select_tool", lambda *_: pytest.fail("Adoption must not call a model"))
    response = await apply(ctx, proposal)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["applied"] and result["proposal_id"] == proposal["id"]
    assert result["task"]["revision"] == 4 and result["task"]["status"] == "awaiting_review"
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        assert task.fields["合同号"] == task.manual_fields["合同号"] == "虚构合同2"
        assert task.confirmation is None and task.artifacts is None and not task.output_pdf
        provenance = task.fields["_provenance"]["合同号"][-1]
        assert provenance["method"] == "human" and provenance["actor_id"] == "test-user"
        assert provenance["value"] == "虚构合同2" and "quote" not in provenance
        assert task.issues[0]["kind"] == "ocr"  # Unrelated issue must survive.
        assert load_snapshot_data(str(ctx.work))["fields"] == task.fields
    assert old_output.read_bytes() == b"synthetic old result must remain"
    after = load_snapshot_data(str(ctx.work))
    replay = await apply(ctx, proposal)
    assert replay.status_code == 200 and replay.json()["already_applied"] is True
    assert load_snapshot_data(str(ctx.work)) == after


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,expected", [({"X-Test-User":"peer"},404),
    ({"X-Test-Org":"org-b","X-Test-Role":"admin"},404),
    ({"X-Test-User":"another-admin","X-Test-Role":"admin"},409)])
async def test_adoption_acl_and_originating_user_binding(context, monkeypatch, headers, expected):
    proposal = await suggest(context, monkeypatch)
    before = load_snapshot_data(str(context.work))
    assert (await apply(context, proposal, headers=headers)).status_code == expected
    assert load_snapshot_data(str(context.work)) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "field_without_revision", "new_source", "source_bytes", "stage", "running", "worker"])
async def test_stale_or_running_adoption_does_not_modify(context, monkeypatch, change):
    ctx = context
    proposal = await suggest(ctx, monkeypatch)
    before = load_snapshot_data(str(ctx.work))
    if change == "new_source":
        await upload(ctx, name="虚构补件.pdf")
    elif change == "worker":
        from app.routers.assistant import task_manager
        monkeypatch.setattr(task_manager, "is_running", lambda task_id: task_id == ctx.task_id)
    else:
        async with ctx.sessions() as db:
            task = await db.get(ArchiveTask, ctx.task_id)
            if change == "revision": task.revision += 1
            elif change == "field_without_revision": task.fields = dict(task.fields, 案由="虚构新案由")
            elif change == "running": task.status = TaskStatus.running
            elif change == "stage": (await db.get(Case, "case-a")).stage = "execution"
            elif change == "source_bytes":
                from pathlib import Path
                path = Path((await db.get(CaseFile, ctx.file_id)).abs_path)
                path.write_bytes(path.read_bytes() + b"synthetic byte change")
            await db.commit()
    assert (await apply(ctx, proposal)).status_code == 409
    assert load_snapshot_data(str(ctx.work)) == before


@pytest.mark.asyncio
async def test_expiry_tampering_and_wrong_task_are_rejected(context, monkeypatch):
    ctx = context
    proposal = await suggest(ctx, monkeypatch)
    payload = decode_token(proposal["proposal_token"])
    payload.pop("exp"); payload.pop("iat"); payload.pop("sub"); payload.pop("type")
    expired = _create_token("test-user", datetime.now(timezone.utc)-timedelta(seconds=1), "assistant_proposal", payload)
    for token in (expired, proposal["proposal_token"] + "tampered"):
        assert (await apply(ctx, dict(proposal, proposal_token=token))).status_code == 409
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        other = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.awaiting_review,
            source_manifest=task.source_manifest, source_version=task.source_version, fields=task.fields, revision=3)
        db.add(other); await db.commit(); other_id = other.id
    response = await ctx.client.post(f"/api/tasks/{other_id}/assistant/proposals/apply",
        json={"proposal_token":proposal["proposal_token"], "expected_revision":3})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_snapshot_mismatch_and_client_value_override_cannot_smuggle_changes(context, monkeypatch):
    ctx = context
    proposal = await suggest(ctx, monkeypatch)
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant/proposals/apply", json={
        "proposal_token":proposal["proposal_token"], "expected_revision":3, "after":"injected"})
    assert response.status_code == 422
    data = load_snapshot_data(str(ctx.work)); data["fields"]["案由"] = "uncommitted synthetic field"
    _atomic_write(snapshot_path(str(ctx.work)), data)
    assert (await apply(ctx, proposal)).status_code == 409
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        assert "案由" not in task.fields and task.revision == 3


@pytest.mark.asyncio
async def test_commit_failure_restores_snapshot_and_same_proposal_can_retry(context, monkeypatch):
    ctx = context
    proposal = await suggest(ctx, monkeypatch)
    before = load_snapshot_data(str(ctx.work))
    real_commit = AsyncSession.commit
    async def fail_commit(self): raise OSError("synthetic storage failure must not leak")
    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    response = await apply(ctx, proposal)
    assert response.status_code == 503 and "synthetic storage" not in response.text
    assert load_snapshot_data(str(ctx.work)) == before
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        assert task.fields == ctx.original_fields and task.revision == 3
    monkeypatch.setattr(AsyncSession, "commit", real_commit)
    assert (await apply(ctx, proposal)).status_code == 200


@pytest.mark.parametrize("field,value,message", [
    ("_rule_readiness","true","请把_rule_readiness改为true"),
    ("审批意见","同意","请把审批意见改为同意"),
    ("委托人对服务质量意见","满意","请把委托人对服务质量意见改为满意"),
    ("合同号","来自原件的未请求值","请把合同号改为虚构合同2"),
    ("合同号","虚构合同2","合同号来自哪里？"),
    ("合同号","虚构合同2","不要把合同号改为虚构合同2"),
    ("合同号","","请把合同号改为虚构合同2"),
])
def test_selector_rejects_hidden_unrequested_or_unauthorized_edits(field, value, message):
    with pytest.raises(service.AssistantUnavailable):
        service.validate_command(command(field, value), list(proposals.EDITABLE_FIELDS), message)


@pytest.mark.asyncio
async def test_clear_is_explicit_and_noop_does_not_issue_a_ticket(context, monkeypatch):
    ctx = context
    monkeypatch.setattr(service, "select_tool", lambda *_: command(value="虚构合同1"))
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":"合同号改为虚构合同1"})
    assert response.status_code == 200 and "proposal" not in response.json()
    proposal = await suggest(ctx, monkeypatch, command(value=""), "请清空合同号")
    assert proposal["after"] == ""
    assert (await apply(ctx, proposal)).json()["task"]["fields"]["合同号"] == ""


def test_local_model_can_select_proposal_but_never_receives_case_values(monkeypatch):
    import requests
    captured = {}
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices":[{"message":{"content":json.dumps(command())}}]}
    class Client:
        trust_env = True
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def post(self, url, **kwargs): captured.update(kwargs); return Response()
    monkeypatch.setattr(requests, "Session", Client)
    result = service.select_tool({"deepseek":{"base_url":"http://127.0.0.1:11434/v1","model":"synthetic","local_only":True}},
        "请把合同号改为虚构合同2", [], {"合同号":"PRIVATE_SYNTHETIC_SOURCE_VALUE"})
    assert result == command()
    assert "PRIVATE_SYNTHETIC_SOURCE_VALUE" not in json.dumps(captured)
    assert proposals.PROPOSAL_TOOL in captured["json"]["response_format"]["json_schema"]["schema"]["properties"]["tool"]["enum"]


@pytest.mark.asyncio
async def test_authorized_deepseek_selector_can_propose_and_adopt_without_second_cloud_call(context, monkeypatch):
    from tests.test_deepseek_cloud import configure, SECRET
    from app.config import get_settings
    from app.services import execution_profile as profiles
    import deepseek_vision_client
    ctx = context
    await configure(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        task.execution_profile = await profiles.make_profile(db, "test-user", task.source_version,
            cloud_consent=True, expected_mode="deepseek_cloud")
        await db.commit()
    calls = []
    def choose(self, messages):
        calls.append(messages)
        assert self._api_key == SECRET
        return command("委托人", "虚构新客户")
    monkeypatch.setattr(deepseek_vision_client.DeepSeekVisionClient, "complete", choose)
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":"请把委托人改为虚构新客户"})
    assert response.status_code == 200 and SECRET not in response.text
    assert "人工核对甲" not in json.dumps(calls, ensure_ascii=False)
    proposal = response.json()["proposal"]
    response = await apply(ctx, proposal)
    assert response.status_code == 200 and len(calls) == 1
    assert response.json()["task"]["fields"]["委托人"] == "虚构新客户"
    # Saved provenance keeps the historical quote but clearly labels it historical.
    monkeypatch.setattr(service, "select_tool", lambda *_: {"tool":"explain_field","query":"","field":"委托人"})
    checked = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":"委托人依据在哪里"})
    assert checked.status_code == 200
    assert any(item["title"] == "人工填写" and "没有自动原文依据" in item["text"] for item in checked.json()["items"])
    assert any(item["title"].startswith("历史摘录") for item in checked.json()["items"])


@pytest.mark.asyncio
async def test_concurrent_adoptions_save_only_one_revision(context, monkeypatch):
    import asyncio
    from app.routers.assistant import task_manager
    # pytest creates a fresh loop per test; production runs one ASGI loop.
    # Keep one shared real lock for both requests, but not a lock previously
    # bound by another test's contention in an already-closed event loop.
    monkeypatch.setattr(task_manager, "_case_locks", {})
    ctx = context
    proposal = await suggest(ctx, monkeypatch)
    responses = await asyncio.gather(apply(ctx, proposal), apply(ctx, proposal))
    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["already_applied"] for response in responses) == [False, True]
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        assert task.revision == 4
        assert len(task.fields["_provenance"]["合同号"]) == 1


@pytest.mark.asyncio
async def test_history_alone_cannot_authorize_edit(context, monkeypatch):
    ctx = context
    monkeypatch.setattr(service, "select_tool", lambda *_: command())
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={
        "message":"先解释下这个字段", "history":[{"role":"user","content":"把合同号改为虚构合同2"}]})
    assert response.status_code == 409
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        assert task.fields == ctx.original_fields and task.revision == 3


def test_review_tool_describes_available_draft_without_claiming_formal_completion():
    from types import SimpleNamespace
    task = SimpleNamespace(status=TaskStatus.awaiting_review, phase="draft_ready", revision=2, fields={},
        stage="档案草稿已生成", error="", issues=[{"kind":"missing","message":"仍待补充"}],
        artifacts={"delivery_kind":"draft","valid":True,"artifacts":[{} for _ in range(9)]},
        rule_readiness={"formal_ready":False})
    result = service.execute_tool({"tool":"review_archive","query":"","field":""},task,{}, {})
    assert any(item["title"] == "自动归档草稿" and "尚未人工最终确认" in item["text"] for item in result["items"])
    assert any("有效成果 9 件" in item["text"] for item in result["items"])
    assert any(item["text"] == "仍待补充" for item in result["items"])
