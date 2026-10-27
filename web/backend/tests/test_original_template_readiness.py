from app.services import original_template_readiness as ready
from app.services import original_template_service as forms
import pytest
from tests.test_file_import_api import upload_context, upload
from tests.test_task_workflow import capture_start, wire_storage
from app.config import get_settings


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,key", [("deepseek_cloud", "deepseek_api_key"), ("glm_cloud", "glm_api_key")])
async def test_missing_original_converter_blocks_before_cloud_task_creation(upload_context, capture_start, monkeypatch, mode, key):
    from app.services.readiness import check_readiness
    from app.routers import tasks
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    monkeypatch.setattr(tasks, "check_readiness", check_readiness)
    await upload(ctx)
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    monkeypatch.setattr(ready, "native_word_available", lambda: False)
    monkeypatch.setattr(forms, "template_metadata", lambda *a, **kw: {})
    def forbidden(*a, **kw):
        raise AssertionError("readiness must not send material or probe a cloud model")
    monkeypatch.setattr("app.services.readiness.httpx.AsyncClient", forbidden)
    saved = await ctx.client.put("/api/settings", json={"processing_mode": mode, key: "synthetic-only"})
    assert saved.status_code == 200
    response = await ctx.client.post("/api/cases/case-a/generate", json={"expected_processing_mode":mode, "cloud_consent":True})
    assert response.status_code == 409 and "转换组件" in response.text
    assert not capture_start


def test_missing_converter_is_actionable_and_no_renderer_runs(monkeypatch):
    monkeypatch.setattr(ready,"native_word_available",lambda:False)
    monkeypatch.setattr(forms,"template_metadata",lambda *args,**kwargs:{})
    result=ready.original_form_readiness()
    assert not result["ready"] and len(result["issues"])==1
    assert "转换组件" in result["issues"][0]
    assert result["check"] == "prerequisites_only_not_render_test"


def test_damaged_template_message_does_not_echo_private_exception(monkeypatch):
    monkeypatch.setattr(ready,"native_word_available",lambda:True)
    def damaged(*args,**kwargs):raise ValueError("secret-path-and-customer-text")
    monkeypatch.setattr(forms,"template_metadata",damaged)
    result=ready.original_form_readiness()
    assert not result["ready"] and "secret" not in str(result)


def test_checks_all_originals_including_nonlit_cover(monkeypatch):
    calls=[]
    monkeypatch.setattr(ready,"native_word_available",lambda:True)
    monkeypatch.setattr(forms,"template_metadata",lambda *args:calls.append(args))
    assert ready.original_form_readiness()["ready"]
    assert len(calls)==6 and calls[-1] == ("档案卷宗",{"案件类别":"非诉"})
