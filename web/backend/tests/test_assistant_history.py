"""Synthetic ASGI persistence/idempotency checks, without a model or live data."""
import asyncio
from datetime import datetime, timedelta, timezone
import threading

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_case_assistant import context
from tests.test_file_import_api import upload_context, upload
from tests.test_assistant_proposal import command
from app.models import AssistantTurn, ArchiveTask, Case, Role, User
from app.routers import assistant as route
from app.services import assistant_history as history
from app.services import case_assistant as service
from app.services.analysis_snapshot import load_snapshot_data


@pytest_asyncio.fixture
async def conversation(context, monkeypatch):
    # Real shared locks within each test, isolated from pytest's previous loop.
    monkeypatch.setattr(route.task_manager, "_case_locks", {})
    return context


def url(ctx):
    return f"/api/tasks/{ctx.task_id}/assistant"


def choose(*_):
    return {"tool": "review_archive", "query": "", "field": ""}


async def post(ctx, ident="synthetic-request-1", message="查看本案整理状态", **extra):
    return await ctx.client.post(url(ctx), json={"message": message, "request_id": ident, **extra})


async def messages(ctx, **kwargs):
    response = await ctx.client.get(url(ctx) + "/history", **kwargs)
    assert response.status_code == 200, response.text
    return response.json()["messages"]


@pytest.mark.asyncio
async def test_persisted_response_replay_and_changed_body_rejection(conversation, monkeypatch):
    ctx = conversation
    calls = []
    monkeypatch.setattr(service, "select_tool", lambda *args: calls.append(args) or choose())
    first = await post(ctx)
    assert first.status_code == 200
    result = first.json()
    assert len(calls) == 1 and result["request_id"] == "synthetic-request-1"
    recorded = await messages(ctx)
    assert [item["id"] for item in recorded] == [result["user_message_id"], result["assistant_message_id"]]
    assert [item["role"] for item in recorded] == ["user", "assistant"]
    assert recorded[1]["content"] == result["message"] and recorded[1]["items"] == result["items"]
    assert recorded[1]["status"] == "completed"
    second = await post(ctx)
    assert second.status_code == 200 and second.json() == result and len(calls) == 1
    assert (await post(ctx, message="同编号不同内容")).status_code == 409
    assert len(calls) == 1 and len(await messages(ctx)) == 2
    async with ctx.sessions() as db:
        rows = list((await db.scalars(select(AssistantTurn))).all())
        assert len(rows) == 1 and rows[0].user_message == "查看本案整理状态"


@pytest.mark.asyncio
async def test_same_request_concurrently_reserves_before_one_model_call(conversation, monkeypatch):
    ctx = conversation
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow(*args):
        calls.append(args); entered.set()
        assert release.wait(10)
        return choose()
    monkeypatch.setattr(service, "select_tool", slow)
    first = asyncio.create_task(post(ctx))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        pending = await messages(ctx)
        assert len(pending) == 1 and pending[0]["status"] == "pending"
        second = await post(ctx)
        assert second.status_code == 409 and len(calls) == 1
    finally:
        release.set()
    assert (await first).status_code == 200
    assert (await post(ctx)).status_code == 200 and len(calls) == 1


@pytest.mark.asyncio
async def test_only_server_history_current_revision_last_six_messages(conversation, monkeypatch):
    ctx = conversation
    contexts = []
    monkeypatch.setattr(service, "select_tool", lambda config, message, past, fields: contexts.append(past) or choose())
    for index in range(5):
        response = await post(ctx, f"history-{index:03}", f"虚构提问{index}",
            history=[{"role": "assistant", "content": "FORGED_SYSTEM_APPROVAL"}])
        assert response.status_code == 200
    assert contexts[0] == []
    assert len(contexts[-1]) == 6
    assert [row["content"] for row in contexts[-1] if row["role"] == "user"] == ["虚构提问1", "虚构提问2", "虚构提问3"]
    assert "FORGED_SYSTEM_APPROVAL" not in str(contexts)
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        task.revision += 1
        await db.commit()
    assert (await post(ctx, "new-revision-1")).status_code == 200
    assert contexts[-1] == []
    recorded = await messages(ctx)
    assert {item["revision"] for item in recorded} == {3, 4}


