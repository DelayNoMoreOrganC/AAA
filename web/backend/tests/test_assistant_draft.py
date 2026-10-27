"""Fictional ASGI + real SQLite draft CAS/atomic-consumption checks."""
import asyncio
import hashlib
import json
import threading

import pytest
import pytest_asyncio
from sqlalchemy import select, inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.test_case_assistant import context
from tests.test_file_import_api import upload_context, upload
from app.database import Base
from app.models import ArchiveTask, AssistantDraft, AssistantTurn, Case, Org, User, Role, TaskStatus
from app.routers import assistant as route
from app.services import assistant_draft as store, assistant_history as history, case_assistant


@pytest_asyncio.fixture
async def draft_context(context, monkeypatch):
    monkeypatch.setattr(route.task_manager, "_case_locks", {})
    return context


def url(ctx):
    return f"/api/tasks/{ctx.task_id}/assistant/draft"


async def current(ctx, **kwargs):
    result = await ctx.client.get(url(ctx), **kwargs)
    assert result.status_code == 200, result.text
    return result.json()


async def save(ctx, text, version=0, **extra):
    state = await current(ctx)
    payload = {"content": text, "expected_version": version,
               "expected_revision": state["task_revision"], "source_version": state["task_source_version"], **extra}
    return await ctx.client.put(url(ctx), json=payload)


async def ask(ctx, text, version=1, ident="draft-request-001", **extra):
    state = await current(ctx)
    return await ctx.client.post(url(ctx).removesuffix("/draft"), json={"message": text,
        "draft_version": version, "request_id": ident, "expected_revision": state["task_revision"],
        "source_version": state["task_source_version"], **extra})


def choose(*_):
    return {"tool": "review_archive", "query": "", "field": ""}


@pytest.mark.asyncio
async def test_get_is_read_only_and_fresh_session_preserves_exact_text(draft_context):
    ctx = draft_context
    before = (ctx.work / "analysis_snapshot.json").read_bytes()
    empty = await current(ctx)
    assert empty["version"] == 0 and empty["updated_at"] is None and empty["consumed_request_id"] is None
    async with ctx.sessions() as db:
        assert list(await db.scalars(select(AssistantDraft))) == []
    value = "  虚构未发送问题\n第二行  "
    response = await save(ctx, value)
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == value and body["version"] == 1 and body["updated_at"]
    async with ctx.sessions() as db:
        row = await db.scalar(select(AssistantDraft))
        assert row.content == value and row.revision == 3 and row.version == 1
        assert await db.scalar(select(AssistantTurn)) is None
        task = await db.get(ArchiveTask, ctx.task_id)
        assert task.fields == ctx.original_fields and task.revision == 3
    assert await current(ctx) == body
    assert (ctx.work / "analysis_snapshot.json").read_bytes() == before


@pytest.mark.asyncio
async def test_cas_lost_ack_explicit_write_and_tombstone_block_aba(draft_context):
    ctx = draft_context
    first = await save(ctx, "")
    assert first.status_code == 200 and first.json()["version"] == 1
    assert (await save(ctx, "旧标签内容", 0)).status_code == 409
    assert (await save(ctx, "A", 1)).json()["version"] == 2
    replay = await save(ctx, "A", 1)
    assert replay.status_code == 200 and replay.json()["version"] == 2
    explicit = await save(ctx, "A", 2)
    assert explicit.json()["version"] == 3
    assert (await save(ctx, "B", 1)).status_code == 409
    assert (await save(ctx, "", 3)).json()["version"] == 4
    assert (await save(ctx, "A", 4)).json()["version"] == 5
    assert (await save(ctx, "A", 1)).status_code == 409


@pytest.mark.asyncio
async def test_drafts_private_even_for_org_admin_and_forged_scope_rejected(draft_context):
    ctx = draft_context
    await save(ctx, "PRIVATE_SYNTHETIC_DRAFT")
    for headers in ({"X-Test-User": "peer"}, {"X-Test-Org": "org-b", "X-Test-Role": "admin"}):
        assert (await ctx.client.get(url(ctx), headers=headers)).status_code == 404
        assert (await ctx.client.put(url(ctx), headers=headers, json={"content":"x", "expected_version":0,
            "expected_revision":3,"source_version":"x"})).status_code == 404
    admin = {"X-Test-User":"other-admin", "X-Test-Role":"admin"}
    assert (await current(ctx, headers=admin))["version"] == 0
    state = await current(ctx)
    data = {"content":"admin draft", "expected_version":0, "expected_revision":3, "source_version":state["source_version"]}
    assert (await ctx.client.put(url(ctx), headers=admin, json=data)).status_code == 200
    assert (await current(ctx))["content"] == "PRIVATE_SYNTHETIC_DRAFT"
    assert (await save(ctx, "x", 1, user_id="other-admin")).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"content":"x"*1501}, {"content":123}, {"expected_version":True},
    {"expected_version":-1}, {"expected_revision":False}, {"source_version":12}])
