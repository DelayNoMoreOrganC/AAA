"""Case screens use the same delivery and integrity semantics as task screens."""
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_automatic_draft import draft_context, create_review, make_draft
from tests.test_file_import_api import upload_context, upload


async def snapshots(ctx):
    listing = (await ctx.client.get("/api/cases")).json()
    detail = (await ctx.client.get("/api/cases/case-a")).json()
    task = (await ctx.client.get(f"/api/tasks/{ctx.task_id}")).json()
    summary = detail["last_task_summary"]
    assert next(row for row in listing if row["id"] == "case-a")["last_task_summary"] == summary
    assert summary == {key: task[key] for key in summary}
    assert detail["last_task_status"] == task["status"]
    return detail, task


@pytest.mark.asyncio
async def test_draft_delivered_visible_on_all_screens_and_saved_history(draft_context):
    ctx = draft_context
    await create_review(ctx)
    await make_draft(ctx)
    detail, task = await snapshots(ctx)
    assert task["phase"] == "draft_ready" and task["delivery_kind"] == "draft" and task["has_archive"]
    assert len(detail["done_tasks"]) == 1
    assert detail["done_tasks"][0]["delivery_kind"] == "draft"
    assert not task["formal_ready"]


@pytest.mark.asyncio
async def test_corrupt_delivery_not_advertised_as_ready_on_case_list(draft_context):
    ctx = draft_context
    await create_review(ctx)
    original = await make_draft(ctx)
    Path(original.output_pdf).write_bytes(b"synthetic corruption")
    detail, task = await snapshots(ctx)
    assert task["phase"] == "artifacts_invalid" and not task["has_archive"]
    assert task["can_resume"] and detail["done_tasks"] == []


@pytest.mark.asyncio
async def test_corrupt_historical_output_not_advertised_beside_newer_task(draft_context):
    from app.models import ArchiveTask, TaskStatus
    ctx = draft_context
    await create_review(ctx)
    original = await make_draft(ctx)
    Path(original.output_pdf).write_bytes(b"synthetic historical corruption")
    async with ctx.sessions() as db:
        # The damaged draft is historical: latest-task validation alone must
        # not leave its download advertised as intact.
        db.add(ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.awaiting_review,
                           phase="review", created_at=datetime.now(timezone.utc) + timedelta(seconds=5)))
        await db.commit()
    response = await ctx.client.get("/api/cases/case-a")
    assert response.status_code == 200
    assert response.json()["last_task_id"] != ctx.task_id
    assert response.json()["done_tasks"] == []
    async with ctx.sessions() as db:
        historical = await db.get(ArchiveTask, ctx.task_id)
        assert historical.phase == "artifacts_invalid"


@pytest.mark.asyncio
async def test_supplement_keeps_previous_draft_but_marks_current_material_changed(draft_context):
    ctx = draft_context
    await create_review(ctx)
    await make_draft(ctx)
    await upload(ctx, name="虚构补件.pdf")
    _, task = await snapshots(ctx)
    assert task["source_changed"] and task["has_archive"] and task["can_resume"]


@pytest.mark.asyncio
async def test_new_case_summary_is_null_and_other_user_cannot_read_it(upload_context):
    ctx = upload_context
    assert (await ctx.client.get("/api/cases/case-a")).json()["last_task_summary"] is None
    assert (await ctx.client.get("/api/cases", headers={"X-Test-User": "peer"})).json() == []
    assert (await ctx.client.get("/api/cases/case-a", headers={"X-Test-Org": "org-b"})).status_code == 404
