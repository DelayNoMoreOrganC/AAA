"""Independent recovery composition probes: real ASGI, synthetic SQLite/files only."""
import asyncio
import hashlib
from io import BytesIO
import threading

from PIL import Image
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_file_import_api import upload_context, pdf_bytes
from tests.test_upload_idempotency import send, records
from app.models import ArchiveTask, Case, Role, TaskStatus, UploadIntent, User
from app.routers import cases


@pytest_asyncio.fixture
async def recovery_context(upload_context, monkeypatch):
    # Independent pytest event loops must not inherit a previously contended
    # singleton lock. Each test still exercises one real case lock and DB.
    monkeypatch.setattr(cases.task_manager, "_case_locks", {})
    return upload_context


def endpoint(key=None, case_id="case-a"):
    path=f"/api/cases/{case_id}/upload-intents"
    return path if key is None else path+"/"+key


def metadata(data, name="虚构材料.pdf", doc_type="default"):
    return {"filename":name,"file_size":len(data),"sha256":hashlib.sha256(data).hexdigest(),"doc_type":doc_type}


async def register(ctx, data, key="independent-001", name="虚构材料.pdf", **kwargs):
    case_id=kwargs.pop("case_id","case-a")
    return await ctx.client.put(endpoint(key,case_id),json=metadata(data,name),**kwargs)


async def listing(ctx, **kwargs):
    case_id=kwargs.pop("case_id","case-a")
    result=await ctx.client.get(endpoint(case_id=case_id),**kwargs)
    assert result.status_code==200
    return result.json()


@pytest.mark.asyncio
async def test_register_replay_is_metadata_only_and_immutable(recovery_context, monkeypatch):
    ctx=recovery_context; data=pdf_bytes("Synthetic registered source")
    first=await register(ctx,data)
    assert first.status_code==200 and first.json()["status"]=="pending"
    assert (await register(ctx,data)).json()==first.json()
    assert (await register(ctx,pdf_bytes("Different fictional bytes"))).status_code==409
    assert (await register(ctx,data,name="不同名称.pdf")).status_code==409
    assert len((await listing(ctx))["items"])==1
    assert await records(ctx)==[] and not list(ctx.root.rglob("original.*"))
    async def forbid_commit(_): raise AssertionError("GET may not mutate queue state")
    monkeypatch.setattr(AsyncSession,"commit",forbid_commit)
    assert (await listing(ctx))["items"][0]["status"]=="pending"


@pytest.mark.asyncio
async def test_scope_is_private_across_case_owner_admin_and_organization(recovery_context):
    ctx=recovery_context; data=pdf_bytes("Synthetic private metadata")
    async with ctx.sessions() as db:
        db.add(User(id="synthetic-admin",org_id="org-a",username="synthetic-upload-admin",hashed_password="unused",role=Role.admin))
        db.add(Case(id="case-second",title="另一虚构案",case_type="civil",org_id="org-a",created_by="test-user"))
        await db.commit()
    assert (await register(ctx,data)).status_code==200
    admin={"X-Test-User":"synthetic-admin","X-Test-Role":"admin"}
    assert (await listing(ctx,headers=admin))["items"]==[]
    assert (await register(ctx,data,headers=admin)).status_code==200
    assert (await register(ctx,data,case_id="case-second")).status_code==200
    assert len((await listing(ctx))["items"])==1
    for denied in ({"X-Test-User":"peer"},{"X-Test-Org":"org-b","X-Test-Role":"admin"}):
        assert (await ctx.client.get(endpoint(),headers=denied)).status_code==404
        assert (await register(ctx,data,headers=denied)).status_code==404
        assert (await ctx.client.delete(endpoint("independent-001"),headers=denied)).status_code==404
    async with ctx.sessions() as db:
        assert len(list(await db.scalars(select(UploadIntent))))==3


@pytest.mark.asyncio
@pytest.mark.parametrize("after_commit",[False,True])
async def test_registration_commit_error_is_recoverable_without_new_key(recovery_context,monkeypatch,after_commit):
    ctx=recovery_context; data=pdf_bytes("Synthetic registration transaction")
    real=AsyncSession.commit; attempts=0
    async def fail_once(db):
        nonlocal attempts
        attempts+=1
        if attempts==1:
            if after_commit: await real(db)
            raise OSError("PRIVATE_SYNTHETIC_REGISTRATION_ERROR")
        await real(db)
    monkeypatch.setattr(AsyncSession,"commit",fail_once)
    result=await register(ctx,data)
    assert result.status_code>=500 and "PRIVATE_SYNTHETIC" not in result.text
    assert len((await listing(ctx))["items"])==(1 if after_commit else 0)
    assert (await register(ctx,data)).status_code==200
    assert len((await listing(ctx))["items"])==1 and await records(ctx)==[]


