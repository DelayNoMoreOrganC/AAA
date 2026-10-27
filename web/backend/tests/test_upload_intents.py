"""Offline synthetic upload-intent recovery and transactional boundaries."""
import asyncio
import hashlib
import threading

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.test_file_import_api import upload_context, pdf_bytes
from tests.test_upload_idempotency import send, records
from app.database import Base, get_db
from app.main import app
from app.models import ArchiveTask, Case, CaseFile, Org, Role, TaskStatus, UploadIntent, User
from app.routers import cases
from app.services import upload_intents as store


@pytest_asyncio.fixture
async def intent_context(upload_context, monkeypatch):
    monkeypatch.setattr(cases.task_manager, "_case_locks", {})
    return upload_context


def endpoint(case="case-a", key=None):
    return f"/api/cases/{case}/upload-intents" + (f"/{key}" if key else "")


def metadata(data, filename="虚构材料.pdf", doc_type="default"):
    return {"filename":filename,"file_size":len(data),"sha256":hashlib.sha256(data).hexdigest(),"doc_type":doc_type}


async def register(ctx, data, key="intent-001", **kwargs):
    return await ctx.client.put(endpoint(kwargs.pop("case_id","case-a"),key),json=metadata(data,**kwargs))


async def listed(ctx, **kwargs):
    response = await ctx.client.get(endpoint(),**kwargs)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_registration_reload_upload_atomic_receipt_and_lost_ack(intent_context):
    ctx = intent_context; data = pdf_bytes("Fictional recovery")
    assert (await listed(ctx))["items"] == []
    registered = await register(ctx,data)
    assert registered.status_code == 200 and registered.json()["status"] == "pending"
    assert (await register(ctx,data)).json() == registered.json()
    async with ctx.sessions() as db:
        assert len(list(await db.scalars(select(UploadIntent)))) == 1
        assert list(await db.scalars(select(CaseFile))) == []
    uploaded = await send(ctx,data,key="intent-001")
    assert uploaded.status_code == 200
    restored = (await listed(ctx))["items"][0]
    assert restored["status"] == "completed" and restored["file_id"] == uploaded.json()["id"]
    assert set(restored) == {"request_id","filename","file_size","sha256","doc_type","status","file_id","created_at","updated_at"}
    assert (await send(ctx,data,key="intent-001")).json() == uploaded.json()
    assert (await register(ctx,data)).json()["status"] == "completed"
    assert len(await records(ctx)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["bytes","name","type","size"])
