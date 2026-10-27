"""Independent synthetic audit probes; no model, live database, or renderer."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_assistant_history import conversation, context, upload_context, post, url
from tests.test_assistant_proposal import command
from tests.test_assistant_journal import SimulatedProcessLoss, interrupted_adoption
from app.models import ArchiveTask, AssistantTurn, TaskStatus
from app.services import case_assistant, assistant_history, assistant_journal, archive_service
from app.services.analysis_snapshot import load_snapshot_data


async def newer_task(ctx):
    async with ctx.sessions() as db:
        old = await db.get(ArchiveTask, ctx.task_id)
        current = ArchiveTask(case_id=old.case_id, created_by=old.created_by,
            status=TaskStatus.awaiting_review, revision=1,
            source_version=old.source_version, source_manifest=copy.deepcopy(old.source_manifest),
            fields=copy.deepcopy(old.fields), parent_task_id=old.id)
        db.add(current)
        await db.commit()
        return current.id


@pytest.mark.asyncio
async def test_pending_proposal_cannot_edit_superseded_task(conversation, monkeypatch):
    ctx = conversation
    monkeypatch.setattr(case_assistant, "select_tool", lambda *_: command())
    proposed = await post(ctx, message="请把合同号改为虚构合同2")
    assert proposed.status_code == 200
    proposal_id = proposed.json()["proposal"]["id"]
    before = load_snapshot_data(ctx.work)
    new_id = await newer_task(ctx)
    normal = await ctx.client.patch(f"/api/tasks/{ctx.task_id}/fields", json={"fields":{"合同号":"虚构合同2"}})
    assert normal.status_code == 409 and "历史任务" in normal.text
    adopted = await ctx.client.post(url(ctx) + "/proposals/apply", json={
        "proposal_id":proposal_id, "expected_revision":3})
    async with ctx.sessions() as db:
        old = await db.get(ArchiveTask, ctx.task_id)
        current = await db.get(ArchiveTask, new_id)
        observed = {"http_status":adopted.status_code, "old_revision":old.revision,
                    "old_field_changed":old.fields["合同号"] != before["fields"]["合同号"],
                    "new_revision":current.revision}
    assert adopted.status_code == 409, observed
    assert load_snapshot_data(ctx.work) == before


@pytest.mark.asyncio
async def test_superseded_history_readable_but_cannot_start_model_or_reissue_ticket(conversation, monkeypatch):
    ctx = conversation
    monkeypatch.setattr(case_assistant, "select_tool", lambda *_: command())
    message = "请把合同号改为虚构合同2"
    response = await post(ctx, message=message)
    assert response.status_code == 200
    proposal_id = response.json()["proposal"]["id"]
    await newer_task(ctx)
    monkeypatch.setattr(case_assistant, "select_tool", lambda *_: pytest.fail("historical task must not start a model"))
    response = await post(ctx, ident="historical-new-request", message=message)
    assert response.status_code == 409 and "历史任务" in response.text
    replay = await post(ctx, message=message)
    assert replay.status_code == 200 and replay.json()["proposal_state"] == "stale"
    assert "proposal_token" not in replay.json()["proposal"]
    history = await ctx.client.get(url(ctx) + "/history")
    assert history.status_code == 200 and not history.json()["source_changed"]
    assert history.json()["messages"][1]["proposal_state"] == "stale"
    for headers in ({"X-Test-User":"peer"}, {"X-Test-Org":"org-b", "X-Test-Role":"admin"}):
        assert (await ctx.client.get(url(ctx) + "/history", headers=headers)).status_code == 404
        assert (await ctx.client.post(url(ctx) + "/proposals/apply", headers=headers,
            json={"proposal_id":proposal_id, "expected_revision":3})).status_code == 404


@pytest.mark.asyncio
async def test_superseded_task_can_recover_prior_journal_but_cannot_adopt_again(conversation, monkeypatch):
    ctx = conversation
    proposal, before = await interrupted_adoption(ctx, monkeypatch)
    await newer_task(ctx)
    monkeypatch.setattr(case_assistant, "select_tool", lambda *_: pytest.fail("recovery must never call model"))
    response = await ctx.client.post(url(ctx) + "/proposals/apply", json={
        "proposal_id":proposal["id"], "expected_revision":3, "recover_only":True})
    assert response.status_code == 409 and "恢复原字段" in response.text
    assert load_snapshot_data(ctx.work) == before
    response = await ctx.client.post(url(ctx) + "/proposals/apply", json={
        "proposal_id":proposal["id"], "expected_revision":3})
    assert response.status_code == 409 and "历史任务" in response.text
    async with ctx.sessions() as db:
        assert (await db.get(ArchiveTask, ctx.task_id)).revision == 3


@pytest.mark.asyncio
async def test_history_expiry_cannot_erase_interrupted_adoption_journal(conversation, monkeypatch):
    """Expiry read started before the journal commit must not overwrite applying.

    Delays emulate I/O scheduling; a controlled clock crosses the existing
    fifteen-minute expiry only after adoption has already validated the ticket.
    """
    ctx = conversation
    monkeypatch.setattr(case_assistant, "select_tool", lambda *_: command())
    proposed = await post(ctx, message="请把合同号改为虚构合同2")
    assert proposed.status_code == 200
    proposal_id = proposed.json()["proposal"]["id"]
    before = load_snapshot_data(ctx.work)
    journal_wait, permit_journal = asyncio.Event(), asyncio.Event()
    history_wait, permit_history = asyncio.Event(), asyncio.Event()
    real_commit = AsyncSession.commit
    real_update = archive_service.update_task_fields

    async def interleaved_commit(db):
        states = [obj.proposal_state for obj in db.dirty if isinstance(obj, AssistantTurn)]
        if "applying" in states:
            journal_wait.set()
            await asyncio.wait_for(permit_journal.wait(), 5)
        if "expired" in states:
            history_wait.set()
            await asyncio.wait_for(permit_history.wait(), 5)
        return await real_commit(db)

    async def write_then_process_loss(*args, **kwargs):
        await real_update(*args, **kwargs)
        raise SimulatedProcessLoss()

    class AfterExpiry(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz or timezone.utc) + timedelta(hours=1)

    monkeypatch.setattr(AsyncSession, "commit", interleaved_commit)
    monkeypatch.setattr(archive_service, "update_task_fields", write_then_process_loss)
    adopting = asyncio.create_task(ctx.client.post(url(ctx) + "/proposals/apply", json={
        "proposal_id":proposal_id, "expected_revision":3}))
    reading = None
    try:
        await asyncio.wait_for(journal_wait.wait(), 5)
        monkeypatch.setattr(assistant_history, "datetime", AfterExpiry)
        reading = asyncio.create_task(ctx.client.get(url(ctx) + "/history"))
        # A correct history route waits for the case lock and never reaches its
        # expiry write here. The old route reaches this barrier immediately.
        history_barrier = asyncio.create_task(history_wait.wait())
        try:
            await asyncio.wait({history_barrier}, timeout=0.25)
        finally:
            history_barrier.cancel()
        permit_journal.set()
        with pytest.raises(SimulatedProcessLoss):
            await adopting
        assert load_snapshot_data(ctx.work)["fields"]["合同号"] == "虚构合同2"
        permit_history.set()
        assert (await reading).status_code == 200
        async with ctx.sessions() as db:
            turn = await db.scalar(select(AssistantTurn))
            task = await db.get(ArchiveTask, ctx.task_id)
            observed = {"proposal_state":turn.proposal_state,
                        "journal_retained":turn.snapshot_before == before,
                        "db_revision":task.revision,
                        "db_still_original":task.fields["合同号"] == "虚构合同1",
                        "snapshot_changed":load_snapshot_data(ctx.work) != before,
                        "guard_detects_pending_restore":await assistant_journal.has_unresolved(db, case_id=task.case_id)}
            assert turn.proposal_state == "applying", observed
            assert await assistant_journal.recover_applications(db) == ["restored"]
            await db.commit()
        assert load_snapshot_data(ctx.work) == before
    finally:
        permit_journal.set()
        permit_history.set()
        for work in (adopting, reading):
            if work is not None and not work.done():
                work.cancel()
