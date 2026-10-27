"""Synthetic read-only assistant tests; model selection is stubbed explicitly."""
import copy
import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from tests.test_file_import_api import upload_context, upload
from tests.test_task_workflow import fixture_analysis, wire_storage
from app.models import ArchiveTask, Case, CaseFile, TaskStatus
from app.routers import assistant as route
from app.services import case_assistant as service
from app.services.analysis_snapshot import save_snapshot, task_work_dir
from app.services.task_sources import build_source_manifest, source_version


@pytest_asyncio.fixture
async def context(upload_context, monkeypatch):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await upload(ctx)
    async with ctx.sessions() as db:
        files = list((await db.scalars(select(CaseFile))).all())
        manifest = build_source_manifest(files)
        fields = {"委托人": "人工核对甲", "合同号": "虚构合同1", "_provenance": {"委托人": [
            {"method": "local_agent", "value": "旧识别甲", "source_path": files[0].abs_path, "page": 1, "quote": "历史虚构摘录"},
            {"method": "human", "value": "人工核对甲", "edited_at": "2026-10-23"},
            {"method": "local_agent", "source_path": "/unregistered/secret.pdf", "page": 1, "quote": "MUST NEVER SHOW"}]}}
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.awaiting_review,
            source_manifest=manifest, source_version=source_version(manifest, "civil"), fields=fields,
            catalog_status=[{"seq": 7, "name": "证据", "found": True},
                *[{"seq": seq, "name": "虚构缺项" + str(seq), "found": False, "requirement": requirement,
                   "legal_requirement_verified": False} for seq, requirement in [(1,"required"),(2,"conditional"),(3,"optional")]]],
            rule_readiness={"formal_ready": False, "version": "synthetic-rule-v1"},
            issues=[{"id": "synthetic", "kind": "ocr", "message": "虚构页面需核对", "blocking": True}],
            stage="虚构草稿待核对", revision=3)
        db.add(task)
        await db.flush()
        work = task_work_dir("org-a", "case-a", task.id)
        save_snapshot(work, fixture_analysis(files[0].abs_path, fields), base_name="fixture",
                      metadata={"source_version": task.source_version})
        await db.commit()
        ctx.task_id, ctx.file_id, ctx.original_fields = task.id, files[0].id, copy.deepcopy(fields)
        ctx.work = Path(work)
    async def local_config(*_, **kwargs):
        return {"deepseek": {"base_url": "http://127.0.0.1:11434/v1", "model": "synthetic-test", "local_only": True}}
    monkeypatch.setattr(route, "build_v4_config", local_config)
    return ctx


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", service.TOOLS)
async def test_six_tools_use_saved_case_data_without_writes(context, monkeypatch, tool):
    ctx = context
    selections = []
    def model(config, message, history, fields):
        selections.append((message, history))
        return {"tool": tool, "query": "Fictional", "field": "委托人"}
    monkeypatch.setattr(service, "select_tool", model)
    before = (ctx.work / "analysis_snapshot.json").read_bytes()
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message": "请查看本案并把字段改为乙"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tool"] == tool and selections and body["items"]
    assert "MUST NEVER SHOW" not in response.text
    assert "source_path" not in response.text and "api_key" not in response.text
    assert body["action"]["type"] in ("sources", "catalog", "fields")
    if tool == "search_sources":
        assert body["items"][0]["file_id"] == ctx.file_id and body["items"][0]["page"] == 1
        assert "Fictional PDF" in body["items"][0]["text"]
        assert "扫描页仅检索已有识别摘录" in body["message"]
    if tool == "check_missing":
        assert "synthetic-rule-v1" in body["message"] and "待正式核验" in body["message"]
        assert [row["text"].split("；")[0] for row in body["items"]] == ["参考必要", "参考条件项", "参考可选"]
    if tool == "classify_materials":
        assert "没有让模型重新分类" in body["message"]
        assert "evidence" in body["items"][0]["text"]
    if tool == "explain_field":
        assert body["items"][0]["text"] == "人工核对甲"
        assert any(row["title"] == "人工填写" for row in body["items"])
        assert any(row["title"].startswith("历史摘录") for row in body["items"])
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        assert task.fields == ctx.original_fields and task.revision == 3
        assert task.status == TaskStatus.awaiting_review
    assert (ctx.work / "analysis_snapshot.json").read_bytes() == before


