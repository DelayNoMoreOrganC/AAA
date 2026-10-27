"""Pending inputs cannot silently disappear into a new archive or confirmation.

Real ASGI routes and isolated SQLite; model/render starts are captured, never run.
"""
import hashlib

import pytest
from sqlalchemy import select

from app.models import ArchiveTask, CaseFile, Role, TaskStatus, User
from app.routers import tasks
from app.services.task_sources import build_source_manifest, source_version
from tests.test_file_import_api import upload_context, upload, pdf_bytes
from tests.test_task_workflow import capture_start, wire_storage


async def register(ctx, *, headers=None):
    payload = pdf_bytes("Synthetic pending supplement")
    response = await ctx.client.put("/api/cases/case-a/upload-intents/pending-supplement", headers=headers,
        json={"filename": "私有虚构补件.pdf", "file_size": len(payload),
              "sha256": hashlib.sha256(payload).hexdigest(), "doc_type": "default"})
    assert response.status_code == 200, response.text
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["generate", "resume", "draft", "assemble"])
async def test_pending_material_blocks_work_before_paid_or_render_start_and_preserves_facts(
        upload_context, monkeypatch, capture_start, operation):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    assert (await upload(ctx)).status_code == 200
    async with ctx.sessions() as db:
        files = list((await db.scalars(select(CaseFile))).all())
        manifest = build_source_manifest(files)
        task = ArchiveTask(case_id="case-a", created_by="test-user", revision=4,
            status=TaskStatus.failed if operation == "resume" else TaskStatus.awaiting_review,
            source_manifest=manifest, source_version=source_version(manifest, "civil"),
            fields={"委托人": "已核对虚构甲"}, manual_fields={"委托人": "已核对虚构甲"},
            confirmation={"revision": 4}, catalog_status=[], checkpoint="analyzed")
        db.add(task)
        await db.commit()
        task_id, previous_status = task.id, task.status
    await register(ctx)
    path = "/api/cases/case-a/generate" if operation == "generate" else f"/api/tasks/{task_id}/{operation}"
    body = {"expected_revision": 4} if operation == "draft" else {
        "confirmation": True, "confirmed_revision": 4, "skipped": []} if operation == "assemble" else {}
    result = await ctx.client.post(path, json=body)
    assert result.status_code == 409, result.text
    assert "导入" in result.json()["detail"]
    assert "私有虚构补件" not in result.text
    assert capture_start == []
    async with ctx.sessions() as db:
        saved = await db.get(ArchiveTask, task_id)
        assert saved.status == previous_status
        assert saved.manual_fields == saved.fields == {"委托人": "已核对虚构甲"}
        assert saved.revision == 4 and saved.confirmation == {"revision": 4}
        assert saved.checkpoint == "analyzed"
        assert len(list((await db.scalars(select(ArchiveTask))).all())) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("resolve", ["cancel", "complete"])
async def test_resolving_pending_material_allows_one_start_and_idempotent_replay(
        upload_context, monkeypatch, capture_start, resolve):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    assert (await upload(ctx)).status_code == 200
    payload = await register(ctx)
    body = {"idempotency_key": "synthetic-start-once"}
    assert (await ctx.client.post("/api/cases/case-a/generate", json=body)).status_code == 409
    if resolve == "cancel":
        cancelled = await ctx.client.delete("/api/cases/case-a/upload-intents/pending-supplement")
        assert cancelled.status_code in (200, 204), cancelled.text
    else:
        completed = await ctx.client.post("/api/cases/case-a/files",
            headers={"Idempotency-Key": "pending-supplement"}, data={"doc_type": "default"},
            files={"file": ("私有虚构补件.pdf", payload)})
        assert completed.status_code == 200, completed.text
    first = await ctx.client.post("/api/cases/case-a/generate", json=body)
    second = await ctx.client.post("/api/cases/case-a/generate", json=body)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert capture_start == [first.json()["id"]]
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, first.json()["id"])
        assert len(task.source_manifest) == (1 if resolve == "cancel" else 2)


@pytest.mark.asyncio
async def test_another_authorized_users_pending_queue_blocks_without_disclosing_names(
        upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    assert (await upload(ctx)).status_code == 200
    async with ctx.sessions() as db:
        db.add(User(id="other-admin", org_id="org-a", username="synthetic-other-admin",
                    hashed_password="unused-synthetic", role=Role.admin))
        await db.commit()
    await register(ctx, headers={"X-Test-User": "other-admin", "X-Test-Role": "admin"})
    own_queue = await ctx.client.get("/api/cases/case-a/upload-intents")
    assert own_queue.status_code == 200
    assert "私有虚构补件" not in own_queue.text
    result = await ctx.client.post("/api/cases/case-a/generate", json={})
    assert result.status_code == 409 and "发起" in result.json()["detail"]
    assert "私有虚构补件" not in result.text
    assert capture_start == []


@pytest.mark.asyncio
async def test_foreign_org_cannot_probe_pending_queue_through_start(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await register(ctx)
    result = await ctx.client.post("/api/cases/case-a/generate", json={}, headers={"X-Test-Org": "org-b"})
    assert result.status_code == 404
    assert "导入" not in result.text and capture_start == []


@pytest.mark.asyncio
async def test_registration_during_preflight_prevents_late_start_commit(upload_context, monkeypatch, capture_start):
    """Separate session stands in for another worker, without an OS-process claim."""
    from app.services import upload_intents
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    assert (await upload(ctx)).status_code == 200
    payload = pdf_bytes("Synthetic second worker input")

    async def preflight(*_args, **_kwargs):
        # The first no-pending check already succeeded. A second DB writer
        # registers input before the task's final write-lock check.
        async with ctx.sessions() as db:
            await upload_intents.register(db, upload_intents.Scope("org-a", "test-user", "case-a"),
                "second-worker", {"filename": "虚构并发补件.pdf", "file_size": len(payload),
                                  "sha256": hashlib.sha256(payload).hexdigest(), "doc_type": "default"},
                ctx.root / "org-a" / "cases" / "case-a")
        return {"ready": True, "issues": []}

    monkeypatch.setattr(tasks, "check_readiness", preflight)
    response = await ctx.client.post("/api/cases/case-a/generate", json={})
    assert response.status_code == 409 and "导入" in response.json()["detail"]
    assert capture_start == []
    async with ctx.sessions() as db:
        assert list(await db.scalars(select(ArchiveTask))) == []
    queue = await ctx.client.get("/api/cases/case-a/upload-intents")
    assert len(queue.json()["items"]) == 1
    assert queue.json()["items"][0]["status"] == "pending"
