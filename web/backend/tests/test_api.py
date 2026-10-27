# -*- coding: utf-8 -*-
"""Phase-1 API tests: auth, case CRUD, org isolation (no OCR/Word)."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
import atexit

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB_PATH = os.path.join(tempfile.gettempdir(), f"gd_web_tests_{os.getpid()}.db")
os.environ["V5_DATABASE_URL"] = "sqlite+aiosqlite:///" + TEST_DB_PATH


def _cleanup_test_db():
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(TEST_DB_PATH + suffix)
        except (FileNotFoundError, PermissionError):
            pass


atexit.register(_cleanup_test_db)

from app.main import app
from app.bootstrap import ensure_bootstrap_admin
from app.core.config_adapter import build_v4_config
from app.database import AsyncSessionLocal, engine
from app.models import Base, Setting, Org, User, Role
from app.security import hash_password
from app.config import get_settings


@pytest_asyncio.fixture(scope="function", autouse=True)
async def reset_database(monkeypatch):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(get_settings(), "registration_enabled", True)
    async with AsyncSessionLocal() as db:
        org = Org(name="测试律所")
        db.add(org)
        await db.flush()
        db.add_all([User(username="admin", hashed_password=hash_password("test-only-admin-pass-2026"), role=Role.admin, org_id=org.id),
                    User(username="zgls", hashed_password=hash_password("zgls123"), role=Role.lawyer, org_id=org.id)])
        await db.commit()
    yield


@pytest_asyncio.fixture(scope="function")
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _login(ac, username="admin", password="test-only-admin-pass-2026"):
    r = await ac.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_login_and_me(client):
    token = await _login(client)
    r = await client.get("/api/auth/me", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 200
    assert r.json()["username"] == "admin"
    assert r.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_bad_password(client):
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_case_crud(client):
    token = await _login(client)
    h = {"Authorization": "Bearer " + token}
    r = await client.post("/api/cases", json={"title": "T-case", "case_type": "civil"}, headers=h)
    assert r.status_code == 201
    cid = r.json()["id"]
    r2 = await client.get("/api/cases", headers=h)
    assert r2.status_code == 200
    assert any(c["id"] == cid for c in r2.json())
    r3 = await client.get("/api/cases/" + cid, headers=h)
    assert r3.status_code == 200
    assert r3.json()["title"] == "T-case"
    r4 = await client.delete("/api/cases/" + cid, headers=h)
    assert r4.status_code == 204


@pytest.mark.asyncio
async def test_protected_without_token(client):
    r = await client.get("/api/cases")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_self_registration_creates_isolated_workspace(client):
    suffix = uuid.uuid4().hex[:8]
    username = "user_" + suffix
    payload = {
        "username": username,
        "password": "safe12345",
        "display_name": "自助用户",
        "org_name": "自助团队" + suffix,
    }
    registered = await client.post("/api/auth/register", json=payload)
    assert registered.status_code == 201
    token = registered.json()["access_token"]
    headers = {"Authorization": "Bearer " + token}

    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["username"] == username
    assert me.json()["role"] == "lawyer"

    logged_in = await client.post(
        "/api/auth/login",
        json={"username": username.upper(), "password": payload["password"]},
    )
    assert logged_in.status_code == 200
    headers = {"Authorization": "Bearer " + logged_in.json()["access_token"]}

    own_settings = await client.get("/api/settings", headers=headers)
    assert own_settings.status_code == 200
    assert own_settings.json()["deepseek_key_configured"] is False
    assert own_settings.json()["deepseek_model"] == "deepseek-v4-flash"
    assert own_settings.json()["mineru_key_configured"] is False

    created = await client.post(
        "/api/cases",
        json={"title": "私有案件", "case_type": "criminal"},
        headers=headers,
    )
    assert created.status_code == 201
    case_id = created.json()["id"]

    admin_token = await _login(client)
    admin_cases = await client.get(
        "/api/cases", headers={"Authorization": "Bearer " + admin_token}
    )
    assert all(item["id"] != case_id for item in admin_cases.json())

    duplicate_payload = dict(payload, username=username.upper())
    duplicate = await client.post("/api/auth/register", json=duplicate_payload)
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_api_settings_are_isolated_per_account_in_same_org(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_external_ai", True)
    admin_token = await _login(client, "admin", "test-only-admin-pass-2026")
    lawyer_token = await _login(client, "zgls", "zgls123")
    admin_headers = {"Authorization": "Bearer " + admin_token}
    lawyer_headers = {"Authorization": "Bearer " + lawyer_token}

    admin_me = (await client.get("/api/auth/me", headers=admin_headers)).json()
    lawyer_me = (await client.get("/api/auth/me", headers=lawyer_headers)).json()
    assert admin_me["org_id"] == lawyer_me["org_id"]

    admin_payload = {
        "local_vision_tier": "minimum",
        "processing_mode": "cloud",
        "local_llm_base_url": "http://127.0.0.1:11434/v1",
        "local_llm_model": "",
        "deepseek_api_key": "admin-llm-key",
        "deepseek_base_url": "https://admin-llm.example/v1",
        "deepseek_model": "admin-model",
        "mineru_api_token": "admin-ocr-token",
        "order_mode": "catalog",
    }
    lawyer_payload = {
        "local_vision_tier": "recommended",
        "processing_mode": "cloud",
        "local_llm_base_url": "http://127.0.0.1:11434/v1",
        "local_llm_model": "",
        "deepseek_api_key": "lawyer-llm-key",
        "deepseek_base_url": "https://lawyer-llm.example/v1",
        "deepseek_model": "lawyer-model",
        "mineru_api_token": "lawyer-ocr-token",
        "order_mode": "original",
    }
    assert (
        await client.put("/api/settings", json=admin_payload, headers=admin_headers)
    ).status_code == 200
    assert (
        await client.put("/api/settings", json=lawyer_payload, headers=lawyer_headers)
    ).status_code == 200

    admin_settings = (await client.get("/api/settings", headers=admin_headers)).json()
    lawyer_settings = (await client.get("/api/settings", headers=lawyer_headers)).json()
    def visible(payload):
        return dict({key: value for key, value in payload.items() if key not in ("deepseek_api_key", "mineru_api_token")},
                    glm_key_configured=False, deepseek_key_configured=True, mineru_key_configured=True, external_ai_allowed=True)
    assert admin_settings == visible(admin_payload)
    assert lawyer_settings == visible(lawyer_payload)

    # Exercise the exact adapter used by archive jobs, not just the HTTP view.
    async with AsyncSessionLocal() as db:
        admin_config = await build_v4_config(db, admin_me["id"])
        lawyer_config = await build_v4_config(db, lawyer_me["id"])
    assert admin_config["deepseek"]["api_key"] == "admin-llm-key"
    assert admin_config["mineru"]["api_token"] == "admin-ocr-token"
    assert lawyer_config["deepseek"]["api_key"] == "lawyer-llm-key"
    assert lawyer_config["mineru"]["api_token"] == "lawyer-ocr-token"


@pytest.mark.asyncio
async def test_legacy_global_keys_are_only_inherited_by_admin(client):
    async with AsyncSessionLocal() as db:
        db.add(Setting(key="deepseek_api_key", value="legacy-admin-key"))
        db.add(Setting(key="mineru_api_token", value="legacy-admin-ocr"))
        await db.commit()

    admin_token = await _login(client, "admin", "test-only-admin-pass-2026")
    lawyer_token = await _login(client, "zgls", "zgls123")
    admin_settings = await client.get(
        "/api/settings", headers={"Authorization": "Bearer " + admin_token}
    )
    lawyer_settings = await client.get(
        "/api/settings", headers={"Authorization": "Bearer " + lawyer_token}
    )
    assert admin_settings.json()["deepseek_key_configured"] is True
    assert admin_settings.json()["mineru_key_configured"] is True
    assert "legacy-admin" not in admin_settings.text
    assert lawyer_settings.json()["deepseek_key_configured"] is False
    assert lawyer_settings.json()["mineru_key_configured"] is False