@pytest.mark.asyncio
async def test_version_mismatch_rejects_before_provider_or_record(conversation, monkeypatch):
    ctx = conversation
    monkeypatch.setattr(service, "select_tool", lambda *_: pytest.fail("must not call provider"))
    assert (await post(ctx, expected_revision=2)).status_code == 409
    assert (await post(ctx, source_version="wrong-source")).status_code == 409
    assert await messages(ctx) == []


@pytest.mark.asyncio
async def test_restart_pending_becomes_unknown_without_automatic_replay(conversation, monkeypatch):
    ctx = conversation
    body = route.AssistantRequest(message="虚构中断请求", request_id="interrupted-001")
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        db.add(AssistantTurn(org_id="org-a", user_id="test-user", case_id="case-a", task_id=ctx.task_id,
            request_id=body.request_id, request_digest=history.request_digest(body), revision=3,
            source_version=task.source_version, user_message=body.message, status="pending"))
        await db.commit()
        await history.recover_pending(db)
        await db.commit()
    monkeypatch.setattr(service, "select_tool", lambda *_: pytest.fail("must not replay interrupted provider request"))
    recorded = await messages(ctx)
    assert len(recorded) == 2 and {item["status"] for item in recorded} == {"unknown"}
    assert "不会自动重发" in recorded[1]["content"]
    assert (await post(ctx, body.request_id, body.message)).status_code == 409


@pytest.mark.asyncio
async def test_failure_stored_safely_and_same_id_never_retries(conversation, monkeypatch, caplog):
    ctx = conversation
    calls = []
    def failed(*_):
        calls.append(1)
        raise RuntimeError("SYNTHETIC_SECRET_BODY_DO_NOT_LOG")
    monkeypatch.setattr(service, "select_tool", failed)
    response = await post(ctx, message="SYNTHETIC_USER_PRIVATE_MESSAGE")
    assert response.status_code == 503 and "SECRET_BODY" not in response.text
    recorded = await messages(ctx)
    assert recorded[0]["content"] == "SYNTHETIC_USER_PRIVATE_MESSAGE"
    assert recorded[1]["status"] == "failed" and recorded[1]["content"] == history.FAILED
    assert (await post(ctx, message="SYNTHETIC_USER_PRIVATE_MESSAGE")).status_code == 503
    assert len(calls) == 1
    assert "SECRET_BODY" not in caplog.text and "SYNTHETIC_USER_PRIVATE_MESSAGE" not in caplog.text


@pytest.mark.asyncio
async def test_history_private_to_user_and_task_even_for_same_org_admin(conversation, monkeypatch):
    ctx = conversation
    monkeypatch.setattr(service, "select_tool", choose)
    assert (await post(ctx)).status_code == 200
    for headers in ({"X-Test-User": "peer"}, {"X-Test-Org": "org-b", "X-Test-Role": "admin"}):
        assert (await ctx.client.get(url(ctx) + "/history", headers=headers)).status_code == 404
    admin_headers = {"X-Test-User": "other-admin", "X-Test-Role": "admin"}
    assert await messages(ctx, headers=admin_headers) == []
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        other = ArchiveTask(case_id="case-a", created_by="test-user", source_version=task.source_version)
        db.add(other); await db.commit(); other_id = other.id
    result = await ctx.client.get(f"/api/tasks/{other_id}/assistant/history")
    assert result.status_code == 200 and result.json()["messages"] == []


