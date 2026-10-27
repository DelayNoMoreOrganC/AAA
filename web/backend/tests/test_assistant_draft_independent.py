"""Independent real-ASGI composition probes; synthetic DB/PDF, model stub only."""
import asyncio
import threading

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_assistant_history import conversation, context, upload_context, url, choose
from tests.test_file_import_api import upload
from app.models import ArchiveTask, AssistantDraft, AssistantTurn, Role, User
from app.services import case_assistant
from app.services.analysis_snapshot import load_snapshot_data


async def read(ctx, **kwargs):
    return await ctx.client.get(url(ctx)+"/draft", **kwargs)


async def put(ctx, content, version, *, revision=3, source=None, **kwargs):
    if source is None:
        async with ctx.sessions() as db:
            source=(await db.get(ArchiveTask,ctx.task_id)).source_version
    return await ctx.client.put(url(ctx)+"/draft",json={"content":content,"expected_version":version,
        "expected_revision":revision,"source_version":source},**kwargs)


async def send(ctx, content, version, request_id="independent-send-001"):
    async with ctx.sessions() as db:
        task=await db.get(ArchiveTask,ctx.task_id)
        payload={"message":content,"request_id":request_id,"expected_revision":task.revision,
                 "source_version":task.source_version,"draft_version":version}
    return await ctx.client.post(url(ctx),json=payload)


@pytest.mark.asyncio
async def test_get_is_read_only_and_initial_empty_save_blocks_version_zero_writer(conversation):
    ctx=conversation
    first=await read(ctx)
    assert first.status_code==200 and first.json()["version"]==0 and first.json()["content"]==""
    async with ctx.sessions() as db:
        assert list((await db.scalars(select(AssistantDraft))).all())==[]
    cleared=await put(ctx,"",0)
    assert cleared.status_code==200 and cleared.json()["version"]==1
    assert (await put(ctx,"旧标签尚未同步的文字",0)).status_code==409
    again=await read(ctx)
    assert again.json()["content"]=="" and again.json()["version"]==1


@pytest.mark.asyncio
async def test_drafts_are_private_even_between_same_org_admin_and_owner(conversation):
    ctx=conversation
    async with ctx.sessions() as db:
        db.add(User(id="other-admin",org_id="org-a",username="fictional-draft-admin",
                    hashed_password="synthetic-unused",role=Role.admin))
        await db.commit()
    assert (await put(ctx,"虚构甲的私人未发送要求",0)).status_code==200
    headers={"X-Test-User":"other-admin","X-Test-Role":"admin"}
    assert (await read(ctx,headers=headers)).json()["content"]==""
    assert (await put(ctx,"虚构管理员自己的要求",0,headers=headers)).status_code==200
    assert (await read(ctx)).json()["content"]=="虚构甲的私人未发送要求"
    for denied in ({"X-Test-User":"peer"},{"X-Test-Org":"org-b","X-Test-Role":"admin"}):
        assert (await read(ctx,headers=denied)).status_code==404
        assert (await put(ctx,"不得写入",1,headers=denied)).status_code==404


@pytest.mark.asyncio
async def test_lost_save_ack_replay_is_exact_and_cannot_overwrite_later_aba(conversation):
    ctx=conversation
    first=await put(ctx,"虚构要求A",0)
    replay=await put(ctx,"虚构要求A",0)
    assert first.status_code==replay.status_code==200
    assert first.json()["version"]==replay.json()["version"]==1
    assert (await put(ctx,"虚构要求B",1)).json()["version"]==2
    assert (await put(ctx,"虚构要求A",2)).json()["version"]==3
    assert (await put(ctx,"虚构要求A",0)).status_code==409
    assert (await read(ctx)).json()["version"]==3


@pytest.mark.asyncio
async def test_new_revision_requires_explicit_context_and_does_not_rebind_on_get(conversation):
    ctx=conversation
    saved=(await put(ctx,"仍待核对的虚构要求",0)).json()
    async with ctx.sessions() as db:
        task=await db.get(ArchiveTask,ctx.task_id);task.revision=4
        await db.commit()
    response=await read(ctx)
    assert response.json()["revision"]==3 and response.json()["task_revision"]==4
    assert response.json()["content"]==saved["content"] and response.json()["notice"]
    assert (await put(ctx,"旧页面尝试保存",1)).status_code==409
    explicit=await put(ctx,saved["content"],1,revision=4)
    assert explicit.status_code==200 and explicit.json()["revision"]==4 and explicit.json()["version"]==2