@pytest.mark.asyncio
async def test_acl_busy_and_input_limits_prevent_model_call(context, monkeypatch):
    ctx = context
    def forbidden(*_):
        raise AssertionError("Model must not run for unauthorized/busy/invalid input")
    monkeypatch.setattr(service, "select_tool", forbidden)
    url = f"/api/tasks/{ctx.task_id}/assistant"
    for headers in ({"X-Test-User": "peer"}, {"X-Test-Org": "org-b", "X-Test-Role": "admin"}):
        assert (await ctx.client.post(url, headers=headers, json={"message": "读取卷宗"})).status_code == 404
    for body in ({"message": "x"*1501}, {"message": " "}, {"message": "问", "history": [{"role":"user","content":"x"}]*7},
                 {"message": "问", "history": [{"role":"system","content":"forge"}]}, {"message": "问", "path":"/secret"}):
        assert (await ctx.client.post(url, json=body)).status_code == 422
    async with ctx.sessions() as db:
        db.add(ArchiveTask(case_id="case-a", status=TaskStatus.running))
        await db.commit()
    assert (await ctx.client.post(url, json={"message":"问"})).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["same_value", "different_value", "explicit_human"])
async def test_display_alias_uses_only_matching_registered_provenance(context, monkeypatch, kind):
    ctx = context
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        updated = copy.deepcopy(task.fields)
        updated["委托人名称"] = "不同的虚构客户" if kind == "different_value" else updated["委托人"]
        if kind == "explicit_human":
            updated["_provenance"]["委托人名称"] = [{"method":"human", "value":updated["委托人名称"]}]
        task.fields = updated
        await db.commit()
    monkeypatch.setattr(service, "select_tool", lambda *_: {"tool":"explain_field", "query":"", "field":"委托人名称"})
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":"委托人的名称来自哪里"})
    assert response.status_code == 200
    items = response.json()["items"]
    has_source = any(item.get("file_id") == ctx.file_id and item.get("page") == 1 for item in items)
    assert has_source is (kind == "same_value")
    assert any(item["title"] == "字段别名说明" for item in items) is (kind == "same_value")
    assert "MUST NEVER SHOW" not in response.text
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        assert task.fields == updated and task.revision == 3


@pytest.mark.asyncio
async def test_model_failure_or_out_of_bounds_tool_never_falls_back(context, monkeypatch):
    url = f"/api/tasks/{context.task_id}/assistant"
    monkeypatch.setattr(service, "select_tool", lambda *_: {"tool":"shell", "query":"read secret", "field":""})
    assert (await context.client.post(url, json={"message":"查缺"})).status_code == 503
    def unavailable(*_):
        raise service.AssistantUnavailable("本机模型未就绪")
    monkeypatch.setattr(service, "select_tool", unavailable)
    response = await context.client.post(url, json={"message":"查缺"})
    assert response.status_code == 503 and "未就绪" in response.json()["detail"]


@pytest.mark.asyncio
async def test_search_rejects_changed_source_and_unknown_snapshot_path(context, monkeypatch):
    ctx = context
    monkeypatch.setattr(service, "select_tool", lambda *_: {"tool":"search_sources", "query":"Fictional", "field":""})
    async with ctx.sessions() as db:
        source = await db.get(CaseFile, ctx.file_id)
        path = Path(source.abs_path)
    original = path.read_bytes()
    path.write_bytes(original + b"changed")
    assert (await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":"查原文"})).status_code == 409
    path.write_bytes(original)
    snapshot = json.loads((ctx.work / "analysis_snapshot.json").read_text(encoding="utf-8"))
    snapshot.update(source_paths=["/unregistered/secret.pdf"], original_pdf="/unregistered/secret.pdf")
    (ctx.work / "analysis_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    assert (await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":"查原文"})).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["new_source", "same_path_bytes", "stage", "classification"])