async def test_registered_metadata_immutable_and_wrong_selected_source_not_imported(intent_context,change):
    ctx = intent_context; data=pdf_bytes("Fictional identity")
    await register(ctx,data)
    body=metadata(data)
    body[{"bytes":"sha256","name":"filename","type":"doc_type","size":"file_size"}[change]] = {
        "bytes":"f"*64,"name":"另一材料.pdf","type":"evidence","size":len(data)+1}[change]
    assert (await ctx.client.put(endpoint(key="intent-001"),json=body)).status_code == 409
    response=await send(ctx,pdf_bytes("Changed") if change in ("bytes","size") else data,key="intent-001",
        filename="另一材料.pdf" if change=="name" else "虚构材料.pdf",doc_type="evidence" if change=="type" else "default")
    assert response.status_code == 409
    assert not await records(ctx) and not list(ctx.root.rglob("original.pdf"))
    assert (await listed(ctx))["items"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_cancel_keeps_tombstone_never_deletes_material_or_restarts_old_key(intent_context):
    ctx=intent_context; data=pdf_bytes("Fictional cancelled")
    await register(ctx,data)
    cancelled=await ctx.client.delete(endpoint(key="intent-001"))
    assert cancelled.status_code==200 and cancelled.json()["status"]=="cancelled"
    assert (await ctx.client.delete(endpoint(key="intent-001"))).json()==cancelled.json()
    assert (await register(ctx,data)).json()==cancelled.json()
    assert (await send(ctx,data,key="intent-001")).status_code==409
    assert not await records(ctx) and not list(ctx.root.rglob("original.pdf"))
    await register(ctx,data,key="new-intent")
    uploaded=await send(ctx,data,key="new-intent")
    assert uploaded.status_code==200
    assert (await ctx.client.delete(endpoint(key="new-intent"))).status_code==409
    assert len(await records(ctx))==1


@pytest.mark.asyncio
@pytest.mark.parametrize("which",["original","normalized","deleted"])
async def test_completed_missing_or_changed_receipt_projects_unavailable_without_rebuilding(intent_context,which):
    ctx=intent_context; data=pdf_bytes("Fictional unavailable")
    await register(ctx,data); result=await send(ctx,data,key="intent-001")
    row=(await records(ctx))[0]
    if which=="deleted":
        assert (await ctx.client.delete(f"/api/cases/case-a/files/{row.id}")).status_code==204
    else:
        normalized=ctx.root/row.stored_name
        path=cases.original_file(ctx.root/"org-a"/"cases"/"case-a",normalized) if which=="original" else normalized
        path.write_bytes(b"Fictional damaged receipt")
    assert (await listed(ctx))["items"][0]["status"]=="unavailable"
    assert (await register(ctx,data)).json()["status"]=="unavailable"
    assert (await send(ctx,data,key="intent-001")).status_code==409
    async with ctx.sessions() as db:
        item=await db.scalar(select(UploadIntent))
        assert item.status=="completed" and item.file_id==result.json()["id"]
    assert len(await records(ctx))==(0 if which=="deleted" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure",["before_commit","after_commit"])
async def test_upload_commit_and_intent_completion_are_atomic(intent_context,monkeypatch,failure):
    ctx=intent_context; data=pdf_bytes("Fictional transaction")
    await register(ctx,data)
    original=AsyncSession.commit; tripped=[]
    async def fail_once(db):
        if not tripped and any(isinstance(item,CaseFile) for item in db.identity_map.values()):
            tripped.append(True)
            if failure=="after_commit":
                await original(db)
            raise RuntimeError("SYNTHETIC_PRIVATE_COMMIT_DIAGNOSTIC")
        return await original(db)
    monkeypatch.setattr(AsyncSession,"commit",fail_once)
    result=await send(ctx,data,key="intent-001")
    assert tripped and "SYNTHETIC_PRIVATE" not in result.text
    state=(await listed(ctx))["items"][0]
    if failure=="before_commit":
        assert result.status_code==500 and state["status"]=="pending" and not await records(ctx)
        assert not list(ctx.root.rglob("original.pdf"))
    else:
        assert result.status_code==200 and state["status"]=="completed" and len(await records(ctx))==1
    assert (await send(ctx,data,key="intent-001")).status_code==200
    assert len(await records(ctx))==1


@pytest.mark.asyncio
async def test_registration_commit_ack_lost_recovers_same_item(intent_context,monkeypatch):
    ctx=intent_context; data=pdf_bytes("Fictional registration ack")
    original=AsyncSession.commit; tripped=[]
    async def lost(db):
        await original(db)
        if not tripped:
            tripped.append(True); raise RuntimeError("SYNTHETIC_PRIVATE_ACK")
    monkeypatch.setattr(AsyncSession,"commit",lost)
    first=await register(ctx,data)
    assert first.status_code==500 and "SYNTHETIC_PRIVATE" not in first.text
    state=(await listed(ctx))["items"][0]
    assert (await register(ctx,data)).json()==state
    async with ctx.sessions() as db:
        assert len(list(await db.scalars(select(UploadIntent))))==1


@pytest.mark.asyncio
async def test_failed_normalization_preserves_pending_for_retry(intent_context,monkeypatch):
    ctx=intent_context; data=pdf_bytes("Fictional parse retry")
    await register(ctx,data)
    original=cases.normalize_import
    def fail(*_):
        raise cases.ImportFailure("虚构转换失败")
    monkeypatch.setattr(cases,"normalize_import",fail)
    assert (await send(ctx,data,key="intent-001")).status_code==400
    assert (await listed(ctx))["items"][0]["status"]=="pending" and not await records(ctx)
    monkeypatch.setattr(cases,"normalize_import",original)
    assert (await send(ctx,data,key="intent-001")).status_code==200


@pytest.mark.asyncio
@pytest.mark.parametrize("status",[TaskStatus.pending,TaskStatus.running,TaskStatus.awaiting_review,TaskStatus.done,TaskStatus.failed])
async def test_busy_blocks_new_sources_but_allows_verified_completed_receipts(intent_context,status):
    ctx=intent_context; data=pdf_bytes("Fictional state")
    await register(ctx,data); result=await send(ctx,data,key="intent-001")
    async with ctx.sessions() as db:
        db.add(ArchiveTask(case_id="case-a",status=status)); await db.commit()
    blocking=status in (TaskStatus.pending,TaskStatus.running)
    assert (await listed(ctx))["writable"] is not blocking
    assert (await register(ctx,data,key="next-intent")).status_code==(409 if blocking else 200)
    assert (await send(ctx,data,key="legacy-new")).status_code==(409 if blocking else 200)
    assert (await send(ctx,data,key="intent-001")).json()==result.json()


@pytest.mark.asyncio
async def test_private_owner_queue_and_case_isolation(intent_context):
    ctx=intent_context; data=pdf_bytes("Fictional private queue")
    await register(ctx,data)
    for headers in ({"X-Test-User":"peer"},{"X-Test-Org":"org-b","X-Test-Role":"admin"}):
        assert (await ctx.client.get(endpoint(),headers=headers)).status_code==404
        assert (await ctx.client.delete(endpoint(key="intent-001"),headers=headers)).status_code==404
    admin={"X-Test-User":"admin-other","X-Test-Role":"admin"}
    assert (await listed(ctx,headers=admin))["items"]==[]
    assert (await ctx.client.delete(endpoint(key="intent-001"),headers=admin)).status_code==404
    assert (await ctx.client.put(endpoint(key="intent-001"),headers=admin,json=metadata(data))).status_code==200
    assert len((await listed(ctx))["items"])==1
    async with ctx.sessions() as db:
        db.add(Case(id="case-other",org_id="org-a",created_by="test-user",title="synthetic")); await db.commit()
    assert (await register(ctx,data,case_id="case-other")).status_code==200
    assert len((await listed(ctx))["items"])==1


@pytest.mark.asyncio
async def test_legacy_uploaded_receipt_can_be_registered_without_duplicate(intent_context):
    ctx=intent_context; data=pdf_bytes("Fictional pre-registration")
    result=await send(ctx,data,key="intent-001")
    registered=await register(ctx,data)
    assert registered.status_code==200 and registered.json()["status"]=="completed"
    assert registered.json()["file_id"]==result.json()["id"] and len(await records(ctx))==1


@pytest.mark.asyncio
async def test_concurrent_same_registration_and_case_cleanup(intent_context):
    ctx=intent_context; data=pdf_bytes("Fictional race")
    responses=await asyncio.gather(register(ctx,data),register(ctx,data),register(ctx,data))
    assert all(item.status_code==200 for item in responses) and len({item.text for item in responses})==1
    assert (await ctx.client.delete("/api/cases/case-a")).status_code==204
    async with ctx.sessions() as db:
        assert await db.scalar(select(UploadIntent)) is None


@pytest.mark.asyncio
async def test_cross_worker_cancel_wins_during_normalization_and_upload_rolls_back(intent_context,tmp_path):
    """Two independent DB connections; direct cancel bypasses in-process lock."""
    ctx=intent_context
    engine=create_async_engine("sqlite+aiosqlite:///"+str(tmp_path/"intent-race.db"),hide_parameters=True)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    old_db=app.dependency_overrides[get_db]
    original_normalize=cases.normalize_import
    entered,release=threading.Event(),threading.Event()
    async def test_db():
        async with sessions() as db:
            yield db
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            db.add(Org(id="org-a",name="synthetic")); db.add(User(id="test-user",org_id="org-a",username="synthetic",hashed_password="unused"))
            db.add(Case(id="case-a",org_id="org-a",title="synthetic",created_by="test-user")); await db.commit()
        app.dependency_overrides[get_db]=test_db
        data=pdf_bytes("Fictional cancellation wins")
        await register(ctx,data)
        def slow(*args):
            entered.set(); assert release.wait(10); return original_normalize(*args)
        cases.normalize_import=slow
        pending=asyncio.create_task(send(ctx,data,key="intent-001"))
        try:
            assert await asyncio.to_thread(entered.wait,5)
            async with sessions() as db:
                result=await store.cancel(db,store.Scope("org-a","test-user","case-a"),"intent-001",tmp_path)
                assert result["status"]=="cancelled"
        finally:
            release.set()
        assert (await pending).status_code==409
        async with sessions() as db:
            assert await db.scalar(select(CaseFile)) is None
            assert (await db.scalar(select(UploadIntent))).status=="cancelled"
        assert not list(ctx.root.rglob("original.pdf"))
    finally:
        cases.normalize_import=original_normalize
        app.dependency_overrides[get_db]=old_db
        await engine.dispose()


@pytest.mark.asyncio
async def test_old_database_adds_intent_table_without_losing_records_and_user_cascade(tmp_path):
    engine=create_async_engine("sqlite+aiosqlite:///"+str(tmp_path/"old-intent-schema.db"),hide_parameters=True)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c:Base.metadata.create_all(c,tables=[t for t in Base.metadata.sorted_tables if t is not UploadIntent.__table__]))
        async with sessions() as db:
            db.add(Org(id="org",name="synthetic")); db.add(User(id="owner",org_id="org",username="owner",hashed_password="unused"))
            db.add(User(id="only-intents",org_id="org",username="other",hashed_password="unused"))
            db.add(Case(id="case",org_id="org",title="preserved",created_by="owner")); await db.commit()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            assert "upload_intents" in await conn.run_sync(lambda c:inspect(c).get_table_names())
        async with sessions() as db:
            assert (await db.get(Case,"case")).title=="preserved"
            db.add(UploadIntent(org_id="org",user_id="only-intents",case_id="case",request_id="synthetic",**metadata(b"x")))
            await db.commit(); await db.delete(await db.get(User,"only-intents")); await db.commit()
            assert await db.scalar(select(UploadIntent)) is None
    finally:
        await engine.dispose()
