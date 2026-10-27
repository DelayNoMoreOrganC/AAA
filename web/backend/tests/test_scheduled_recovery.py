"""Startup recovery budget checks using only synthetic SQLite/files/counters."""
from copy import deepcopy

import pytest

from tests.test_file_import_api import upload_context
from app.models import ArchiveTask, TaskStatus
from app.services import archive_service, recovery, execution_profile
from app.services.task_manager import task_manager


@pytest.fixture
def recovery_calls(upload_context, monkeypatch):
    calls = []
    monkeypatch.setattr(recovery, "AsyncSessionLocal", upload_context.sessions)
    monkeypatch.setattr(execution_profile, "external_ai_allowed", lambda: True)
    # Production dispatch creates a coroutine then passes it to manager.start;
    # these stubs record creation, never execute a model or rendering operation.
    def archive(*args, **kwargs):
        calls.append(("analyze", args, kwargs))
        async def empty():
            pass
        return empty()
    def assemble(*args, **kwargs):
        calls.append(("draft" if kwargs.get("draft") else "assemble", args, kwargs))
        async def empty():
            pass
        return empty()
    monkeypatch.setattr(archive_service, "run_archive", archive)
    monkeypatch.setattr(archive_service, "run_assemble", assemble)
    monkeypatch.setattr(task_manager, "start", lambda _id, coroutine: coroutine.close())
    return calls


def cloud_profile():
    return {"version": 1, "processing_mode": "deepseek_cloud", "provider": "deepseek",
            "model": "deepseek-flash", "workflow": "document_two_stage", "cloud_consent": True,
            "authorized_by": "test-user", "authorized_source_version": "fictional-v1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [TaskStatus.pending, TaskStatus.running])
@pytest.mark.parametrize("checkpoint", ["", "analyzed"])
async def test_scheduled_analyze_is_failed_without_requeue_and_preserves_evidence(upload_context, recovery_calls, status, checkpoint):
    ctx = upload_context
    original = ctx.root / "fictional-original.pdf"
    snapshot = ctx.root / "fictional-analysis.json"
    original.write_bytes(b"synthetic source remains untouched")
    snapshot.write_bytes(b'{"synthetic":"analysis remains untouched"}')
    fields = {"委托人": "虚构主体", "_provenance": {"委托人": [{"source_path": str(original), "page": 1, "method": "human"}]}}
    manifest = [{"file_id": "fictional", "sha256": "a" * 64}]
    async with ctx.sessions() as db:
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=status,
            idempotency_key="real-auto-scheduled-20261025-abc-case48", requested_operation="analyze",
            checkpoint=checkpoint, fields=deepcopy(fields), manual_fields={"委托人": "虚构主体"},
            source_version="fictional-v1", source_manifest=deepcopy(manifest), revision=3, execution_profile=cloud_profile())
        db.add(task)
        await db.commit()
        task_id = task.id
    await recovery.recover_interrupted_tasks()
    await recovery.recover_interrupted_tasks()  # Repeated startup cannot unlock a charged attempt.
    assert not recovery_calls
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, task_id)
        assert task.status == TaskStatus.failed and "人工" in task.stage and "重复计费" in task.error
        assert task.requested_operation == "analyze" and task.checkpoint == checkpoint and task.revision == 3
        assert task.fields == fields and task.manual_fields == {"委托人": "虚构主体"}
        assert task.source_manifest == manifest and task.source_version == "fictional-v1"
    assert original.read_bytes() == b"synthetic source remains untouched"
    assert snapshot.read_bytes() == b'{"synthetic":"analysis remains untouched"}'


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["draft", "assemble"])
async def test_scheduled_local_output_recovery_remains_available_without_analysis(upload_context, recovery_calls, operation):
    ctx = upload_context
    async with ctx.sessions() as db:
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.running,
            idempotency_key="real-auto-scheduled-20261025-abc-case85", requested_operation=operation,
            source_manifest=[{"file_id": "fictional"}], checkpoint="analyzed", revision=2,
            source_version="fictional-v1", execution_profile=cloud_profile())
        db.add(task)
        await db.commit()
        task_id = task.id
    await recovery.recover_interrupted_tasks()
    assert len(recovery_calls) == 1 and recovery_calls[0][0] == operation
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, task_id)
        assert task.status == TaskStatus.pending and task.checkpoint == "analyzed" and task.revision == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, "ordinary-user-run", "real-auto-manual-acceptance-case48"])
async def test_ordinary_task_recovery_is_unchanged(upload_context, recovery_calls, key):
    ctx = upload_context
    async with ctx.sessions() as db:
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.running,
            idempotency_key=key, requested_operation="analyze", source_manifest=[{"file_id": "fictional"}])
        db.add(task)
        await db.commit()
    await recovery.recover_interrupted_tasks()
    assert len(recovery_calls) == 1 and recovery_calls[0][0] == "analyze"


@pytest.mark.asyncio
async def test_unknown_scheduled_operation_cannot_fall_back_to_model_analysis(upload_context, recovery_calls):
    async with upload_context.sessions() as db:
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.running,
            idempotency_key="real-auto-scheduled-20261025-abc-case48", requested_operation="unknown",
            source_manifest=[{"file_id": "fictional"}])
        db.add(task)
        await db.commit()
        task_id = task.id
    await recovery.recover_interrupted_tasks()
    assert not recovery_calls
    async with upload_context.sessions() as db:
        assert (await db.get(ArchiveTask, task_id)).status == TaskStatus.failed