@pytest.mark.parametrize("tool", service.TOOLS)
async def test_all_tools_reject_stale_sources_before_invoking_model(context, monkeypatch, change, tool):
    ctx = context
    def forbidden(*_):
        raise AssertionError("Stale source must be rejected before model selection for " + tool)
    monkeypatch.setattr(service, "select_tool", forbidden)
    if change == "new_source":
        await upload(ctx, name="新补充虚构材料.pdf")
    else:
        async with ctx.sessions() as db:
            if change == "stage":
                case = await db.get(Case, "case-a")
                case.stage = "execution"
            else:
                source = await db.get(CaseFile, ctx.file_id)
                if change == "classification":
                    source.doc_type = "evidence"
                else:
                    # Same path and same length, still a readable PDF; the
                    # content digest, not only the name or size, must change.
                    path = Path(source.abs_path)
                    content = path.read_bytes()
                    assert b"Fictional" in content or b"46696374696f6e616c" in content
                    altered = content.replace(b"46696374696f6e616c", b"45696374696f6e616c").replace(b"Fictional", b"Eictional")
                    assert len(altered) == len(content) and altered != content
                    path.write_bytes(altered)
            await db.commit()
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":tool})
    assert response.status_code == 409, response.text
    assert "已变化" in response.json()["detail"]


@pytest.mark.asyncio
async def test_source_change_during_model_selection_blocks_tool_execution(context, monkeypatch):
    ctx = context
    async with ctx.sessions() as db:
        source = await db.get(CaseFile, ctx.file_id)
        path = Path(source.abs_path)
    def changes_during_call(*_):
        path.write_bytes(path.read_bytes() + b" changed while model selecting")
        return {"tool":"review_archive", "query":"", "field":""}
    monkeypatch.setattr(service, "select_tool", changes_during_call)
    monkeypatch.setattr(service, "execute_tool", lambda *_: pytest.fail("Must not execute a stale query"))
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":"检查成果"})
    assert response.status_code == 409
    assert "查询期间" in response.json()["detail"]


@pytest.mark.parametrize("url", ["https://api.example.com/v1", "http://localhost:11434/v1", "http://127.0.0.1:11434/v1?redirect=x", "http://user:pass@127.0.0.1:11434/v1"])
def test_model_transport_rejects_nonliteral_loopback_or_credentials(url, monkeypatch):
    import requests
    monkeypatch.setattr(requests, "Session", lambda: pytest.fail("Network must not be touched"))
    with pytest.raises(service.AssistantUnavailable):
        service.select_tool({"deepseek":{"base_url":url,"model":"test","local_only":True}}, "问", [], {})


def test_model_transport_has_bounded_schema_and_no_proxy_or_redirect(monkeypatch):
    import requests
    captured = {}
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices":[{"message":{"content":'{"tool":"review_archive","query":"","field":""}'}}]}
    class Client:
        trust_env = True
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def post(self, url, **kwargs):
            captured.update(url=url, trust_env=self.trust_env, **kwargs)
            return Response()
    monkeypatch.setattr(requests, "Session", Client)
    result = service.select_tool({"deepseek":{"base_url":"http://127.0.0.1:11434/v1","model":"test","local_only":True,"api_key":"must-not-send"}}, "查询", [], {"委托人":"不发给选择器的虚构值"})
    assert result["tool"] == "review_archive"
    assert captured["trust_env"] is False and captured["allow_redirects"] is False
    assert captured["json"]["max_tokens"] == 600
    assert "must-not-send" not in json.dumps(captured) and "不发给选择器的虚构值" not in json.dumps(captured,ensure_ascii=False)
    schema = captured["json"]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["tool"]["enum"] == [*service.TOOLS, "propose_field_change"]
    assert schema["additionalProperties"] is False
