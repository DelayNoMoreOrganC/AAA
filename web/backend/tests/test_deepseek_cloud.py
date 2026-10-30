"""Synthetic backend integration; all model/probe calls are explicitly mocked."""
import copy
import json

import pytest
from sqlalchemy import select

from tests.test_file_import_api import upload_context, upload
from tests.test_task_workflow import capture_start, wire_storage, fixture_analysis
from tests.test_case_assistant import context
from app.config import get_settings
from app.core.config_adapter import build_v4_config, load_user_settings
from app.models import ArchiveTask, CaseFile, User, UserSetting, Setting, TaskStatus, Role
from app.routers import settings as settings_route
from app.services import execution_profile as profiles, recovery, archive_service, case_assistant
from app.services.readiness import check_readiness
from app.services.safe_errors import ErrorCode, SafeTaskError, deepseek_error_code, public_error
from app.services.analysis_snapshot import save_snapshot, task_work_dir
from app.services.task_manager import safe_log_line
from case_outcome import STRICT_EVIDENCE_VERSION

SECRET = "synthetic-deepseek-key-never-real"


async def configure(ctx, mode="deepseek_cloud", **extra):
    response = await ctx.client.put("/api/settings", json={"processing_mode":mode, "deepseek_api_key":SECRET, **extra})
    assert response.status_code == 200, response.text
    return response


def consent(**extra):
    return {"cloud_consent":True, "expected_processing_mode":"deepseek_cloud", **extra}


@pytest.mark.asyncio
async def test_all_secrets_are_write_only_preserved_and_isolated(upload_context):
    ctx = upload_context
    result = await configure(ctx, mineru_api_token="synthetic-mineru", glm_api_key="synthetic-glm")
    assert result.json()["deepseek_key_configured"] and result.json()["mineru_key_configured"] and result.json()["glm_key_configured"]
    for key in ("deepseek_api_key", "mineru_api_token", "glm_api_key"):
        assert key not in result.json()
    for payload in ({"order_mode":"original"}, {"deepseek_api_key":None,"mineru_api_token":None}):
        saved = await ctx.client.put("/api/settings", json=payload)
        assert saved.status_code == 200 and saved.json()["deepseek_key_configured"] and saved.json()["mineru_key_configured"]
        assert "synthetic-" not in saved.text
    async with ctx.sessions() as db:
        db.add(User(id="peer", org_id="org-a", username="deepseek-peer", hashed_password="unused", role=Role.lawyer))
        await db.commit()
        own = await load_user_settings(db, "test-user")
        assert own["deepseek_api_key"] == SECRET and own["mineru_api_token"] == "synthetic-mineru"
    other = await ctx.client.get("/api/settings", headers={"X-Test-User":"peer"})
    assert other.json()["deepseek_key_configured"] is False and other.json()["mineru_key_configured"] is False
    cleared = await ctx.client.put("/api/settings", json={"deepseek_api_key":"", "mineru_api_token":""})
    assert not cleared.json()["deepseek_key_configured"] and not cleared.json()["mineru_key_configured"]
    assert cleared.json()["glm_key_configured"] is True


@pytest.mark.asyncio
async def test_first_account_save_preserves_omitted_legacy_keys_without_echo(upload_context):
    ctx = upload_context
    async with ctx.sessions() as db:
        user = await db.get(User, "test-user")
        user.role = Role.admin
        db.add_all([Setting(key="deepseek_api_key", value=SECRET), Setting(key="mineru_api_token", value="synthetic-legacy-ocr")])
        await db.commit()
    saved = await ctx.client.put("/api/settings", json={"processing_mode":"deepseek_cloud"})
    assert saved.status_code == 200 and saved.json()["deepseek_key_configured"]
    assert SECRET not in saved.text
    async with ctx.sessions() as db:
        cfg = await load_user_settings(db, "test-user")
        assert cfg["deepseek_api_key"] == SECRET and cfg["mineru_api_token"] == "synthetic-legacy-ocr"


