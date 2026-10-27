"""Synthetic markers test error boundaries, never model quality or real data."""
import asyncio
import copy
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from tests.test_file_import_api import upload_context, upload
from tests.test_task_workflow import fixture_analysis, wire_storage
from app import database
from app.models import ArchiveTask, CaseFile, TaskStatus
from app.services import archive_service
from app.services.analysis_snapshot import save_snapshot, task_work_dir
from app.services.safe_errors import ErrorCode, SafeTaskError, public_error, readiness_error
from app.services.task_manager import TaskManager, ProgressTracker, filtered_log_lines
from app.services.task_sources import build_source_manifest, source_version, fields_digest


MARKER = "虚构敏感标记-NO-LOG-2026-PRIVATE"


def raw_failure():
    try:
        raise ValueError("response body: " + MARKER)
    except ValueError as cause:
        raise RuntimeError("prompt and field: " + MARKER) from cause


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["analyze", "assemble", "browser", "cover_browser"])
async def test_failure_keeps_business_snapshot_but_not_raw_error(upload_context, monkeypatch, caplog, operation):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await upload(ctx)
    fields = {"委托人": MARKER, "_provenance": {"委托人": [{"quote": MARKER, "page": 1}]}}
    # This test injects a snapshot-write failure after checkpoint reuse. An old
    # normalization snapshot correctly triggers a fresh model readiness check.
    from case_outcome import STRICT_EVIDENCE_VERSION
    fields["_field_normalization_version"] = STRICT_EVIDENCE_VERSION
    async with ctx.sessions() as db:
        files = (await db.scalars(select(CaseFile))).all()
        manifest = build_source_manifest(files)
        version = source_version(manifest, "civil")
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.running,
                           revision=1, source_manifest=manifest, source_version=version,
                           fields=copy.deepcopy(fields), manual_fields={"委托人": MARKER}, issues=[],
                           confirmation={"revision":1, "source_version":version,
                                         "fields_digest":fields_digest(fields, "catalog"), "skipped":[]})
        db.add(task)
        await db.commit()
        task_id = task.id
    work = task_work_dir("org-a", "case-a", task_id)
    save_snapshot(work, fixture_analysis(files[0].abs_path, fields), base_name="synthetic",
                  metadata={"source_version": version})
    snapshot = Path(work) / "analysis_snapshot.json"
    original_snapshot = snapshot.read_bytes()
    async def context(*_):
        return SimpleNamespace(case_type="civil", stage=""), files, {"privacy":{"mode":"local"}}
    async def org(*_):
        return "虚构测试律所"
    monkeypatch.setattr(archive_service, "_load_case_context", context)
    monkeypatch.setattr(archive_service, "_load_org_name", org)
    monkeypatch.setattr(archive_service, "get_settings", lambda: SimpleNamespace(preview_only=True))
    manager = TaskManager()
    monkeypatch.setattr(archive_service, "task_manager", manager)
    tracker = manager.get_tracker(task_id)
    queue = await tracker.subscribe()
    if operation == "analyze":
        monkeypatch.setattr(archive_service, "save_snapshot", lambda *a, **kw: raw_failure())
        action, expected = archive_service.run_archive, ErrorCode.ANALYSIS_FAILED
    elif operation == "assemble":
        from app.services import system_docx_service
        monkeypatch.setattr(system_docx_service, "generate_system_docx", lambda *a, **kw: raw_failure())
        action, expected = archive_service.run_assemble, ErrorCode.ASSEMBLY_FAILED
    else:
        from app.services import system_docx_service, output_derivation
        from app.services.browser_pdf_service import BrowserPdfError
        from app.services.analysis_snapshot import SYSTEM_TEMPLATE_NAMES
        def browser_failure(*a, **kw):
            # A typed browser exception still cannot authorize arbitrary text.
            try:
                raise ValueError(MARKER)
            except ValueError as cause:
                raise BrowserPdfError("[BROWSER_START_FAILED] " + MARKER) from cause
        templates = {name:str(Path(work) / (name + ".pdf")) for name in SYSTEM_TEMPLATE_NAMES}
        monkeypatch.setattr(system_docx_service, "generate_system_docx", lambda *a, **kw: templates)
        if operation == "browser":
            monkeypatch.setattr(archive_service, "render_system_form_pdfs", browser_failure)
        else:
            monkeypatch.setattr(archive_service, "render_system_form_pdfs", lambda *a, **kw: templates)
            monkeypatch.setattr(archive_service, "archive_pipeline", lambda: SimpleNamespace(
                assemble_archive=lambda *a, **kw: SimpleNamespace(success=True, page_count=1,
                    pagination={"mode":"body","body_start":1})))
            monkeypatch.setattr(output_derivation, "finalize_cover_count", browser_failure)
        action, expected = archive_service.run_assemble, ErrorCode.BROWSER_RENDER_FAILED
    with caplog.at_level(logging.ERROR):
        await action(task_id, "case-a", "org-a", "test-user")
    await asyncio.sleep(0)
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    async with ctx.sessions() as db:
        final = await db.get(ArchiveTask, task_id)
        assert final.status == TaskStatus.failed
        assert final.error == public_error(expected)
        assert final.fields == fields and final.manual_fields == {"委托人": MARKER}
        assert final.output_pdf == "" and final.artifacts is None
        assert MARKER not in final.log_text
    if operation == "cover_browser":
        # Rendering legitimately updates template paths, never confirmed facts.
        saved = json.loads(snapshot.read_text(encoding="utf-8"))
        assert saved["fields"] == fields
        assert saved["workflow"]["source_version"] == version
    else:
        assert snapshot.read_bytes() == original_snapshot
    assert any(event == {"type":"error", "error":public_error(expected)} for event in events)
    assert MARKER not in json.dumps(events, ensure_ascii=False) + caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_failure_to_persist_failure_does_not_escape_raw_chain(monkeypatch, caplog):
    manager = TaskManager()
    monkeypatch.setattr(archive_service, "task_manager", manager)
    async def fail(*a, **kw):
        raw_failure()
    monkeypatch.setattr(archive_service, "_load_case_context", fail)
    monkeypatch.setattr(archive_service, "_persist_task", fail)
    queue = await manager.get_tracker(123).subscribe()
    with caplog.at_level(logging.ERROR):
        await archive_service.run_archive(123, "synthetic", "synthetic", "synthetic")
    event = await asyncio.wait_for(queue.get(), 1)
    assert event["error"] == public_error(ErrorCode.TASK_FAILURE_PERSIST_FAILED)
    assert MARKER not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_manager_storage_and_unhandled_job_errors_are_fixed(monkeypatch, caplog):
    class BrokenSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, *args):
            raw_failure()
    monkeypatch.setattr(database, "AsyncSessionLocal", BrokenSession)
    manager = TaskManager()
    queue = await manager.get_tracker(55).subscribe()
    async def failed_job():
        await asyncio.sleep(.01)
        raw_failure()
    with caplog.at_level(logging.ERROR):
        manager.start(55, failed_job())
        await manager._tasks[55]  # Must not leave an unhandled task exception.
    event = await asyncio.wait_for(queue.get(), 1)
    assert event["error"] == public_error(ErrorCode.TASK_FAILED)
    for code in (ErrorCode.TASK_LOG_LOAD_FAILED, ErrorCode.TASK_LOG_PERSIST_FAILED,
                 ErrorCode.TASK_FINAL_PERSIST_FAILED, ErrorCode.TASK_FAILURE_PERSIST_FAILED):
        assert code.value in caplog.text
    assert MARKER not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_progress_callback_and_replay_accept_only_whole_safe_events():
    tracker = ProgressTracker(7)
    queue = await tracker.subscribe()
    allowed = "归档助理：来源核对完成，已处理 3 / 9 个页面片段"
    rejected = [MARKER, "材料名-" + MARKER + ".pdf", "[WARN] 文书定位失败: " + MARKER,
                allowed + MARKER, allowed + "\n" + MARKER,
                "归档助理：正在阅读 " + MARKER + " 个页面片段", RuntimeError(MARKER)]
    for line in rejected:
        tracker.log(line)
    tracker.log("  " + allowed)
    tracker.fail(RuntimeError(MARKER))
    await asyncio.sleep(0)
    assert tracker.log_lines == [allowed]
    assert (await queue.get()) == {"type":"log", "text":allowed}
    assert (await queue.get()) == {"type":"error", "error":public_error(ErrorCode.TASK_FAILED)}
    assert queue.empty()
    assert filtered_log_lines([*rejected, allowed]) == [allowed]