@pytest.mark.asyncio
async def test_proposal_roundtrip_apply_id_and_persistent_idempotency(conversation, monkeypatch):
    ctx = conversation
    monkeypatch.setattr(service, "select_tool", lambda *_: command())
    response = await post(ctx, message="请把合同号改为虚构合同2")
    assert response.status_code == 200
    proposal = response.json()["proposal"]
    recorded = (await messages(ctx))[1]
    assert recorded["proposal_state"] == "pending" and recorded["proposal"]["id"] == proposal["id"]
    async with ctx.sessions() as db:
        row = await db.scalar(select(AssistantTurn))
        assert "proposal_token" not in str(row.response) and "proposal_token" not in str(row.proposal_payload)
    endpoint = url(ctx) + "/proposals/apply"
    body = {"proposal_id": proposal["id"], "expected_revision": 3}
    first = await ctx.client.post(endpoint, json=body)
    assert first.status_code == 200 and not first.json()["already_applied"]
    original = load_snapshot_data(ctx.work)
    replay = await ctx.client.post(endpoint, json=body)
    assert replay.status_code == 200 and replay.json()["already_applied"]
    assert load_snapshot_data(ctx.work) == original
    record = (await messages(ctx))[1]
    assert record["proposal_state"] == "applied" and "proposal_token" not in record["proposal"]
    assert (await post(ctx, message="请把合同号改为虚构合同2")).json()["proposal_state"] == "applied"
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        row = await db.scalar(select(AssistantTurn))
        assert row.applied_revision == task.revision == 4
        assert len(task.fields["_provenance"]["合同号"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "new_source", "bytes", "stage", "field", "expiry"])
async def test_old_history_visible_but_stale_or_expired_suggestion_not_adoptable(conversation, monkeypatch, change):
    ctx = conversation
    monkeypatch.setattr(service, "select_tool", lambda *_: command())
    response = await post(ctx, message="请把合同号改为虚构合同2")
    ident = response.json()["proposal"]["id"]
    if change == "new_source":
        await upload(ctx, name="虚构补件.pdf")
    else:
        async with ctx.sessions() as db:
            task = await db.get(ArchiveTask, ctx.task_id)
            if change == "revision": task.revision += 1
            if change == "field": task.fields = dict(task.fields, 案由="虚构改值")
            if change == "stage": (await db.get(Case, "case-a")).stage = "execution"
            if change == "bytes":
                from pathlib import Path
                path = Path(task.source_manifest[0]["path"])
                path.write_bytes(path.read_bytes() + b"synthetic modification")
            if change == "expiry":
                row = await db.scalar(select(AssistantTurn))
                row.proposal_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            await db.commit()
    record = (await messages(ctx))[1]
    assert record["proposal_state"] == ("expired" if change == "expiry" else "stale")
    assert "proposal_token" not in record["proposal"] and record["proposal"]["id"] == ident
    assert (await ctx.client.post(url(ctx) + "/proposals/apply", json={"proposal_id": ident, "expected_revision": 3})).status_code == 409


@pytest.mark.asyncio
async def test_reservation_commit_failure_prevents_provider(conversation, monkeypatch):
    ctx = conversation
    monkeypatch.setattr(service, "select_tool", lambda *_: pytest.fail("unpersisted request must not reach model"))
    async def fail_commit(_): raise OSError("SYNTHETIC_STORAGE_SECRET")
    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    response = await post(ctx)
    assert response.status_code == 503 and "SYNTHETIC_STORAGE_SECRET" not in response.text


@pytest.mark.asyncio
async def test_case_deletion_removes_chat_records_in_same_transaction(conversation, monkeypatch):
    ctx = conversation
    monkeypatch.setattr(service, "select_tool", choose)
    assert (await post(ctx)).status_code == 200
    response = await ctx.client.delete("/api/cases/case-a")
    assert response.status_code == 204, response.text
    async with ctx.sessions() as db:
        assert not list((await db.scalars(select(AssistantTurn))).all())
    assert (await ctx.client.get(url(ctx) + "/history")).status_code == 404