@pytest.mark.asyncio
async def test_native_mode_ignores_legacy_url_model_and_needs_no_mineru(upload_context, monkeypatch):
    ctx = upload_context
    await configure(ctx, deepseek_base_url="https://invalid.example/do-not-call", deepseek_model="legacy-custom")
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    def forbidden(*args, **kwargs): pytest.fail("readiness must not make cloud/OCR requests")
    monkeypatch.setattr("app.services.readiness.httpx.AsyncClient", forbidden)
    monkeypatch.setattr("app.services.readiness.importlib.util.find_spec", forbidden)
    forms = {"ready": True, "issues": [], "check": "prerequisites_only_not_render_test"}
    monkeypatch.setattr("app.services.original_template_readiness.original_form_readiness", lambda: forms)
    async with ctx.sessions() as db:
        ready = await check_readiness(db, "test-user")
        cfg = await build_v4_config(db, "test-user")
    assert ready == {"ready":True,"mode":"deepseek_cloud","issues":[],"external_ai_allowed":True,"original_forms":forms}
    assert cfg["vision"] == {"provider":"deepseek", "model":"deepseek-flash", "api_key":SECRET,
        "workflow":"document_two_stage", "endpoint":"https://api.deepseek.com/chat/completions"}
    assert cfg["deepseek"] == cfg["mineru"] == {}
    assert cfg["extraction"]["mode"] == "visual_agent" and not cfg["privacy"]["cloud_authorized"]
    await ctx.client.put("/api/settings", json={"deepseek_api_key":""})
    not_ready = await ctx.client.get("/api/settings/readiness")
    assert not not_ready.json()["ready"] and "DeepSeek" in not_ready.text


@pytest.mark.asyncio
async def test_explicit_probe_sends_only_saved_own_key_and_hides_errors(upload_context, monkeypatch):
    ctx = upload_context
    seen = []
    monkeypatch.setattr(settings_route, "_probe_deepseek", lambda key: seen.append(key) or {"ready":True, "body":SECRET})
    monkeypatch.setattr(get_settings(), "allow_external_ai", False)
    await configure(ctx)
    assert (await ctx.client.post("/api/settings/deepseek/check")).status_code == 409
    assert not seen
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    await ctx.client.put("/api/settings", json={"deepseek_api_key":""})
    assert (await ctx.client.post("/api/settings/deepseek/check")).status_code == 409
    assert not seen
    await configure(ctx)
    success = await ctx.client.post("/api/settings/deepseek/check")
    assert success.status_code == 200 and success.json()["ready"] and SECRET not in success.text
    assert seen == [SECRET]
    def fail(key): raise RuntimeError("provider-body " + key)
    monkeypatch.setattr(settings_route, "_probe_deepseek", fail)
    failure = await ctx.client.post("/api/settings/deepseek/check")
    assert failure.status_code == 503 and "GD_DEEPSEEK_CHECK_FAILED" in failure.text
    assert SECRET not in failure.text and "provider-body" not in failure.text


@pytest.mark.asyncio
async def test_generation_and_supplement_freeze_provider_and_require_version_consent(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await upload(ctx)
    await configure(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", False)
    assert (await ctx.client.post("/api/cases/case-a/generate", json=consent())).status_code == 409
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    for payload in ({}, {"cloud_consent":True}, consent(expected_processing_mode="glm_cloud")):
        assert (await ctx.client.post("/api/cases/case-a/generate", json=payload)).status_code == 409
    result = await ctx.client.post("/api/cases/case-a/generate", json=consent())
    assert result.status_code == 201, result.text
    first = result.json()
    profile = first["execution_profile"]
    assert profile["provider"] == "deepseek" and profile["model"] == "deepseek-flash" and profile["workflow"] == "document_two_stage"
    assert profile["authorized_source_version"] == first["source_version"] and SECRET not in result.text
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, first["id"])
        cfg = await profiles.task_config(db, task, actual_source_version=task.source_version)
        assert cfg["privacy"]["cloud_authorized"] is True
        assert cfg['vision']['batch_policy']==task.execution_profile['_visual_batch_policy']
        assert cfg['vision']['batch_policy']['classification_pages']==8
        task.status = TaskStatus.awaiting_review
        await db.commit()
    await configure(ctx, mode="glm_cloud", glm_api_key="unrelated-synthetic-key")
    await upload(ctx, name="synthetic-supplement.pdf")
    resume = f"/api/tasks/{first['id']}/resume"
    assert (await ctx.client.post(resume)).status_code == 409
    assert (await ctx.client.post(resume, json=consent(expected_processing_mode="glm_cloud"))).status_code == 409
    child = (await ctx.client.post(resume, json=consent())).json()
    assert child["id"] != first["id"] and child["parent_task_id"] == first["id"]
    assert child["execution_profile"]["processing_mode"] == "deepseek_cloud"
    assert child["execution_profile"]["authorized_source_version"] == child["source_version"] != first["source_version"]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["provider", "model", "workflow", "cloud_consent", "authorized_source_version", "authorized_by"])
