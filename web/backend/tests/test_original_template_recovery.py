"""Editable layout failures remain actionable, private and durable."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_file_import_api import upload_context
from app.database import migrate_task_columns
from app.models import ArchiveTask, TaskStatus
from app.services import archive_service as archive, original_template_service as original
from app.services.safe_errors import ErrorCode, original_template_target, task_recovery_target


@pytest.mark.parametrize("name,fields,key", [
    ("立案审批表", {"案情简介": "虚构材料内容" * 200}, "案情简介"),
    ("送达材料清单", {"法院文件清单": "\n".join(["虚构裁定书"] * 19)}, "法院文件清单"),
])
def test_real_original_form_capacity_error_has_exact_edit_target(tmp_path, name, fields, key):
    with pytest.raises(original.OriginalTemplateError) as caught:
        original.fill_original_docx(name, fields, "虚构律所", tmp_path / "out.docx")
    assert original_template_target(caught.value) == {"template_name": name, "field": key}
    assert "虚构材料内容" not in str(caught.value)


def test_unknown_errors_and_targets_never_leak_text_or_invent_field():
    marker = "FICTIONAL_PRIVATE_PATH"
    assert original_template_target(RuntimeError(marker)) is None
    error = original.OriginalTemplateError("overflow", ["案情简介"])
    error.template_name = marker
    assert original_template_target(error) is None
    error.template_name = "送达材料清单"
    error.fields = [marker, "案情简介"]  # valid elsewhere, not in this form
    assert original_template_target(error) == {"template_name": "送达材料清单", "field": None}


@pytest.mark.parametrize("row", [6, 7, 9])
def test_custom_opinion_overflow_does_not_misidentify_case_summary(tmp_path, row):
    fields = {"案情简介": "虚构简短说明", "_preview_custom_values": {
        "立案审批表": {f"p0-b0-r{row}-c0": "虚构意见" * 60}}}
    with pytest.raises(original.OriginalTemplateError) as caught:
        original.fill_original_docx("立案审批表", fields, "虚构律所", tmp_path / "out.docx")
    assert caught.value.fields == []
    assert original_template_target(caught.value) == {"template_name":"立案审批表", "field":None}


def test_native_page_failure_retains_form_without_guessing_field(tmp_path, monkeypatch):
    def fail_convert(*args, **kwargs):
        raise original.OriginalTemplateError("page_count")
    monkeypatch.setattr(original, "convert_docx_to_pdf", fail_convert)
    with pytest.raises(original.OriginalTemplateError) as caught:
        original.render_original_pdf("结案报告表", {}, "虚构律所", tmp_path / "out.pdf")
    assert original_template_target(caught.value) == {"template_name":"结案报告表", "field":None}


@pytest.mark.asyncio
async def test_overflow_state_survives_fresh_sessions_and_clears_after_saved_edit(upload_context, monkeypatch):
    ctx = upload_context
    monkeypatch.setattr(archive, "AsyncSessionLocal", ctx.sessions)
    async with ctx.sessions() as db:
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.running,
                           manual_fields={"委托人": "虚构已确认主体"}, fields={"委托人": "虚构已确认主体"})
        db.add(task)
        await db.commit()
        task_id = task.id
    error = original.OriginalTemplateError("overflow", ["法院文件清单"])
    error.template_name = "送达材料清单"
    tracker = SimpleNamespace(fail=lambda value: None)
    await archive._fail_task(task_id, tracker, error, ErrorCode.TASK_FAILED)
    response = await ctx.client.get(f"/api/tasks/{task_id}")
    assert response.status_code == 200
    value = response.json()
    target = {"template_name": "送达材料清单", "field": "法院文件清单"}
    assert value["status"] == "awaiting_review" and value["phase"] == "needs_input"
    assert "GD_ORIGINAL_TEMPLATE_OVERFLOW" in value["error"] and value["recovery_target"] == target
    assert not value["has_archive"]
    for url in ("/api/cases", "/api/cases/case-a"):
        result = (await ctx.client.get(url)).json()
        summary = result[0]["last_task_summary"] if isinstance(result, list) else result["last_task_summary"]
        assert summary["recovery_target"] == target and summary["error"] == value["error"]
    assert (await ctx.client.get(f"/api/tasks/{task_id}", headers={"X-Test-Org":"org-b"})).status_code == 404
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, task_id)
        previous_revision = task.revision
        archive.invalidate_output(task)
        await db.commit()
    result = (await ctx.client.get(f"/api/tasks/{task_id}")).json()
    assert result["error"] == "" and result["recovery_target"] is None
    assert result["revision"] == previous_revision + 1
    assert result["fields"]["委托人"] == "虚构已确认主体"
    async with ctx.sessions() as db:
        saved = await db.get(ArchiveTask, task_id)
        assert saved.manual_fields == {"委托人": "虚构已确认主体"}


@pytest.mark.parametrize("status,phase,error", [
    (TaskStatus.running, "needs_input", "old"),
    (TaskStatus.awaiting_review, "ready_to_finalize", "old"),
    (TaskStatus.awaiting_review, "needs_input", ""),
])
def test_old_target_is_hidden_after_status_changes(status, phase, error):
    task = SimpleNamespace(status=status, phase=phase, error=error,
                           recovery_target={"template_name":"送达材料清单", "field":"法院文件清单"})
    assert task_recovery_target(task) is None


@pytest.mark.asyncio
async def test_additive_migration_preserves_old_task_and_is_repeatable(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + (tmp_path / "old.db").as_posix())
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("CREATE TABLE tasks(id INTEGER PRIMARY KEY, case_id TEXT, fields JSON)")
            await connection.exec_driver_sql("INSERT INTO tasks VALUES (7, 'fictional-case', ?)", (json.dumps({"original":"kept"}),))
            await migrate_task_columns(connection)
            await migrate_task_columns(connection)
            row = (await connection.exec_driver_sql("SELECT id, case_id, fields, recovery_target FROM tasks")).one()
            assert tuple(row) == (7, "fictional-case", json.dumps({"original":"kept"}), None)
    finally:
        await engine.dispose()