@pytest.mark.asyncio
@pytest.mark.parametrize("after_commit",[False,True])
async def test_upload_receipt_and_completed_state_share_one_transaction(recovery_context,monkeypatch,after_commit):
    ctx=recovery_context; data=pdf_bytes("Synthetic upload atomic transaction")
    assert (await register(ctx,data)).status_code==200
    real=AsyncSession.commit; attempts=0
    async def fail_once(db):
        nonlocal attempts
        attempts+=1
        if attempts==1:
            if after_commit: await real(db)
            raise OSError("PRIVATE_SYNTHETIC_UPLOAD_COMMIT_ERROR")
        await real(db)
    monkeypatch.setattr(AsyncSession,"commit",fail_once)
    result=await send(ctx,data,key="independent-001")
    assert "PRIVATE_SYNTHETIC" not in result.text
    if after_commit:
        assert result.status_code==200
        assert (await listing(ctx))["items"][0]["status"]=="completed"
    else:
        assert result.status_code>=500
        assert (await listing(ctx))["items"][0]["status"]=="pending"
        assert await records(ctx)==[] and not list(ctx.root.rglob("original.pdf"))
    assert (await send(ctx,data,key="independent-001")).status_code==200
    assert len(await records(ctx))==1 and len(list(ctx.root.rglob("original.pdf")))==1
    assert (await listing(ctx))["items"][0]["status"]=="completed"


@pytest.mark.asyncio
async def test_cancelled_key_is_a_tombstone_and_cannot_resurrect_upload(recovery_context):
    ctx=recovery_context; data=pdf_bytes("Synthetic cancelled source")
    assert (await register(ctx,data)).status_code==200
    first=await ctx.client.delete(endpoint("independent-001"))
    assert first.status_code==200 and first.json()["status"]=="cancelled"
    assert (await ctx.client.delete(endpoint("independent-001"))).json()==first.json()
    assert (await register(ctx,data)).json()["status"]=="cancelled"
    assert (await send(ctx,data,key="independent-001")).status_code==409
    assert await records(ctx)==[] and not list(ctx.root.rglob("original.pdf"))


@pytest.mark.asyncio
async def test_cancel_waiting_on_inflight_upload_cannot_delete_the_committed_source(recovery_context,monkeypatch):
    ctx=recovery_context; data=pdf_bytes("Synthetic real in-flight race")
    assert (await register(ctx,data)).status_code==200
    entered,release=threading.Event(),threading.Event(); real=cases.normalize_import
    def slow(*args):
        entered.set();assert release.wait(10)
        return real(*args)
    monkeypatch.setattr(cases,"normalize_import",slow)
    uploading=asyncio.create_task(send(ctx,data,key="independent-001"))
    cancelling=None
    try:
        assert await asyncio.to_thread(entered.wait,5)
        cancelling=asyncio.create_task(ctx.client.delete(endpoint("independent-001")))
        await asyncio.sleep(0)
        assert not cancelling.done()
    finally:
        release.set()
    result=await uploading
    assert result.status_code==200 and (await cancelling).status_code==409
    assert len(await records(ctx))==1
    assert (await listing(ctx))["items"][0]["status"]=="completed"
    assert (ctx.root/(await records(ctx))[0].stored_name).read_bytes()==data