async def test_invalid_payload_cannot_write(draft_context, extra):
    extra = dict(extra)
    assert (await save(draft_context, "x", **extra) if "content" not in extra else
            await save(draft_context, extra.pop("content"), **extra)).status_code == 422
    assert (await current(draft_context))["version"] == 0


@pytest.mark.asyncio
async def test_context_not_rebased_get_and_explicit_adoption_required(draft_context):
    ctx = draft_context
    old = (await save(ctx, "旧修订草稿")).json()
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id); task.revision = 4
        await db.commit()
    shown = await current(ctx)
    assert shown["revision"] == 3 and shown["task_revision"] == 4 and shown["writable"] is True and shown["notice"]
    assert (await save(ctx, "new", 1, expected_revision=3)).status_code == 409
    adopted = await save(ctx, old["content"], 1)
    assert adopted.status_code == 200 and adopted.json()["revision"] == 4 and adopted.json()["version"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["new_source", "new_task"])
async def test_old_materials_or_history_readable_but_not_writable(draft_context, change):
    ctx = draft_context
    await save(ctx, "旧上下文草稿")
    if change == "new_source":
        await upload(ctx, name="新虚构材料.pdf")
    else:
        async with ctx.sessions() as db:
            db.add(ArchiveTask(case_id="case-a", status=TaskStatus.awaiting_review))
            await db.commit()
    shown = await current(ctx)
    assert shown["content"] == "旧上下文草稿" and shown["version"] == 1 and shown["writable"] is False
    assert (await save(ctx, "overwrite", 1)).status_code == 409


