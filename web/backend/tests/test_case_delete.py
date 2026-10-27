"""Deletion of synthetic case copies; no real cases, models or services."""
import asyncio
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_file_import_api import upload_context, upload
from app.models import ArchiveTask, Case, CaseFile, TaskStatus
from app.routers import cases
from app.services import case_deletion
from app.services.task_manager import task_manager


async def retained_case(ctx, status=TaskStatus.done):
    assert (await upload(ctx)).status_code == 200
    case_dir = ctx.root / "org-a" / "cases" / "case-a"
    work = case_dir / "tasks" / "test" / "r1"
    work.mkdir(parents=True)
    (work / "synthetic-output.pdf").write_bytes(b"synthetic result")
    (work / "analysis_snapshot.json").write_text('{"synthetic":true}', encoding="utf-8")
    external = ctx.root / "outside-saved-result"
    external.mkdir()
    (external / "saved.pdf").write_bytes(b"external saved copy")
    original = ctx.root / "original-source.pdf"
    original.write_bytes(b"original outside workstation case")
    async with ctx.sessions() as db:
        await db.execute(text("PRAGMA foreign_keys=ON"))
        task = ArchiveTask(case_id="case-a", status=status, created_by="test-user",
            output_pdf=str(external / "saved.pdf"), output_docx_dir=str(external), fields={"_saved_to":str(external)})
        db.add(task)
        await db.commit()
        task_id = task.id
    return case_dir, external, original, task_id


async def assert_records(ctx, present):
    async with ctx.sessions() as db:
        assert (await db.get(Case, "case-a") is not None) is present
        assert bool((await db.scalars(select(CaseFile))).all()) is present
        assert bool((await db.scalars(select(ArchiveTask))).all()) is present


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"X-Test-User":"another-admin", "X-Test-Role":"admin"}])
async def test_creator_and_own_org_admin_delete_complete_case_but_keep_external_copies(upload_context, headers):
    ctx = upload_context
    case_dir, external, original, _ = await retained_case(ctx)
    response = await ctx.client.delete("/api/cases/case-a", headers=headers)
    assert response.status_code == 204, response.text
    await assert_records(ctx, False)
    assert not case_dir.exists()
    assert (external / "saved.pdf").read_bytes() == b"external saved copy"
    assert original.read_bytes() == b"original outside workstation case"
    assert not (ctx.root / "org-a" / ".case-deletions" / "case-a").exists()
    assert (await ctx.client.get("/api/cases/case-a")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{"X-Test-User":"peer"}, {"X-Test-Org":"org-b"}, {"X-Test-Org":"org-b", "X-Test-Role":"admin"}])
async def test_other_users_or_orgs_cannot_delete(upload_context, headers):
    ctx = upload_context
    case_dir, _, _, _ = await retained_case(ctx)
    assert (await ctx.client.delete("/api/cases/case-a", headers=headers)).status_code == 404
    await assert_records(ctx, True)
    assert case_dir.is_dir()


@pytest.mark.asyncio
async def test_legacy_ownerless_case_is_admin_only(upload_context):
    ctx = upload_context
    await retained_case(ctx)
    async with ctx.sessions() as db:
        case = await db.get(Case, "case-a")
        case.created_by = None
        await db.commit()
    assert (await ctx.client.delete("/api/cases/case-a")).status_code == 404
    assert (await ctx.client.delete("/api/cases/case-a", headers={"X-Test-Role":"admin"})).status_code == 204


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [TaskStatus.pending, TaskStatus.running])
async def test_queued_running_or_recovering_task_blocks_deletion(upload_context, status):
    ctx = upload_context
    case_dir, _, _, _ = await retained_case(ctx, status)
    response = await ctx.client.delete("/api/cases/case-a")
    assert response.status_code == 409 and "任务" in response.text
    await assert_records(ctx, True)
    assert case_dir.exists()


@pytest.mark.asyncio
async def test_live_worker_and_case_mutation_lock_block_deletion(upload_context, monkeypatch):
    ctx = upload_context
    case_dir, _, _, task_id = await retained_case(ctx)
    with monkeypatch.context() as patch:
        patch.setattr(task_manager, "is_running", lambda ident: ident == task_id)
        assert (await ctx.client.delete("/api/cases/case-a")).status_code == 409
    async with task_manager.case_lock("case-a"):
        assert (await ctx.client.delete("/api/cases/case-a")).status_code == 409
    await assert_records(ctx, True)
    assert case_dir.exists()


