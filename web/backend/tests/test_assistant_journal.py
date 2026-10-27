"""Synthetic process-loss checkpoints; never kill a service or invoke a model."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_assistant_history import conversation, context, upload_context, post, url, messages
from tests.test_assistant_proposal import command
from app.models import ArchiveTask, AssistantTurn
from app.services import case_assistant as selector
from app.services import archive_service, assistant_journal as journal
from app.services.analysis_snapshot import load_snapshot_data


class SimulatedProcessLoss(BaseException):
    """Escapes ordinary exception rollback, exactly at the two-store boundary."""


async def interrupted_adoption(ctx, monkeypatch):
    monkeypatch.setattr(selector, "select_tool", lambda *_: command())
    response = await post(ctx, message="请把合同号改为虚构合同2")
    assert response.status_code == 200
    proposal = response.json()["proposal"]
    before = load_snapshot_data(ctx.work)
    real_update = archive_service.update_task_fields
    async def write_then_lose_process(*args, **kwargs):
        await real_update(*args, **kwargs)
        raise SimulatedProcessLoss()
    monkeypatch.setattr(archive_service, "update_task_fields", write_then_lose_process)
    with pytest.raises(SimulatedProcessLoss):
        await ctx.client.post(url(ctx) + "/proposals/apply", json={"proposal_id": proposal["id"], "expected_revision": 3})
    monkeypatch.setattr(archive_service, "update_task_fields", real_update)
    assert load_snapshot_data(ctx.work)["fields"]["合同号"] == "虚构合同2"
    async with ctx.sessions() as db:
        turn = await db.scalar(select(AssistantTurn))
        task = await db.get(ArchiveTask, ctx.task_id)
        assert turn.proposal_state == "applying" and turn.target_revision == 4
        assert turn.snapshot_before == before
        assert task.revision == 3 and task.fields["合同号"] == "虚构合同1"
    return proposal, before


@pytest.mark.asyncio
async def test_startup_recovers_file_written_but_db_not_committed_then_explicit_retry(conversation, monkeypatch):
    ctx = conversation
    proposal, before = await interrupted_adoption(ctx, monkeypatch)
    pending = (await messages(ctx))[1]
    assert pending["proposal_state"] == "applying" and "proposal_token" not in pending["proposal"]
    monkeypatch.setattr(selector, "select_tool", lambda *_: pytest.fail("recovery must not call a model"))
    from app import database
    monkeypatch.setattr(database, "engine", ctx.sessions.kw["bind"])
    monkeypatch.setattr(database, "DB_PATH", ctx.root / "synthetic-startup.sqlite")
    await database.init_db()
    assert load_snapshot_data(ctx.work) == before
    async with ctx.sessions() as db:
        turn = await db.scalar(select(AssistantTurn))
        assert turn.snapshot_before is None and turn.target_revision is None and turn.proposal_state == "pending"
        assert (await db.get(ArchiveTask, ctx.task_id)).revision == 3
        assert await journal.recover_applications(db) == []
    response = await ctx.client.post(url(ctx) + "/proposals/apply", json={"proposal_id": proposal["id"], "expected_revision": 3})
    assert response.status_code == 200 and response.json()["task"]["revision"] == 4
    async with ctx.sessions() as db:
        turn = await db.scalar(select(AssistantTurn))
        assert turn.proposal_state == "applied" and turn.snapshot_before is None
        assert turn.target_revision is None


@pytest.mark.asyncio
async def test_recovery_failure_keeps_preimage_and_explicit_recovery_never_adopts(conversation, monkeypatch):
    ctx = conversation
    proposal, before = await interrupted_adoption(ctx, monkeypatch)
    real_restore = journal._restore_snapshot
    def fail_restore(*_): raise OSError("SYNTHETIC_PRIVATE_IO_ERROR")
    monkeypatch.setattr(journal, "_restore_snapshot", fail_restore)
    async with ctx.sessions() as db:
        assert await journal.recover_applications(db) == ["failed"]
        await db.commit()
        turn = await db.scalar(select(AssistantTurn))
        assert turn.proposal_state == "applying" and turn.snapshot_before == before
        assert turn.safe_error == journal.RESTORE_FAILED
    body = {"proposal_id": proposal["id"], "expected_revision": 3}
    response = await ctx.client.post(url(ctx) + "/proposals/apply", json=body)
    assert response.status_code == 503 and "PRIVATE_IO" not in response.text
    pending = (await messages(ctx))[1]
    assert pending["proposal_state"] == "applying" and pending["proposal_notice"] == journal.RESTORE_FAILED
    monkeypatch.setattr(journal, "_restore_snapshot", real_restore)
    response = await ctx.client.post(url(ctx) + "/proposals/apply", json=body)
    assert response.status_code == 409 and "恢复原字段" in response.text
    assert load_snapshot_data(ctx.work) == before
    async with ctx.sessions() as db:
        assert (await db.get(ArchiveTask, ctx.task_id)).revision == 3
    # Another tab may have completed recovery since this tab displayed applying.
    # An explicit recovery click must still never become an adoption click.
    response = await ctx.client.post(url(ctx) + "/proposals/apply", json={**body, "recover_only": True})
    assert response.status_code == 409 and "没有采用" in response.text
    assert load_snapshot_data(ctx.work) == before
    # A distinct, explicit click may now adopt. Recovery did not do so.
    assert (await ctx.client.post(url(ctx) + "/proposals/apply", json=body)).status_code == 200


@pytest.mark.asyncio
async def test_second_commit_failure_restores_preimage_without_losing_journal(conversation, monkeypatch):
    ctx = conversation
    monkeypatch.setattr(selector, "select_tool", lambda *_: command())
    proposal = (await post(ctx, message="请把合同号改为虚构合同2")).json()["proposal"]
    before = load_snapshot_data(ctx.work)
    real_commit = AsyncSession.commit
    calls = []
    async def fail_second(db):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("synthetic commit failure after snapshot")
        return await real_commit(db)
    monkeypatch.setattr(AsyncSession, "commit", fail_second)
    response = await ctx.client.post(url(ctx) + "/proposals/apply", json={"proposal_id": proposal["id"], "expected_revision": 3})
    assert response.status_code == 503
    assert load_snapshot_data(ctx.work) == before
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        turn = await db.scalar(select(AssistantTurn))
        assert task.revision == 3 and turn.proposal_state == "pending" and turn.snapshot_before is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "source", "field", "org", "target"])
async def test_recovery_does_not_overwrite_a_different_authoritative_version(conversation, monkeypatch, change):
    ctx = conversation
    _, before = await interrupted_adoption(ctx, monkeypatch)
    written = load_snapshot_data(ctx.work)
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        turn = await db.scalar(select(AssistantTurn))
        if change == "revision": task.revision = 4
        if change == "source": task.source_version = "changed"
        if change == "field": task.fields = {**task.fields, "合同号": "另一明确值"}
        if change == "org": turn.org_id = "org-b"
        if change == "target": turn.target_revision = 8
        await db.commit()
        assert await journal.recover_applications(db) == ["failed"]
        await db.commit()
        await db.refresh(turn)
        assert turn.snapshot_before == before and turn.proposal_state == "applying"
    assert load_snapshot_data(ctx.work) == written


@pytest.mark.asyncio
async def test_committed_adoption_is_never_rolled_back(conversation, monkeypatch):
    ctx = conversation
    monkeypatch.setattr(selector, "select_tool", lambda *_: command())
    proposal = (await post(ctx, message="请把合同号改为虚构合同2")).json()["proposal"]
    before = load_snapshot_data(ctx.work)
    assert (await ctx.client.post(url(ctx) + "/proposals/apply", json={"proposal_id": proposal["id"], "expected_revision": 3})).status_code == 200
    after = load_snapshot_data(ctx.work)
    async with ctx.sessions() as db:
        turn = await db.scalar(select(AssistantTurn))
        # Even a stale journal copy cannot undo an atomically committed applied row.
        turn.snapshot_before, turn.target_revision = before, 4
        await db.commit()
        assert await journal.recover_application(db, turn.id) == "applied"
        assert await journal.recover_applications(db) == []
        assert (await db.get(ArchiveTask, ctx.task_id)).revision == 4
    assert load_snapshot_data(ctx.work) == after


def test_restore_path_rejects_invalid_db_identifiers(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "ORGS_DIR", tmp_path)
    for org, case, ident in (("../outside", "case", 1), ("org", "../outside", 1), ("org", "case", True)):
        with pytest.raises(ValueError): journal._snapshot_path(org, case, ident)


def test_restore_path_rejects_ancestor_reparse_points(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "ORGS_DIR", tmp_path)
    folder = tmp_path / "org" / "cases" / "case" / "tasks" / "1"
    folder.mkdir(parents=True)
    real_lstat = Path.lstat
    def flagged(path):
        value = real_lstat(path)
        return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400) if path == tmp_path / "org" else value
    monkeypatch.setattr(Path, "lstat", flagged)
    with pytest.raises(OSError): journal._snapshot_path("org", "case", 1)


@pytest.mark.asyncio
async def test_existing_chat_table_gains_nullable_journal_columns(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.database import migrate_assistant_columns
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "old-chat.sqlite"))
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE TABLE assistant_turns (id VARCHAR(32) PRIMARY KEY, user_message TEXT)")
            await conn.exec_driver_sql("INSERT INTO assistant_turns VALUES ('old', 'synthetic saved message')")
            await migrate_assistant_columns(conn)
            await migrate_assistant_columns(conn)
            row = (await conn.exec_driver_sql("SELECT user_message, snapshot_before, target_revision FROM assistant_turns")).first()
            assert row == ("synthetic saved message", None, None)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,suffix,body", [
    ("PATCH", "/fields", {"fields":{"合同号":"不得写入"}}),
    ("POST", "/regenerate-templates", {"fields":{}}),
    ("POST", "/refill", {"fields":{}}),
    ("PUT", "/preview-fields/档案卷宗", {"values":{"合同号":"不得写入"},"expected_revision":3}),
    ("PATCH", "/documents/synthetic-unit/classification", {"expected_revision":3,"doc_type":"evidence","catalog_seq":7,"reason":"虚构分类"}),
    ("POST", "/draft", {"expected_revision":3}),
    ("POST", "/assemble", {"confirmation":True,"confirmed_revision":3}),
    ("POST", "/resume", {}),
    ("POST", "generate", {}),
    ("GET", "/preview/档案卷宗", None),
    ("GET", "/docx/档案卷宗", None),
    ("POST", "/assistant", {"message":"不能读取混合快照","request_id":"blocked-new-request"}),
])
async def test_unresolved_recovery_blocks_snapshot_consumers_before_core_calls(conversation, monkeypatch, method, suffix, body):
    ctx = conversation
    _, before = await interrupted_adoption(ctx, monkeypatch)
    written = load_snapshot_data(ctx.work)
    def failed_restore(*_): raise OSError("synthetic unavailable storage")
    monkeypatch.setattr(journal, "_restore_snapshot", failed_restore)
    async with ctx.sessions() as db:
        assert await journal.recover_applications(db) == ["failed"]
        await db.commit()
    from app.routers import tasks
    def forbidden(*_, **__): pytest.fail("mixed snapshot must not reach core/model/renderer")
    for name in ("update_task_fields", "regenerate_templates", "preview_template_pdf", "get_template_docx_path", "run_archive", "run_assemble"):
        monkeypatch.setattr(tasks, name, forbidden)
    monkeypatch.setattr(selector, "load_context", forbidden)
    monkeypatch.setattr(selector, "select_tool", forbidden)
    path = "/api/cases/case-a/generate" if suffix == "generate" else f"/api/tasks/{ctx.task_id}" + suffix
    response = await ctx.client.request(method, path, **({"json":body} if body is not None else {}))
    assert response.status_code == 409 and response.json()["detail"] == journal.RECOVERY_REQUIRED
    assert load_snapshot_data(ctx.work) == written
    async with ctx.sessions() as db:
        turn = await db.scalar(select(AssistantTurn))
        assert turn.snapshot_before == before and turn.proposal_state == "applying"
        assert (await db.get(ArchiveTask, ctx.task_id)).revision == 3


@pytest.mark.asyncio
async def test_recovery_reopens_normal_editing_and_keeps_status_history_readable(conversation, monkeypatch):
    ctx = conversation
    proposal, before = await interrupted_adoption(ctx, monkeypatch)
    base = f"/api/tasks/{ctx.task_id}"
    assert (await ctx.client.get(base)).status_code == 200
    docs = await ctx.client.get(base + "/documents")
    assert docs.status_code == 200 and not docs.json()["editable"]
    fields = await ctx.client.get(base + "/preview-fields/档案卷宗")
    assert fields.status_code == 200 and not fields.json()["editable"]
    assert (await messages(ctx))[1]["proposal_state"] == "applying"
    recovery = await ctx.client.post(url(ctx) + "/proposals/apply", json={
        "proposal_id":proposal["id"],"expected_revision":3,"recover_only":True})
    assert recovery.status_code == 409 and load_snapshot_data(ctx.work) == before
    edited = await ctx.client.patch(base + "/fields", json={"fields":{"合同号":"恢复后明确人工值"}})
    assert edited.status_code == 200 and edited.json()["revision"] == 4
    assert load_snapshot_data(ctx.work)["fields"]["合同号"] == "恢复后明确人工值"


@pytest.mark.asyncio
async def test_case_guard_does_not_disable_intact_published_downloads(conversation, monkeypatch):
    import hashlib
    import copy
    from app.services.artifact_manifest import REQUIRED_ARTIFACT_KEYS
    from app.models import TaskStatus
    ctx = conversation
    # Establish the interrupted edit while this is still the current task.
    # Publishing a newer task first would now correctly make it historical.
    await interrupted_adoption(ctx, monkeypatch)
    # Synthetic published bytes: this test exercises the HTTP integrity/read
    # gate, not PDF rendering. No artifact validation is mocked.
    async with ctx.sessions() as db:
        source_task = await db.get(ArchiveTask, ctx.task_id)
        published = ArchiveTask(case_id="case-a",created_by="test-user",status=TaskStatus.done,
            revision=1,source_manifest=copy.deepcopy(source_task.source_manifest),
            source_version=source_task.source_version,fields=copy.deepcopy(source_task.fields))
        db.add(published); await db.flush()
        result = ctx.work / "synthetic-published"
        result.mkdir()
        entries = []
        for number, key in enumerate(sorted(REQUIRED_ARTIFACT_KEYS)):
            path = result / f"artifact-{number}.bin"
            data = ("synthetic intact " + key).encode()
            path.write_bytes(data)
            entries.append({"key":key,"path":str(path),"size":len(data),"sha256":hashlib.sha256(data).hexdigest()})
            if key == "archive_pdf": published.output_pdf = str(path)
        published.artifacts = {"valid":True,"result_dir":str(result),"revision":1,
                              "source_version":published.source_version,"artifacts":entries}
        await db.commit()
        published_id, archive_bytes = published.id, Path(published.output_pdf).read_bytes()
    response = await ctx.client.get(f"/api/tasks/{published_id}/download/archive")
    assert response.status_code == 200 and response.content == archive_bytes
    assert (await ctx.client.get(f"/api/tasks/{published_id}")).json()["has_archive"]
    async with ctx.sessions() as db:
        assert await journal.has_unresolved(db, case_id="case-a")
        assert not await journal.has_unresolved(db, case_id="different-case")
        await journal.require_consistent(db, task_id=published_id)