@pytest.mark.asyncio
async def test_model_busy_does_not_block_text_persistence(draft_context):
    ctx = draft_context
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id); task.status = TaskStatus.running
        await db.commit()
    async with route.task_manager.semaphore:
        assert (await save(ctx, "等待模型期间写字")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("same", [True, False])
async def test_concurrent_http_cas(same, draft_context):
    ctx = draft_context
    outcomes = await asyncio.gather(save(ctx, "A"), save(ctx, "A" if same else "B"))
    assert sorted(result.status_code for result in outcomes) == ([200,200] if same else [200,409])
    async with ctx.sessions() as db:
        rows = list(await db.scalars(select(AssistantDraft)))
        assert len(rows) == 1 and rows[0].version == 1


@pytest.mark.asyncio
async def test_atomic_consume_trim_replay_preserves_new_input_and_legacy_digest(draft_context, monkeypatch):
    ctx = draft_context
    calls = []
    monkeypatch.setattr(case_assistant, "select_tool", lambda *args: calls.append(args) or choose())
    assert (await save(ctx, "  虚构问题A\n")).status_code == 200
    answer = await ask(ctx, "虚构问题A")
    assert answer.status_code == 200, answer.text
    state = await current(ctx)
    assert state["content"] == "" and state["version"] == 2 and state["consumed_request_id"] == "draft-request-001"
    assert (await save(ctx, "B", 2)).json()["consumed_request_id"] is None
    assert (await ask(ctx, "虚构问题A")).status_code == 200
    assert (await current(ctx))["content"] == "B" and len(calls) == 1
    assert (await ask(ctx, "虚构问题A", version=3)).status_code == 409
    body = route.AssistantRequest(message="legacy")
    assert history.request_digest(body) == hashlib.sha256(json.dumps(["legacy",None,None],ensure_ascii=False).encode()).hexdigest()
    assert history.request_digest(body) != history.request_digest(body.model_copy(update={"draft_version":0}))
    async with ctx.sessions() as db:
        turn = await db.scalar(select(AssistantTurn))
        assert turn.user_message == "虚构问题A" and turn.status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("version,message", [(0,"A"),(1,"B"),(None,"A")])
async def test_mismatched_or_legacy_send_does_not_consume(draft_context, monkeypatch, version, message):
    ctx = draft_context
    await save(ctx, "A")
    monkeypatch.setattr(case_assistant,"select_tool",choose)
    assert (await ask(ctx,message,version=version)).status_code == 200
    state = await current(ctx)
    assert state["content"] == "A" and state["version"] == 1 and state["consumed_request_id"] is None


@pytest.mark.asyncio
async def test_turn_reservation_commit_failure_keeps_draft_and_no_model(draft_context, monkeypatch):
    ctx = draft_context
    await save(ctx, "A")
    original = AsyncSession.commit
    async def fail_pending(db):
        if any(isinstance(item, AssistantTurn) and item.status == "pending" for item in db.identity_map.values()):
            raise RuntimeError("SYNTHETIC_PRIVATE_DB_FAILURE")
        return await original(db)
    monkeypatch.setattr(AsyncSession, "commit", fail_pending)
    monkeypatch.setattr(case_assistant, "select_tool", lambda *_: pytest.fail("reservation failure must not invoke model"))
    result = await ask(ctx,"A")
    assert result.status_code == 503 and "SYNTHETIC_PRIVATE_DB_FAILURE" not in result.text
    state = await current(ctx)
    assert state["content"] == "A" and state["version"] == 1
    async with ctx.sessions() as db:
        assert await db.scalar(select(AssistantTurn)) is None


@pytest.mark.asyncio
async def test_model_failure_keeps_sent_history_and_does_not_resurrect_draft(draft_context, monkeypatch, caplog):
    ctx = draft_context
    await save(ctx,"SYNTHETIC_PRIVATE_DRAFT")
    def fail(*_):
        raise RuntimeError("SYNTHETIC_PRIVATE_MODEL_EXCEPTION")
    monkeypatch.setattr(case_assistant,"select_tool",fail)
    result = await ask(ctx,"SYNTHETIC_PRIVATE_DRAFT")
    assert result.status_code == 503
    state = await current(ctx)
    assert state["content"] == "" and state["version"] == 2 and state["consumed_request_id"]
    async with ctx.sessions() as db:
        turn = await db.scalar(select(AssistantTurn))
        assert turn.status == "failed" and turn.user_message == "SYNTHETIC_PRIVATE_DRAFT"
    assert "SYNTHETIC_PRIVATE" not in caplog.text and "SYNTHETIC_PRIVATE" not in result.text


@pytest.mark.asyncio
async def test_new_text_while_model_pending_survives_completion(draft_context, monkeypatch):
    ctx = draft_context
    await save(ctx,"A")
    entered, release = threading.Event(), threading.Event()
    def slow(*_):
        entered.set(); assert release.wait(10); return choose()
    monkeypatch.setattr(case_assistant,"select_tool",slow)
    pending = asyncio.create_task(ask(ctx,"A"))
    try:
        assert await asyncio.to_thread(entered.wait,5)
        state = await current(ctx)
        assert state["content"] == "" and state["version"] == 2
        assert (await save(ctx,"新输入B",2)).status_code == 200
    finally:
        release.set()
    assert (await pending).status_code == 200
    assert (await current(ctx))["content"] == "新输入B"


@pytest.mark.asyncio
async def test_case_delete_removes_private_drafts(draft_context):
    ctx = draft_context
    await save(ctx,"A")
    result = await ctx.client.delete("/api/cases/case-a")
    assert result.status_code == 204, result.text
    async with ctx.sessions() as db:
        assert await db.scalar(select(AssistantDraft)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["task", "user", "case"])
async def test_orm_cascade_for_private_drafts(draft_context, target):
    ctx = draft_context
    async with ctx.sessions() as db:
        db.add(User(id="draft-only-user",org_id="org-a",username="draft-only-user",hashed_password="fictional",role=Role.admin))
        await db.commit()
        db.add(AssistantDraft(org_id="org-a",user_id="draft-only-user",case_id="case-a",task_id=ctx.task_id,
            content="synthetic",version=1,revision=3,source_version="synthetic"))
        await db.commit()
        kind, identity = {"task":(ArchiveTask,ctx.task_id),"case":(Case,"case-a"),"user":(User,"draft-only-user")}[target]
        await db.delete(await db.get(kind,identity)); await db.commit()
    async with ctx.sessions() as db:
        assert await db.scalar(select(AssistantDraft)) is None


@pytest.mark.asyncio
async def test_file_sqlite_cross_session_cas_and_old_schema_upgrade(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "synthetic-drafts.db"), hide_parameters=True)
    sessions = async_sessionmaker(engine,expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            old_tables = [t for t in Base.metadata.sorted_tables if t is not AssistantDraft.__table__]
            await conn.run_sync(lambda c: Base.metadata.create_all(c,tables=old_tables))
        async with sessions() as db:
            db.add(Org(id="org",name="synthetic")); db.add(User(id="user",org_id="org",username="synthetic",hashed_password="unused"))
            db.add(Case(id="case",org_id="org",title="synthetic",created_by="user"))
            db.add(ArchiveTask(id=1,case_id="case",revision=1,source_version="source")); await db.commit()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(Base.metadata.create_all)
            assert "assistant_drafts" in await conn.run_sync(lambda c:inspect(c).get_table_names())
        scope = store.DraftScope("org","user","case",1)
        async def write(value, expected):
            async with sessions() as db:
                try:
                    row = await store.write_draft(db,scope,content=value,expected_version=expected,revision=1,source_version="source")
                    return row.version
                except store.DraftConflict:
                    return "conflict"
        outcomes = await asyncio.gather(write("A",0),write("B",0))
        assert sorted(outcomes,key=str) == [1,"conflict"]
        outcomes = await asyncio.gather(write("C",1),write("D",1))
        assert sorted(outcomes,key=str) == [2,"conflict"]
        async with sessions() as db:
            assert (await store.read_draft(db,scope)).version == 2
            assert (await db.get(ArchiveTask,1)).source_version == "source"
        assert engine.sync_engine.hide_parameters is True
    finally:
        await engine.dispose()