@pytest.mark.asyncio
async def test_upload_holds_same_case_lock_while_normalizing(upload_context, monkeypatch):
    import threading
    ctx = upload_context
    started, release = threading.Event(), threading.Event()
    normalize = cases.normalize_import
    def waiting(*args):
        started.set()
        assert release.wait(5)
        return normalize(*args)
    monkeypatch.setattr(cases, "normalize_import", waiting)
    request = asyncio.create_task(upload(ctx))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        assert (await ctx.client.delete("/api/cases/case-a")).status_code == 409
    finally:
        release.set()
    assert (await request).status_code == 200
    assert (await ctx.client.delete("/api/cases/case-a")).status_code == 204


@pytest.mark.asyncio
async def test_database_failure_restores_complete_directory_and_records(upload_context, monkeypatch):
    ctx = upload_context
    case_dir, _, _, _ = await retained_case(ctx)
    before = {p.relative_to(case_dir):p.read_bytes() for p in case_dir.rglob("*") if p.is_file()}
    async def failed_commit(self):
        raise RuntimeError("synthetic-private-database-error")
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", failed_commit)
        response = await ctx.client.delete("/api/cases/case-a")
    assert response.status_code == 503 and "synthetic-private" not in response.text
    await assert_records(ctx, True)
    after = {p.relative_to(case_dir):p.read_bytes() for p in case_dir.rglob("*") if p.is_file()}
    assert after == before
    assert (await ctx.client.delete("/api/cases/case-a")).status_code == 204


@pytest.mark.asyncio
async def test_stage_os_failure_keeps_case_and_does_not_echo_private_error(upload_context, monkeypatch):
    ctx = upload_context
    case_dir, _, _, _ = await retained_case(ctx)
    def denied(*args): raise PermissionError("synthetic-private-file-path")
    with monkeypatch.context() as patch:
        patch.setattr(case_deletion.os, "replace", denied)
        response = await ctx.client.delete("/api/cases/case-a")
    assert response.status_code == 409 and "synthetic-private" not in response.text
    await assert_records(ctx, True)
    assert (case_dir / "tasks" / "test" / "r1" / "analysis_snapshot.json").is_file()


@pytest.mark.asyncio
async def test_partial_cleanup_is_explicit_202_and_only_owner_or_admin_may_retry(upload_context, monkeypatch):
    ctx = upload_context
    case_dir, external, original, _ = await retained_case(ctx)
    def partial(path):
        (path / "tasks" / "test" / "r1" / "synthetic-output.pdf").unlink()
        raise PermissionError("synthetic-cleanup-private")
    with monkeypatch.context() as patch:
        patch.setattr(case_deletion.shutil, "rmtree", partial)
        response = await ctx.client.delete("/api/cases/case-a")
    assert response.status_code == 202
    assert response.json()["deleted"] and response.json()["cleanup_pending"]
    assert "synthetic-cleanup" not in response.text
    await assert_records(ctx, False)
    stage = ctx.root / "org-a" / ".case-deletions" / "case-a"
    assert stage.is_dir() and not case_dir.exists()
    for headers in ({"X-Test-User":"peer"}, {"X-Test-Org":"org-b", "X-Test-Role":"admin"}):
        assert (await ctx.client.delete("/api/cases/case-a", headers=headers)).status_code == 404
    assert (await ctx.client.delete("/api/cases/case-a")).status_code == 204
    assert not stage.exists()
    assert (external / "saved.pdf").is_file() and original.is_file()


@pytest.mark.asyncio
async def test_interrupted_staging_can_be_retried_without_losing_records(upload_context):
    ctx = upload_context
    case_dir, _, _, _ = await retained_case(ctx)
    checked_case, stage = case_deletion.checked_paths(ctx.root, "org-a", "case-a")
    case_deletion.stage_case(checked_case, stage, org_id="org-a", case_id="case-a", created_by="test-user")
    assert not case_dir.exists()
    await assert_records(ctx, True)
    assert (await ctx.client.delete("/api/cases/case-a")).status_code == 204
    await assert_records(ctx, False)


@pytest.mark.asyncio
async def test_nested_windows_reparse_point_is_rejected_without_following(upload_context, monkeypatch):
    ctx = upload_context
    case_dir, external, _, _ = await retained_case(ctx)
    link = case_dir / "nested-link"
    link.mkdir()
    real_lstat = Path.lstat
    def marked(path):
        if path == link:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return real_lstat(path)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", marked)
        response = await ctx.client.delete("/api/cases/case-a")
    assert response.status_code == 409
    await assert_records(ctx, True)
    assert case_dir.is_dir() and (external / "saved.pdf").is_file()


@pytest.mark.asyncio
async def test_output_directory_overlap_blocks_deletion(upload_context):
    ctx = upload_context
    case_dir, _, _, task_id = await retained_case(ctx)
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, task_id)
        task.fields = {"_saved_to":str(case_dir / "user-saved-copy")}
        await db.commit()
    assert (await ctx.client.delete("/api/cases/case-a")).status_code == 409
    await assert_records(ctx, True)