async def test_invalid_frozen_authority_cannot_build_or_recover_cloud_task(upload_context, monkeypatch, capture_start, changed):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await configure(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    async with ctx.sessions() as db:
        profile = await profiles.make_profile(db, "test-user", "fictional-v1", cloud_consent=True, expected_mode="deepseek_cloud")
        profile[changed] = "forged"
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.running,
            source_version="fictional-v1", source_manifest=[{"synthetic":True}], execution_profile=profile)
        db.add(task)
        await db.commit()
        task_id = task.id
        with pytest.raises(SafeTaskError):
            await profiles.task_config(db, task, actual_source_version=task.source_version)
    await recovery.recover_interrupted_tasks()
    assert not capture_start
    async with ctx.sessions() as db:
        assert (await db.get(ArchiveTask, task_id)).status == TaskStatus.failed


@pytest.mark.asyncio
async def test_cloud_assistant_uses_real_selector_boundary_and_is_read_only(context, monkeypatch):
    ctx = context
    await configure(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        task.execution_profile = await profiles.make_profile(db, "test-user", task.source_version, cloud_consent=True, expected_mode="deepseek_cloud")
        before_fields, before_confirmation, before_revision = copy.deepcopy(task.fields), copy.deepcopy(task.confirmation), task.revision
        await db.commit()
    import deepseek_vision_client as client
    seen = []
    def select(self, messages):
        seen.append((self._api_key, messages))
        return {"tool":"explain_field", "query":"", "field":"委托人"}
    monkeypatch.setattr(client.DeepSeekVisionClient, "complete", select)
    before_snapshot = (ctx.work / "analysis_snapshot.json").read_bytes()
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":"把委托人改成虚构乙"})
    assert response.status_code == 200, response.text
    assert response.json()["tool"] == "explain_field"
    assert seen[0][0] == SECRET and SECRET not in response.text
    prompt = json.dumps(seen[0][1], ensure_ascii=False)
    assert "人工核对甲" not in prompt and "synthetic.pdf" not in prompt
    assert (ctx.work / "analysis_snapshot.json").read_bytes() == before_snapshot
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        assert task.fields == before_fields and task.confirmation == before_confirmation and task.revision == before_revision
    for headers in ({"X-Test-User":"peer"}, {"X-Test-Org":"org-b"}):
        denied = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":"查看"}, headers=headers)
        assert denied.status_code == 404
    assert len(seen) == 1
    # New unapproved materials are blocked before the model sees any question.
    await upload(ctx, name="new-unapproved.pdf")
    changed = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":"查看"})
    assert changed.status_code == 409 and len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["site_gate", "consent", "key", "tool", "provider_failure"])