@pytest.mark.asyncio
async def test_send_reservation_failure_keeps_unsent_draft_and_calls_no_model(conversation,monkeypatch):
    ctx=conversation
    saved=(await put(ctx,"虚构事务失败要求",0)).json()
    monkeypatch.setattr(case_assistant,"select_tool",lambda *_:pytest.fail("uncommitted request must not call model"))
    async def fail_reservation(db):
        raise OSError("SYNTHETIC_SECRET_TRANSACTION_BODY")
    monkeypatch.setattr(AsyncSession,"commit",fail_reservation)
    response=await send(ctx,saved["content"],saved["version"])
    assert response.status_code==503 and "SYNTHETIC_SECRET" not in response.text
    current=(await read(ctx)).json()
    assert current["content"]==saved["content"] and current["version"]==saved["version"]
    async with ctx.sessions() as db:
        assert list((await db.scalars(select(AssistantTurn))).all())==[]


@pytest.mark.asyncio
async def test_failed_model_keeps_actual_message_history_but_never_restores_consumed_input(conversation,monkeypatch):
    ctx=conversation
    text="虚构模型失败后的问题"
    saved=(await put(ctx,text,0)).json()
    calls=[]
    def fail(*_):
        calls.append(1)
        raise case_assistant.AssistantUnavailable("本机模型暂未就绪")
    monkeypatch.setattr(case_assistant,"select_tool",fail)
    result=await send(ctx,text,saved["version"])
    assert result.status_code==503 and calls==[1]
    current=(await read(ctx)).json()
    assert current["content"]=="" and current["version"]==saved["version"]+1
    assert current["consumed_request_id"]=="independent-send-001"
    async with ctx.sessions() as db:
        turn=await db.scalar(select(AssistantTurn))
        assert turn.user_message==text and turn.status=="failed"
    assert (await send(ctx,text,saved["version"])).status_code==503 and calls==[1]


@pytest.mark.asyncio
async def test_send_in_flight_new_input_and_old_request_replay_never_clear_new_text(conversation,monkeypatch):
    ctx=conversation
    text="虚构先发出的要求"
    saved=(await put(ctx,text,0)).json()
    before=load_snapshot_data(ctx.work)
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def slow(*_):
        calls.append(1);entered.set()
        assert release.wait(10)
        return choose()
    monkeypatch.setattr(case_assistant,"select_tool",slow)
    running=asyncio.create_task(send(ctx,text,saved["version"]))
    try:
        assert await asyncio.to_thread(entered.wait,5)
        consumed=(await read(ctx)).json()
        assert consumed["content"]=="" and consumed["consumed_request_id"]=="independent-send-001"
        newer=await put(ctx,"发送期间另写的新要求",consumed["version"])
        assert newer.status_code==200 and not newer.json().get("consumed_request_id")
        duplicate=await send(ctx,text,saved["version"])
        assert duplicate.status_code==409 and calls==[1]
    finally:
        release.set()
    assert (await running).status_code==200
    assert (await send(ctx,text,saved["version"])).status_code==200 and calls==[1]
    assert (await read(ctx)).json()["content"]=="发送期间另写的新要求"
    assert load_snapshot_data(ctx.work)==before


@pytest.mark.asyncio
async def test_new_material_prevents_consumption_or_model_and_preserves_old_draft(conversation,monkeypatch):
    ctx=conversation
    saved=(await put(ctx,"依据原材料写下的要求",0)).json()
    await upload(ctx,name="本次虚构新增材料.pdf")
    monkeypatch.setattr(case_assistant,"select_tool",lambda *_:pytest.fail("changed source cannot call model"))
    assert (await send(ctx,saved["content"],saved["version"])).status_code==409
    current=(await read(ctx)).json()
    assert not current["writable"] and current["content"]==saved["content"] and current["version"]==1


@pytest.mark.asyncio
async def test_case_delete_commit_failure_preserves_draft_then_success_removes_it(conversation,monkeypatch):
    ctx=conversation
    assert (await put(ctx,"虚构删除回滚草稿",0)).status_code==200
    real_commit=AsyncSession.commit
    async def fail_commit(_): raise OSError("SYNTHETIC_DELETE_SECRET")
    monkeypatch.setattr(AsyncSession,"commit",fail_commit)
    response=await ctx.client.delete("/api/cases/case-a")
    assert response.status_code==503 and "SYNTHETIC_DELETE_SECRET" not in response.text
    monkeypatch.setattr(AsyncSession,"commit",real_commit)
    assert (await read(ctx)).json()["content"]=="虚构删除回滚草稿"
    assert (await ctx.client.delete("/api/cases/case-a")).status_code==204
    async with ctx.sessions() as db:
        assert list((await db.scalars(select(AssistantDraft))).all())==[]
