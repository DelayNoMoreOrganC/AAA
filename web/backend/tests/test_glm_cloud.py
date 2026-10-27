"""Cloud policy regressions: synthetic sources and stub transport only."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.test_file_import_api import upload_context, upload
from tests.test_task_workflow import capture_start, wire_storage
from app.config import get_settings
from app.core.config_adapter import build_v4_config, load_user_settings
from app.models import ArchiveTask, User, UserSetting, Setting, TaskStatus, Role
from app.routers import settings as settings_route, tasks
from app.services import execution_profile as profiles, recovery, archive_service
from app.services.readiness import check_readiness
from app.services.safe_errors import SafeTaskError, ErrorCode

SECRET = "synthetic-glm-secret-NOT-REAL"


async def configure(ctx, mode="glm_cloud", key=SECRET):
    response = await ctx.client.put("/api/settings", json={"processing_mode": mode, "glm_api_key": key})
    assert response.status_code == 200
    return response


def consent(**extra):
    return {"cloud_consent": True, "expected_processing_mode": "glm_cloud", **extra}


@pytest.mark.asyncio
async def test_key_write_only_retention_clear_and_account_isolation(upload_context):
    ctx = upload_context
    first = await configure(ctx)
    assert first.json()["glm_key_configured"] is True
    assert "glm_api_key" not in first.json() and SECRET not in first.text
    for body in ({"order_mode": "original"}, {"glm_api_key": None}):
        result = await ctx.client.put("/api/settings", json=body)
        assert result.json()["glm_key_configured"] is True
        assert result.json()["processing_mode"] == "glm_cloud"
    async with ctx.sessions() as db:
        db.add(User(id="peer", org_id="org-a", username="peer-glm", hashed_password="unused", role=Role.lawyer))
        await db.commit()
    peer = await ctx.client.get("/api/settings", headers={"X-Test-User": "peer"})
    assert peer.json()["glm_key_configured"] is False and SECRET not in peer.text
    peer_write = await ctx.client.put("/api/settings", json={"glm_api_key": "peer-synthetic"}, headers={"X-Test-User": "peer"})
    assert peer_write.status_code == 200
    async with ctx.sessions() as db:
        assert (await load_user_settings(db, "test-user"))["glm_api_key"] == SECRET
    cleared = await ctx.client.put("/api/settings", json={"glm_api_key": ""})
    assert cleared.json()["glm_key_configured"] is False
    assert (await ctx.client.get("/api/settings", headers={"X-Test-User": "peer"})).json()["glm_key_configured"] is True


@pytest.mark.asyncio
async def test_glm_key_never_inherits_legacy_global_settings(upload_context):
    async with upload_context.sessions() as db:
        user = await db.get(User, "test-user")
        user.role = Role.admin
        db.add(Setting(key="glm_api_key", value=SECRET))
        await db.commit()
        assert (await load_user_settings(db, user.id))["glm_api_key"] == ""


@pytest.mark.asyncio
async def test_readiness_glm_has_no_ocr_or_network_requirement(upload_context, monkeypatch):
    ctx = upload_context
    await configure(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    def forbidden(*a, **k):
        raise AssertionError("automatic network/OCR check")
    monkeypatch.setattr("app.services.readiness.httpx.AsyncClient", forbidden)
    monkeypatch.setattr("app.services.readiness.importlib.util.find_spec", forbidden)
    forms = {"ready": True, "issues": [], "check": "prerequisites_only_not_render_test"}
    monkeypatch.setattr("app.services.original_template_readiness.original_form_readiness", lambda: forms)
    async with ctx.sessions() as db:
        result = await check_readiness(db, "test-user")
    assert result == {"ready": True, "mode": "glm_cloud", "issues": [], "external_ai_allowed": True,"original_forms":forms}
    monkeypatch.setattr(get_settings(), "allow_external_ai", False)
    assert (await ctx.client.get("/api/settings/readiness")).json()["ready"] is False


@pytest.mark.asyncio
async def test_explicit_probe_only_with_allowed_key_and_safe_errors(upload_context, monkeypatch):
    ctx = upload_context
    seen = []
    def probe(key):
        seen.append(key)
        return {"ready": True, "raw": SECRET}
    monkeypatch.setattr(settings_route, "_probe_glm", probe)
    monkeypatch.setattr(get_settings(), "allow_external_ai", False)
    await configure(ctx)
    assert (await ctx.client.post("/api/settings/glm/check")).status_code == 409
    assert not seen
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    await ctx.client.put("/api/settings", json={"glm_api_key": ""})
    assert (await ctx.client.post("/api/settings/glm/check")).status_code == 409
    assert not seen
    await configure(ctx)
    good = await ctx.client.post("/api/settings/glm/check")
    assert good.status_code == 200 and good.json()["ready"] is True
    assert seen == [SECRET] and SECRET not in good.text and "raw" not in good.json()
    def fail(key):
        raise RuntimeError("synthetic-provider-body " + key)
    monkeypatch.setattr(settings_route, "_probe_glm", fail)
    bad = await ctx.client.post("/api/settings/glm/check")
    assert bad.status_code == 503 and SECRET not in bad.text and "provider-body" not in bad.text
    assert "GD_GLM_CHECK_FAILED" in bad.text


@pytest.mark.asyncio
async def test_cloud_generation_requires_explicit_provider_consent_and_site_gate(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await upload(ctx)
    await configure(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", False)
    assert (await ctx.client.post("/api/cases/case-a/generate", json=consent())).status_code == 409
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    for body in ({}, {"cloud_consent": True}, {"expected_processing_mode": "glm_cloud"},
                 consent(expected_processing_mode="cloud")):
        assert (await ctx.client.post("/api/cases/case-a/generate", json=body)).status_code == 409
    forged = await ctx.client.post("/api/cases/case-a/generate", json=consent(execution_profile={"cloud_consent": True}))
    assert forged.status_code == 422
    assert not capture_start
    result = await ctx.client.post("/api/cases/case-a/generate", json=consent())
    assert result.status_code == 201, result.text
    profile = result.json()["execution_profile"]
    assert profile["model"] == "glm-5.3-flash" and profile["provider"] == "zhipu"
    assert profile["authorized_source_version"] == result.json()["source_version"]
    assert "authorized_by" not in profile and SECRET not in result.text
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, result.json()["id"])
        assert task.execution_profile["authorized_by"] == "test-user"
        assert SECRET not in json.dumps(task.execution_profile)
        # Current settings changing back to local cannot change the frozen model.
        await configure(ctx, "local")
        cfg = await profiles.task_config(db, task, actual_source_version=task.source_version)
        assert cfg["vision"]["api_key"] == SECRET
        assert cfg["vision"]["model"] == "glm-5.3-flash"
        assert cfg["extraction"]["mode"] == "visual_agent"
        assert cfg["privacy"]["mode"] == "cloud" and cfg["privacy"]["cloud_authorized"] is True
        assert callable(cfg["privacy"]["request_guard"])
        assert cfg["deepseek"] == cfg["mineru"] == {}


@pytest.mark.asyncio
async def test_supplement_requires_new_consent_for_frozen_cloud_mode(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    await configure(ctx)
    await upload(ctx)
    original = (await ctx.client.post("/api/cases/case-a/generate", json=consent())).json()
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, original["id"])
        task.status = TaskStatus.awaiting_review
        await db.commit()
    await configure(ctx, "local")
    await upload(ctx, name="虚构补件.pdf")
    url = f"/api/tasks/{original['id']}/resume"
    assert (await ctx.client.post(url)).status_code == 409
    assert (await ctx.client.post(url, json=consent(expected_processing_mode="local"))).status_code == 409
    resumed = await ctx.client.post(url, json=consent())
    assert resumed.status_code == 200, resumed.text
    child = resumed.json()
    assert child["id"] != original["id"] and child["parent_task_id"] == original["id"]
    assert child["source_version"] != original["source_version"]
    assert child["execution_profile"]["processing_mode"] == "glm_cloud"
    assert child["execution_profile"]["authorized_source_version"] == child["source_version"]


@pytest.mark.asyncio
async def test_legacy_resume_does_not_follow_account_into_cloud(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await upload(ctx)
    old = (await ctx.client.post("/api/cases/case-a/generate", json={})).json()
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, old["id"])
        task.execution_profile = None
        task.status = TaskStatus.awaiting_review
        await db.commit()
    await configure(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", False)
    await upload(ctx, name="legacy-supplement.pdf")
    response = await ctx.client.post(f"/api/tasks/{old['id']}/resume", json={"expected_processing_mode": "local"})
    assert response.status_code == 200, response.text
    assert response.json()["execution_profile"]["processing_mode"] == "local"
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, response.json()["id"])
        config = await profiles.task_config(db, task, actual_source_version=task.source_version)
        assert config["privacy"] == {"mode": "local", "cloud_authorized": False}
        assert "vision" not in config


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", ["consent", "source", "actor", "model", "source_now"])
async def test_execution_authorization_cannot_be_forged_or_reused_for_new_bytes(upload_context, monkeypatch, corrupt):
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    ctx = upload_context
    await configure(ctx)
    async with ctx.sessions() as db:
        profile = await profiles.make_profile(db, "test-user", "v1", cloud_consent=True, expected_mode="glm_cloud")
        task = SimpleNamespace(execution_profile=profile, source_version="v1", created_by="test-user")
        actual = "v1"
        if corrupt == "consent": profile["cloud_consent"] = "true"
        if corrupt == "source": profile["authorized_source_version"] = "old"
        if corrupt == "actor": profile["authorized_by"] = "peer"
        if corrupt == "model": profile["model"] = "unexpected"
        if corrupt == "source_now": actual = "changed"
        with pytest.raises(SafeTaskError):
            await profiles.task_config(db, task, actual_source_version=actual)


@pytest.mark.asyncio
async def test_restart_rejects_bad_consent_and_legacy_stays_local(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await configure(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    async with ctx.sessions() as db:
        profile = await profiles.make_profile(db, "test-user", "v1", cloud_consent=True, expected_mode="glm_cloud")
        profile["authorized_source_version"] = "old"
        bad = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.running,
                          source_version="v1", source_manifest=[{"synthetic": True}], execution_profile=profile)
        old = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.running,
                          source_version="v1", source_manifest=[{"synthetic": True}], execution_profile=None)
        db.add_all([bad, old])
        await db.commit()
        ids = bad.id, old.id
    await recovery.recover_interrupted_tasks()
    assert capture_start == [ids[1]]
    async with ctx.sessions() as db:
        assert (await db.get(ArchiveTask, ids[0])).status == TaskStatus.failed
        old = await db.get(ArchiveTask, ids[1])
        assert profiles.profile_overrides(old) == {"processing_mode": "local"}


@pytest.mark.asyncio
async def test_cloud_assistant_refuses_instead_of_silent_local_fallback(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await configure(ctx)
    await upload(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    created = (await ctx.client.post("/api/cases/case-a/generate", json=consent())).json()
    result = await ctx.client.post(f"/api/tasks/{created['id']}/assistant", json={"message": "找委托人"})
    assert result.status_code == 409 and "尚未开放辅助对话" in result.text
    denied = await ctx.client.post(f"/api/tasks/{created['id']}/resume", json=consent(), headers={"X-Test-User": "peer"})
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_default_config_is_never_cloud_authorized(upload_context, monkeypatch):
    ctx = upload_context
    await configure(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    async with ctx.sessions() as db:
        cfg = await build_v4_config(db, "test-user")
    assert cfg["privacy"]["cloud_authorized"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["consent", "new_source"])
async def test_worker_stops_before_analysis_for_invalid_authority(upload_context, monkeypatch, capture_start, fault):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await configure(ctx)
    await upload(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    created = (await ctx.client.post("/api/cases/case-a/generate", json=consent())).json()
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, created["id"])
        task.status = TaskStatus.awaiting_review
        if fault == "consent":
            task.execution_profile = dict(task.execution_profile, cloud_consent=False)
        await db.commit()
    if fault == "new_source":
        await upload(ctx, name="not-authorized-supplement.pdf")
    monkeypatch.setattr(archive_service, "archive_pipeline", lambda: SimpleNamespace())
    monkeypatch.setattr(archive_service, "run_word", lambda *_: pytest.fail("unauthorized model invocation"))
    await archive_service.run_archive(created["id"], "case-a", "org-a", "test-user")
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, created["id"])
        assert task.status == TaskStatus.failed
        expected = "GD_CLOUD_CONSENT_REQUIRED" if fault == "consent" else "GD_SOURCE_CHANGED"
        assert expected in task.error and SECRET not in task.error


@pytest.mark.parametrize("old_visual,old_model", [(False, "local-model"), (True, "old-visual-model")])
def test_visual_mode_reanalyzes_nonmatching_parent_but_keeps_manual(tmp_path, monkeypatch, old_visual, old_model):
    import archive_pipeline as ap
    from tests.test_task_workflow import fixture_analysis
    from app.services import task_workflow as workflow
    path = str(tmp_path / "synthetic.pdf")
    row = {"file_id":"old", "path":path, "sha256":"synthetic-sha", "doc_type":"default", "pages":1, "filename":"synthetic.pdf"}
    parent = SimpleNamespace(id=1, case_id="synthetic", source_manifest=[row], manual_fields={"合同号":"人工保留"}, execution_profile=None)
    task = SimpleNamespace(source_manifest=[row], execution_profile={"processing_mode":"glm_cloud", "model":"glm-5.3-flash"})
    previous = fixture_analysis(path, {"合同号":"人工保留", "_agent_summary":{"visual":old_visual, "model":old_model}})
    monkeypatch.setattr(workflow, "snapshot_exists", lambda *_: True)
    monkeypatch.setattr(workflow, "load_analysis", lambda *_: (previous, {}))
    calls = []
    def analyze(case_type, *, sources, config, log):
        calls.append([source.path for source in sources])
        return fixture_analysis(path, {"合同号":"视觉候选", "_agent_summary":{"visual":True, "model":"glm-5.3-flash"}})
    engine = SimpleNamespace(analyze_archive=analyze, compute_found_seqs=ap.compute_found_seqs, compute_missing_items=ap.compute_missing_items)
    config = {"workflow_case_type":"civil", "extraction":{"mode":"visual_agent"}, "vision":{"model":"glm-5.3-flash"}}
    analysis, manual, _ = workflow.analyze_with_parent(engine, task, parent,
        [SimpleNamespace(id="old", abs_path=path, doc_type="default")], config, "synthetic-org", lambda *_:None)
    assert calls == [[path]]
    assert analysis.fields["合同号"] == manual["合同号"] == "人工保留"
    assert analysis.fields["_agent_summary"]["visual"] is True