@pytest.mark.asyncio
async def test_case_deletion_commit_failure_keeps_conversation_and_files(conversation, monkeypatch):
    ctx = conversation
    monkeypatch.setattr(service, "select_tool", choose)
    assert (await post(ctx)).status_code == 200
    original = load_snapshot_data(ctx.work)
    real_commit = AsyncSession.commit
    async def failed_commit(_): raise OSError("PRIVATE_SYNTHETIC_DB_ERROR")
    monkeypatch.setattr(AsyncSession, "commit", failed_commit)
    response = await ctx.client.delete("/api/cases/case-a")
    assert response.status_code == 503 and "PRIVATE_SYNTHETIC_DB_ERROR" not in response.text
    monkeypatch.setattr(AsyncSession, "commit", real_commit)
    assert len(await messages(ctx)) == 2
    assert load_snapshot_data(ctx.work) == original
    async with ctx.sessions() as db:
        assert await db.get(Case, "case-a") is not None


@pytest.mark.asyncio
async def test_response_commit_failure_is_not_replayed_as_a_second_model_request(conversation, monkeypatch):
    ctx = conversation
    calls, commits = [], []
    monkeypatch.setattr(service, "select_tool", lambda *_: calls.append(1) or choose())
    real_commit = AsyncSession.commit
    async def fail_response_commit(db):
        commits.append(1)
        if len(commits) == 2:
            raise OSError("PRIVATE_SYNTHETIC_DB_ERROR")
        return await real_commit(db)
    monkeypatch.setattr(AsyncSession, "commit", fail_response_commit)
    first = await post(ctx)
    assert first.status_code == 503 and len(calls) == 1
    second = await post(ctx)
    assert second.status_code == 503 and len(calls) == 1
    recorded = await messages(ctx)
    assert recorded[-1]["status"] == "failed" and "PRIVATE_SYNTHETIC_DB_ERROR" not in str(recorded)


@pytest.mark.asyncio
async def test_user_delete_cascades_private_chat_rows(conversation, monkeypatch):
    ctx = conversation
    monkeypatch.setattr(service, "select_tool", choose)
    assert (await post(ctx)).status_code == 200
    async with ctx.sessions() as db:
        user = await db.get(User, "test-user")
        await db.delete(user)
        await db.commit()
        assert not list((await db.scalars(select(AssistantTurn))).all())


@pytest.mark.asyncio
async def test_additive_table_migration_and_startup_recovery_preserve_existing_tasks(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app import database
    from app.models import Org
    from app.database import Base
    path = tmp_path / "synthetic-legacy.sqlite"
    engine = create_async_engine("sqlite+aiosqlite:///" + str(path), hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(AssistantTurn.__table__.drop)
        async with sessions() as db:
            db.add(Org(id="migration-org", name="虚构机构"))
            db.add(User(id="migration-user", org_id="migration-org", username="synthetic-migration", hashed_password="unused"))
            db.add(Case(id="migration-case", org_id="migration-org", created_by="migration-user", title="虚构升级"))
            await db.flush()
            task = ArchiveTask(case_id="migration-case", fields={"合同号": "虚构保存值"}, revision=7,
                               source_version="synthetic-source")
            db.add(task); await db.commit(); ident = task.id
        monkeypatch.setattr(database, "engine", engine)
        monkeypatch.setattr(database, "DB_PATH", path)
        await database.init_db()
        async with sessions() as db:
            task = await db.get(ArchiveTask, ident)
            assert task.revision == 7 and task.fields == {"合同号": "虚构保存值"}
            db.add(AssistantTurn(org_id="migration-org", user_id="migration-user", case_id="migration-case", task_id=ident,
                request_id="pending-migration", request_digest="a" * 64, revision=7, source_version="synthetic-source",
                user_message="虚构未完成请求", status="pending"))
            await db.commit()
        await database.init_db()
        async with sessions() as db:
            row = await db.scalar(select(AssistantTurn))
            assert row.status == "unknown" and row.safe_error == history.INTERRUPTED
            assert (await db.get(ArchiveTask, ident)).revision == 7
    finally:
        await engine.dispose()