def test_raw_error_cannot_spoof_a_safe_message_or_controlled_reasons():
    error = SafeTaskError(ErrorCode.SOURCE_CHANGED)
    error.args = (MARKER,)
    assert MARKER not in public_error(error)
    assert public_error(RuntimeError(public_error(error) + MARKER)) == public_error(ErrorCode.TASK_FAILED)
    ready = readiness_error({"issues":["工作站缺少本地 OCR 组件，请由部署人员安装",
                                       "本地模型服务未就绪，请由管理员启动模型服务", MARKER]})
    message = public_error(ready)
    assert ErrorCode.LOCAL_OCR_UNAVAILABLE.value in message
    assert ErrorCode.LOCAL_MODEL_UNAVAILABLE.value in message
    assert MARKER not in message


@pytest.mark.asyncio
async def test_database_exception_hides_bound_values():
    assert database.engine.sync_engine.hide_parameters is True
    async with database.engine.begin() as connection:
        await connection.execute(text("CREATE TABLE privacy_binding_fixture (value TEXT UNIQUE)"))
        await connection.execute(text("INSERT INTO privacy_binding_fixture VALUES (:value)"), {"value": MARKER})
        with pytest.raises(IntegrityError) as error:
            await connection.execute(text("INSERT INTO privacy_binding_fixture VALUES (:value)"), {"value": MARKER})
        assert MARKER not in str(error.value)
        assert "parameters hidden" in str(error.value)
        await connection.execute(text("DROP TABLE privacy_binding_fixture"))
