"""Synthetic installation policy tests; no external model or live policy access."""
import json

import pytest

from tests.test_file_import_api import upload_context
from tests.test_deepseek_cloud import configure, SECRET
from app import config
from app.core.config_adapter import build_v4_config
from app.services import cloud_policy, case_assistant
from app.services.safe_errors import ErrorCode, SafeTaskError


ADMIN = {"X-Test-Role": "admin"}


@pytest.fixture(autouse=True)
def isolated_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "synthetic-policy")
    monkeypatch.setattr(config.get_settings(), "allow_external_ai", False)
    monkeypatch.setattr(config.get_settings(), "external_ai_locked", False)


@pytest.mark.asyncio
async def test_policy_requires_admin_and_explicit_enable_confirmation(upload_context):
    client = upload_context.client
    for method in (client.get, client.put):
        kwargs = {"json": {"allowed": True, "confirm_external_processing": True}} if method == client.put else {}
        assert (await method("/api/settings/cloud-policy", **kwargs)).status_code == 403
    initial = await client.get("/api/settings/cloud-policy", headers=ADMIN)
    assert initial.json()["allowed"] is False and initial.json()["scope"] == "workstation"
    assert not cloud_policy._policy_path().exists()
    denied = await client.put("/api/settings/cloud-policy", headers=ADMIN, json={"allowed": True})
    assert denied.status_code == 409 and not cloud_policy._policy_path().exists()
    enabled = await client.put("/api/settings/cloud-policy", headers=ADMIN,
                               json={"allowed": True, "confirm_external_processing": True})
    assert enabled.status_code == 200 and enabled.json()["allowed"] is True
    assert enabled.json()["updated_by"] == "test-user" and enabled.json()["updated_at"]
    # The legacy default was not mutated; no key, case or material is in the policy.
    assert config.get_settings().allow_external_ai is False
    stored = json.loads(cloud_policy._policy_path().read_text(encoding="utf-8"))
    assert set(stored) == {"version", "allowed", "updated_by", "updated_at"}
    assert (await client.get("/api/settings")).json()["external_ai_allowed"] is True
    assert config.get_settings().capabilities["external_ai_allowed"] is True
    await configure(upload_context)
    assert (await client.get("/api/settings/readiness")).json()["ready"] is True
    disabled = await client.put("/api/settings/cloud-policy", headers=ADMIN, json={"allowed": False})
    assert disabled.status_code == 200 and disabled.json()["allowed"] is False
    assert (await client.get("/api/settings/readiness")).json()["ready"] is False
    assert (await client.post("/api/settings/deepseek/check")).status_code == 409


@pytest.mark.asyncio
async def test_deployment_lock_cannot_be_overridden(upload_context, monkeypatch):
    cloud_policy.write_cloud_policy(allowed=True, actor_id="synthetic-admin")
    monkeypatch.setattr(config.get_settings(), "external_ai_locked", True)
    before = cloud_policy._policy_path().read_bytes()
    response = await upload_context.client.put("/api/settings/cloud-policy", headers=ADMIN,
                                               json={"allowed": True, "confirm_external_processing": True})
    assert response.status_code == 409
    assert cloud_policy._policy_path().read_bytes() == before
    status = cloud_policy.read_cloud_policy()
    assert not status["allowed"] and status["locked"] and status["state"] == "locked"
    assert not config.get_settings().capabilities["external_ai_allowed"]


@pytest.mark.parametrize("contents", [b"broken", b"[]", b'{"version":1,"allowed":"true"}', b"x" * 4097])
def test_corrupt_policy_fails_closed_even_if_legacy_setting_enabled(contents, monkeypatch):
    monkeypatch.setattr(config.get_settings(), "allow_external_ai", True)
    assert cloud_policy.external_ai_allowed()
    path = cloud_policy._policy_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(contents)
    status = cloud_policy.read_cloud_policy()
    assert status["state"] == "invalid" and not status["allowed"]
    with pytest.raises(SafeTaskError) as error:
        cloud_policy.require_external_ai()
    assert error.value.code == ErrorCode.CLOUD_DISABLED


def test_unreadable_policy_fails_closed(monkeypatch):
    monkeypatch.setattr(config.get_settings(), "allow_external_ai", True)
    path = cloud_policy._policy_path()
    path.parent.mkdir(parents=True)
    path.mkdir()
    assert cloud_policy.read_cloud_policy()["state"] == "invalid"
    assert not cloud_policy.external_ai_allowed()


@pytest.mark.asyncio
async def test_failed_atomic_write_keeps_previous_policy_and_safe_error(upload_context, monkeypatch):
    cloud_policy.write_cloud_policy(allowed=False, actor_id="synthetic-admin")
    before = cloud_policy._policy_path().read_bytes()
    def blocked(*args):
        raise PermissionError("synthetic-private-path-do-not-echo")
    monkeypatch.setattr(cloud_policy.os, "replace", blocked)
    response = await upload_context.client.put("/api/settings/cloud-policy", headers=ADMIN,
                                               json={"allowed": True, "confirm_external_processing": True})
    assert response.status_code == 503 and "synthetic-private" not in response.text
    assert cloud_policy._policy_path().read_bytes() == before
    assert not list(cloud_policy._policy_path().parent.glob(".cloud-policy-*.tmp"))
    assert not cloud_policy.external_ai_allowed()


@pytest.mark.asyncio
async def test_prepared_cloud_request_observes_later_disable_without_key_or_profile_changes(upload_context, monkeypatch):
    await configure(upload_context)
    cloud_policy.write_cloud_policy(allowed=True, actor_id="synthetic-admin")
    async with upload_context.sessions() as db:
        native = await build_v4_config(db, "test-user", cloud_authorized=True)
    native["privacy"]["request_guard"]()
    cloud_policy.write_cloud_policy(allowed=False, actor_id="synthetic-admin")
    with pytest.raises(SafeTaskError) as error:
        native["privacy"]["request_guard"]()
    assert error.value.code == ErrorCode.CLOUD_DISABLED
    from app.core.v4_bridge import init_v4_path
    init_v4_path()
    import deepseek_vision_client
    def forbidden(*args, **kwargs):
        pytest.fail("disable must stop the prepared model request")
    monkeypatch.setattr(deepseek_vision_client, "DeepSeekVisionClient", forbidden)
    with pytest.raises(SafeTaskError):
        case_assistant.select_tool(native, "查缺件", [], {"委托人": "虚构主体"})
    assert native["vision"]["api_key"] == SECRET
    assert native["vision"]["model"] == "deepseek-flash"