@pytest.mark.asyncio
async def test_duplicate_occurrences_are_distinct_but_same_key_changed_bytes_are_rejected(recovery_context):
    ctx=recovery_context; data=pdf_bytes("Synthetic identical intentional occurrences")
    for key in ("independent-a","independent-b"):
        assert (await register(ctx,data,key)).status_code==200
    assert (await send(ctx,pdf_bytes("Different bytes"),key="independent-a")).status_code==409
    assert await records(ctx)==[]
    first=await send(ctx,data,key="independent-a")
    second=await send(ctx,data,key="independent-b")
    assert first.status_code==second.status_code==200 and first.json()["id"]!=second.json()["id"]
    assert len(await records(ctx))==2
    assert [item["status"] for item in (await listing(ctx))["items"]]==["completed","completed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("damage",["original","normalized","missing_record"])
async def test_completed_but_damaged_receipt_is_unavailable_without_get_write_or_old_key_rebuild(recovery_context,monkeypatch,damage):
    ctx=recovery_context; stream=BytesIO(); Image.new("RGB",(30,40),"white").save(stream,format="PNG")
    data=stream.getvalue(); name="虚构扫描.png"
    assert (await register(ctx,data,name=name)).status_code==200
    assert (await send(ctx,data,key="independent-001",filename=name)).status_code==200
    file=(await records(ctx))[0]; stored=ctx.root/file.stored_name
    if damage=="original":(stored.parent/"original.png").write_bytes(b"synthetic-corruption")
    elif damage=="normalized":stored.write_bytes(pdf_bytes("Synthetic changed normalization"))
    else:
        async with ctx.sessions() as db:
            from sqlalchemy import delete
            from app.models import CaseFile
            await db.execute(delete(CaseFile).where(CaseFile.id==file.id));await db.commit()
    real=AsyncSession.commit
    async def no_get_commit(_):raise AssertionError("GET must only project unavailable")
    monkeypatch.setattr(AsyncSession,"commit",no_get_commit)
    assert (await listing(ctx))["items"][0]["status"]=="unavailable"
    monkeypatch.setattr(AsyncSession,"commit",real)
    assert (await register(ctx,data,name=name)).json()["status"]=="unavailable"
    assert (await send(ctx,data,key="independent-001",filename=name)).status_code==409
    async with ctx.sessions() as db:
        intent=await db.scalar(select(UploadIntent))
        assert intent.status=="completed"


@pytest.mark.asyncio
async def test_running_task_blocks_new_intent_but_not_completed_receipt_recovery(recovery_context):
    ctx=recovery_context; data=pdf_bytes("Synthetic existing completed receipt")
    assert (await register(ctx,data)).status_code==200
    first=await send(ctx,data,key="independent-001")
    async with ctx.sessions() as db:
        db.add(ArchiveTask(case_id="case-a",status=TaskStatus.running));await db.commit()
    state=await listing(ctx)
    assert not state["writable"] and state["items"][0]["status"]=="completed"
    assert (await register(ctx,data)).status_code==200
    assert (await send(ctx,data,key="independent-001")).json()["id"]==first.json()["id"]
    assert (await register(ctx,data,key="independent-new")).status_code==409
    assert len(await records(ctx))==1


@pytest.mark.asyncio
async def test_private_pending_queue_blocks_generation_without_exposing_owner_filename(recovery_context,monkeypatch):
    ctx=recovery_context; data=pdf_bytes("Synthetic pending requirement")
    assert (await send(ctx,data,key="already-complete")).status_code==200
    secret_name="虚构私人待办文件名.pdf"
    assert (await register(ctx,data,name=secret_name)).status_code==200
    monkeypatch.setattr(cases.task_manager,"start",lambda *_:pytest.fail("pending queue may not start model task"))
    result=await ctx.client.post("/api/cases/case-a/generate",json={"order_mode":"catalog"},headers={"X-Test-User":"synthetic-admin","X-Test-Role":"admin"})
    assert result.status_code==409 and secret_name not in result.text
    assert "未完成" in result.text and "导入" in result.text


@pytest.mark.asyncio
async def test_case_delete_rolls_back_queue_then_removes_it_with_case(recovery_context,monkeypatch):
    ctx=recovery_context; data=pdf_bytes("Synthetic queue deletion")
    assert (await register(ctx,data)).status_code==200
    real=AsyncSession.commit
    async def failure(_):raise OSError("PRIVATE_SYNTHETIC_DELETE_FAILURE")
    monkeypatch.setattr(AsyncSession,"commit",failure)
    failed=await ctx.client.delete("/api/cases/case-a")
    assert failed.status_code>=500 and "PRIVATE_SYNTHETIC" not in failed.text
    monkeypatch.setattr(AsyncSession,"commit",real)
    assert len((await listing(ctx))["items"])==1
    assert (await ctx.client.delete("/api/cases/case-a")).status_code==204
    async with ctx.sessions() as db:
        assert list(await db.scalars(select(UploadIntent)))==[]