async def test_cloud_assistant_rejects_missing_authority_or_invalid_tool(context, monkeypatch, invalid):
    ctx = context
    await configure(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        profile = await profiles.make_profile(db, "test-user", task.source_version, cloud_consent=True, expected_mode="deepseek_cloud")
        if invalid == "consent": profile["cloud_consent"] = False
        task.execution_profile = profile
        await db.commit()
    if invalid == "site_gate": monkeypatch.setattr(get_settings(), "allow_external_ai", False)
    if invalid == "key": await ctx.client.put("/api/settings", json={"deepseek_api_key":""})
    import deepseek_vision_client as client
    called = []
    def bad(self, messages):
        called.append(True)
        if invalid == "provider_failure": raise RuntimeError(SECRET)
        return {"tool":"shell", "query":"read arbitrary path", "field":""}
    monkeypatch.setattr(client.DeepSeekVisionClient, "complete", bad)
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assistant", json={"message":"查看"})
    assert response.status_code == (503 if invalid in ("tool", "provider_failure") else 409)
    assert SECRET not in response.text
    assert len(called) == (1 if invalid in ("tool", "provider_failure") else 0)


def test_safe_provider_errors_and_two_stage_progress():
    import deepseek_vision_client as ds
    assert deepseek_error_code(ds.DeepSeekVisionError("QUOTA_EXHAUSTED")) == ErrorCode.DEEPSEEK_QUOTA_EXHAUSTED
    assert SECRET not in public_error(deepseek_error_code(RuntimeError(SECRET)))
    for line in ("视觉分类：已核对 4 / 85 页", "文书提取：已处理 3 / 12 份文书"):
        assert safe_log_line(line) == line
        assert safe_log_line(line + " " + SECRET) is None


def test_selected_page_reminder_is_nonblocking_and_has_registered_sources():
    from app.services.task_workflow import analysis_issues, unresolved_issues
    analysis = fixture_analysis("synthetic.pdf", {"委托人":"虚构甲", "_field_extraction_review":[
        {"source_path":"synthetic.pdf","page":1,"doc_id":0,"reason_code":"selected_pages_only","raw":SECRET}]})
    manifest = [{"path":"synthetic.pdf","file_id":"synthetic-id","filename":"虚构.pdf"}]
    issues = analysis_issues(analysis, manifest)
    reminder = next(item for item in issues if item["kind"] == "field_extraction_review")
    assert reminder["blocking"] is False
    assert reminder["detail"]["pages"] == [{"file_id":"synthetic-id","filename":"虚构.pdf","page":1}]
    assert not unresolved_issues(issues, analysis.fields) and SECRET not in json.dumps(reminder)


@pytest.mark.parametrize("reasons,selected,limited", [
    (["document_operation_limit"], 0, 1),
    (["selected_pages_only"], 1, 0),
    (["selected_pages_only", "document_operation_limit"], 1, 1),
])
def test_field_extraction_reminder_distinguishes_incomplete_documents(reasons, selected, limited):
    from app.services.task_workflow import analysis_issues, unresolved_issues
    rows = [{"source_path":"synthetic.pdf","page":i+1,"doc_id":i,"reason_code":reason}
            for i,reason in enumerate(reasons)]
    analysis = fixture_analysis("synthetic.pdf", {"委托人":"虚构甲", "_field_extraction_review":rows})
    issues = analysis_issues(analysis)
    reminder = next(item for item in issues if item["kind"] == "field_extraction_review")
    assert reminder["detail"]["selected_pages_document_count"] == selected
    assert reminder["detail"]["operation_limit_document_count"] == limited
    assert reminder["detail"]["document_count"] == selected + limited
    assert ("提取未完成" in reminder["message"]) == bool(limited)
    assert ("选定页面" in reminder["message"]) == bool(selected)
    assert not reminder["blocking"] and not unresolved_issues(issues, analysis.fields)


def test_operation_limit_takes_precedence_for_same_document():
    from app.services.task_workflow import analysis_issues
    rows = [{"source_path":"synthetic.pdf","page":1,"doc_id":0,"reason_code":reason}
            for reason in ("selected_pages_only", "document_operation_limit")]
    analysis = fixture_analysis("synthetic.pdf", {"委托人":"虚构甲", "_field_extraction_review":rows})
    reminder = next(item for item in analysis_issues(analysis) if item["kind"] == "field_extraction_review")
    assert reminder["detail"]["document_count"] == reminder["detail"]["operation_limit_document_count"] == 1
    assert reminder["detail"]["selected_pages_document_count"] == 0
    assert "选定页面" not in reminder["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("visual_version", ["visual-analysis-v2", "visual-analysis-v1", None])
@pytest.mark.parametrize("checkpoint_workflow", ["document_two_stage", "legacy_workflow", None])
@pytest.mark.parametrize("normalization_version", [STRICT_EVIDENCE_VERSION, "strict-fields-v2", "strict-fields-v1", None])
async def test_authorized_analysis_enters_visual_core_without_legacy_ocr(upload_context, monkeypatch, capture_start, checkpoint_workflow, normalization_version, visual_version):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await upload(ctx)
    await configure(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    created = (await ctx.client.post("/api/cases/case-a/generate", json=consent())).json()
    from types import SimpleNamespace
    import archive_pipeline as ap
    from visual_archive_agent import VISUAL_ANALYSIS_VERSION
    calls = []
    def synthetic_analyze(case_type, *, sources, config, log):
        calls.append(config)
        assert config["privacy"]["cloud_authorized"] is True
        assert config["vision"]["provider"] == "deepseek" and config["vision"]["workflow"] == "document_two_stage"
        assert config["deepseek"] == config["mineru"] == {}
        return fixture_analysis(sources[0].path, {"委托人":"虚构分析夹具", "_field_normalization_version":STRICT_EVIDENCE_VERSION,
            "_agent_summary":{"visual":True,"model":"deepseek-flash","workflow":"document_two_stage",
                              "analysis_version": VISUAL_ANALYSIS_VERSION}})
    monkeypatch.setattr(archive_service, "archive_pipeline", lambda:SimpleNamespace(analyze_archive=synthetic_analyze,
        compute_found_seqs=ap.compute_found_seqs, compute_missing_items=ap.compute_missing_items))
    async def inline(fn, *args, **kwargs): return fn(*args, **kwargs)
    monkeypatch.setattr(archive_service, "run_word", inline)
    deliveries = []
    async def delivery_boundary(task_id, *args, draft=False, **kwargs):
        # This test owns provider selection/reuse. Actual nine-file delivery is
        # exercised by test_automatic_draft, rather than this analyzer-only stub.
        assert draft is True
        deliveries.append(task_id)
        await archive_service._persist_task(task_id, status=TaskStatus.awaiting_review)
    monkeypatch.setattr(archive_service, "run_assemble", delivery_boundary)
    await archive_service.run_archive(created["id"], "case-a", "org-a", "test-user")
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, created["id"])
        assert task.status == TaskStatus.awaiting_review, task.error
        assert task.fields["委托人"] == "虚构分析夹具" and len(calls) == 1
        assert SECRET not in json.dumps(task.fields, ensure_ascii=False)
    # Only the same algorithm can recover without invoking the model again.
    compatible = (checkpoint_workflow == "document_two_stage" and normalization_version == STRICT_EVIDENCE_VERSION
                  and visual_version == VISUAL_ANALYSIS_VERSION)
    if not compatible:
        from app.services.analysis_snapshot import load_analysis
        work = task_work_dir("org-a", "case-a", created["id"])
        old, snapshot = load_analysis(work)
        if visual_version is None:
            old.fields["_agent_summary"].pop("analysis_version")
        else:
            old.fields["_agent_summary"]["analysis_version"] = visual_version
        if checkpoint_workflow is None:
            old.fields["_agent_summary"].pop("workflow")
        else:
            old.fields["_agent_summary"]["workflow"] = checkpoint_workflow
        if normalization_version is None:
            old.fields.pop("_field_normalization_version")
        else:
            old.fields["_field_normalization_version"] = normalization_version
        save_snapshot(work, old, base_name="虚构旧检查点", metadata=snapshot["workflow"])
        async with ctx.sessions() as db:
            task = await db.get(ArchiveTask, created["id"])
            task.manual_fields = {"合同号":"人工核对保留"}
            await db.commit()
    else:
        monkeypatch.setattr(archive_service, "run_word", lambda *_:pytest.fail("snapshot replay must not invoke model"))
    await archive_service.run_archive(created["id"], "case-a", "org-a", "test-user")
    assert len(calls) == (1 if compatible else 2)
    assert deliveries == [created["id"], created["id"]]
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, created["id"])
        assert task.status == TaskStatus.awaiting_review, task.error
        assert task.fields["_agent_summary"]["workflow"] == "document_two_stage"
        assert task.fields["_field_normalization_version"] == STRICT_EVIDENCE_VERSION
        if not compatible:
            assert task.fields["合同号"] == "人工核对保留"


@pytest.mark.parametrize("previous_workflow", [None, "legacy_workflow", "document_two_stage"])
@pytest.mark.parametrize("added", [False, True])
@pytest.mark.parametrize("normalization_version", [STRICT_EVIDENCE_VERSION, "strict-fields-v2", "strict-fields-v1", None])
def test_parent_reuse_requires_matching_visual_workflow(tmp_path, monkeypatch, previous_workflow, added, normalization_version):
    from types import SimpleNamespace
    import archive_pipeline as ap
    from visual_archive_agent import VISUAL_ANALYSIS_VERSION
    from app.services import task_workflow as workflow
    paths = [str(tmp_path / "old.pdf"), str(tmp_path / "new.pdf")]
    rows = [{"file_id":str(i),"path":p,"sha256":str(i),"doc_type":"default","pages":1,"filename":f"{i}.pdf"} for i,p in enumerate(paths)]
    profile = {"processing_mode":"deepseek_cloud","model":"deepseek-flash","workflow":"document_two_stage"}
    parent = SimpleNamespace(id=1,case_id="synthetic",source_manifest=rows[:1],manual_fields={"合同号":"人工保留"},execution_profile=profile)
    current = rows if added else rows[:1]
    task = SimpleNamespace(case_id='synthetic',source_manifest=current,execution_profile=profile)
    summary = {"visual":True,"model":"deepseek-flash", "analysis_version": VISUAL_ANALYSIS_VERSION}
    if previous_workflow is not None: summary["workflow"] = previous_workflow
    previous = fixture_analysis(paths[0], {"委托人":"虚构旧", "_agent_summary":summary})
    if normalization_version is not None: previous.fields["_field_normalization_version"] = normalization_version
    monkeypatch.setattr(workflow, "snapshot_exists", lambda *_:True)
    monkeypatch.setattr(workflow, "load_analysis", lambda *_:(previous,{}))
    calls = []
    def analyze(case_type, *, sources, config, log):
        calls.append([source.path for source in sources])
        return fixture_analysis(sources[0].path, {"委托人":"虚构新", "_agent_summary":{**summary,"workflow":"document_two_stage"}})
    engine = SimpleNamespace(analyze_archive=analyze,compute_found_seqs=ap.compute_found_seqs,compute_missing_items=ap.compute_missing_items)
    files = [SimpleNamespace(id=row["file_id"],abs_path=row["path"],doc_type="default") for row in current]
    result, _, _ = workflow.analyze_with_parent(engine, task, parent, files,
        {"workflow_case_type":"civil","extraction":{"mode":"visual_agent"},
         "vision":{"model":"deepseek-flash","workflow":"document_two_stage"}}, "synthetic-org", lambda *_:None)
    compatible = previous_workflow == "document_two_stage" and normalization_version == STRICT_EVIDENCE_VERSION
    expected = ([paths[1]] if added else None) if compatible else [row["path"] for row in current]
    assert calls == ([expected] if expected else [])
    assert result.fields["合同号"] == "人工保留"


@pytest.mark.parametrize("review_key", ["_field_extraction_review", "_visual_classification_review", "_targeted_fact_review"])
def test_incremental_review_metadata_retains_parent_and_reassigns_doc_ids(tmp_path, monkeypatch, review_key):
    from types import SimpleNamespace
    import archive_pipeline as ap
    from visual_archive_agent import VISUAL_ANALYSIS_VERSION
    from app.services import task_workflow as workflow
    old_path, new_path = str(tmp_path / "old.pdf"), str(tmp_path / "new.pdf")
    rows = [{"file_id":str(i),"path":path,"sha256":str(i),"doc_type":"default","pages":1,"filename":f"{i}.pdf"}
            for i,path in enumerate((old_path,new_path))]
    profile = {"processing_mode":"deepseek_cloud","model":"deepseek-flash","workflow":"document_two_stage"}
    parent = SimpleNamespace(id=1,case_id="fictional",source_manifest=rows[:1],manual_fields={},execution_profile=profile)
    task = SimpleNamespace(case_id='fictional',source_manifest=rows,execution_profile=profile)
    reason = "selected_pages_only" if review_key == "_field_extraction_review" else "catalog_mapping_uncertain"
    def analysis(path):
        return fixture_analysis(path, {"委托人":"虚构甲", "_field_normalization_version":STRICT_EVIDENCE_VERSION, "_agent_summary":{"visual":True,"model":"deepseek-flash", "analysis_version": VISUAL_ANALYSIS_VERSION},
            review_key:[{"source_path":path,"page":1,"doc_id":0,"reason_code":reason}]})
    previous = analysis(old_path)
    monkeypatch.setattr(workflow,"snapshot_exists",lambda *_:True)
    monkeypatch.setattr(workflow,"load_analysis",lambda *_:(previous,{}))
    def analyze(case_type, *, sources, config, log):
        assert [source.path for source in sources] == [new_path]
        return analysis(new_path)
    engine = SimpleNamespace(analyze_archive=analyze,compute_found_seqs=ap.compute_found_seqs,compute_missing_items=ap.compute_missing_items)
    files = [SimpleNamespace(id=row["file_id"],abs_path=row["path"],doc_type="default") for row in rows]
    result, _, _ = workflow.analyze_with_parent(engine, task, parent, files,
        {"workflow_case_type":"civil","extraction":{"mode":"visual_agent"},"vision":{"model":"deepseek-flash"}}, "fictional-org", lambda *_:None)
    assert [(item["source_path"],item["doc_id"]) for item in result.fields[review_key]] == [(old_path,0),(new_path,1)]
