"""Synthetic content must not become HTTP/WS diagnostics or runtime logs."""
import json
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from starlette.websockets import WebSocketState

from tests.test_file_import_api import upload_context
from app.routers import tasks, workstation
from app.models import ArchiveTask, TaskStatus


MARKER = "FICTIONAL_PRIVATE_TEXT_8c19_客户原文"


@pytest.mark.asyncio
async def test_unexpected_http_failure_does_not_reach_server_traceback(upload_context, monkeypatch, caplog):
    async def broken(*args):
        try:
            raise ValueError(MARKER)
        except ValueError as cause:
            raise RuntimeError("outer " + MARKER) from cause
    monkeypatch.setattr(tasks, "_load_task_for_user", broken)
    result = await upload_context.client.get("/api/tasks/1")
    assert result.status_code == 500
    assert "GD_HTTP_FAILED" in result.text
    assert MARKER not in result.text + caplog.text
    assert result.headers["cache-control"] == "no-store"
    assert "content-security-policy" in result.headers
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_invalid_request_does_not_echo_submitted_material(upload_context):
    response = await upload_context.client.post("/api/cases", json={"title": MARKER, "case_type": MARKER})
    assert response.status_code == 422
    assert "GD_INPUT_INVALID" in response.text
    assert MARKER not in response.text


@pytest.mark.asyncio
async def test_preview_failure_keeps_fixed_actionable_hint(upload_context, monkeypatch):
    async with upload_context.sessions() as db:
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.awaiting_review)
        db.add(task)
        await db.commit()
        task_id = task.id
    calls = []
    async def fail(*args):
        calls.append(True)
        raise RuntimeError(MARKER)
    monkeypatch.setattr(tasks, "preview_template_pdf", fail)
    response = await upload_context.client.get(f"/api/tasks/{task_id}/preview/立案审批表")
    assert calls == [True]
    assert response.status_code == 500
    assert "GD_PREVIEW_FAILED" in response.text
    assert MARKER not in response.text


@pytest.mark.asyncio
async def test_original_overflow_lists_only_known_field_names(upload_context, monkeypatch):
    from app.services.original_template_service import OriginalTemplateError
    async with upload_context.sessions() as db:
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.awaiting_review)
        db.add(task)
        await db.commit()
        task_id = task.id
    calls = []
    async def fail(*args):
        calls.append(True)
        raise OriginalTemplateError("overflow", ["案情简介", MARKER])
    monkeypatch.setattr(tasks, "preview_template_pdf", fail)
    response = await upload_context.client.get(f"/api/tasks/{task_id}/preview/立案审批表")
    assert calls == [True]
    assert response.status_code == 422
    assert "GD_ORIGINAL_TEMPLATE_OVERFLOW" in response.text and "案情简介" in response.text
    assert MARKER not in response.text


@pytest.mark.asyncio
async def test_output_directory_os_error_does_not_echo_path(monkeypatch):
    def fail(*args):
        raise OSError(MARKER)
    monkeypatch.setattr(workstation, "set_output_directory", fail)
    with pytest.raises(HTTPException) as caught:
        await workstation.update_output(workstation.OutputSettings(output_directory="C:/fictional"), user=object())
    assert "GD_OUTPUT_DIRECTORY_INVALID" in caught.value.detail
    assert MARKER not in caught.value.detail
    assert caught.value.__suppress_context__


@pytest.mark.asyncio
async def test_unexpected_ws_failure_does_not_reach_server_traceback(monkeypatch, caplog):
    async def broken(*args):
        raise RuntimeError(MARKER)
    monkeypatch.setattr(tasks, "_task_ws", broken)
    class Socket:
        application_state = WebSocketState.CONNECTED
        sent = None
        async def send_json(self, value): self.sent = value
        async def close(self, code=1000): self.close_code = code
    socket = Socket()
    await tasks.task_ws(socket, 1)
    assert socket.close_code == 1011
    assert "GD_PROGRESS_STREAM_FAILED" in json.dumps(socket.sent)
    assert MARKER not in json.dumps(socket.sent) + caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect_on_replay", [False, True])
async def test_ws_historical_log_filters_material_but_keeps_progress(monkeypatch, disconnect_on_replay):
    import asyncio
    safe_line = "从已保存分析检查点恢复，无需重复识别材料"
    actor = SimpleNamespace(is_active=True, org_id="fictional")
    task = SimpleNamespace(log_text=MARKER + "\n" + safe_line, progress=60, stage="待核对")
    class DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args): return actor
    monkeypatch.setattr(tasks, "AsyncSessionLocal", DB)
    monkeypatch.setattr(tasks, "decode_token", lambda _: {"type": "access", "org": "fictional", "sub": "fictional"})
    async def owned(*args): return task
    monkeypatch.setattr(tasks, "_load_task_for_user", owned)
    class Tracker:
        log_lines = []
        unsubscribed = False
        async def subscribe(self):
            queue = asyncio.Queue()
            queue.put_nowait({"type": "done"})
            return queue
        async def unsubscribe(self, _): self.unsubscribed = True
    tracker = Tracker()
    monkeypatch.setattr(tasks.task_manager, "get_tracker", lambda _: tracker)
    monkeypatch.setattr(tasks.task_manager, "is_running", lambda _: False)
    class Socket:
        application_state = WebSocketState.CONNECTED
        headers = {"sec-websocket-protocol": "gd-workstation, gd-token.synthetic"}
        def __init__(self): self.sent = []
        async def accept(self, **kwargs): pass
        async def send_json(self, value):
            if disconnect_on_replay:
                raise RuntimeError(MARKER)
            self.sent.append(value)
        async def close(self, code=1000): self.application_state = WebSocketState.DISCONNECTED
    socket = Socket()
    await tasks.task_ws(socket, 1)
    assert tracker.unsubscribed
    assert MARKER not in json.dumps(socket.sent, ensure_ascii=False)
    if not disconnect_on_replay:
        assert any(item.get("text") == safe_line for item in socket.sent)


@pytest.mark.asyncio
async def test_stream_failure_is_aborted_without_original_exception(caplog):
    import traceback
    from app.services.http_privacy import ConfidentialityMiddleware
    messages = []
    async def broken(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"1000")]})
        await send({"type": "http.response.body", "body": b"partial", "more_body": True})
        raise OSError("FICTIONAL_PRIVATE_TEXT_8c19_" + "客户原文")
    async def send(message): messages.append(message)
    async def receive(): return {"type": "http.request"}
    with pytest.raises(RuntimeError, match="GD_RESPONSE_STREAM_FAILED") as caught:
        await ConfidentialityMiddleware(broken)({"type": "http", "path": "/api/tasks/1/download/pdf"}, receive, send)
    assert caught.value.__suppress_context__
    rendered = "".join(traceback.format_exception(caught.value))
    assert MARKER not in rendered + caplog.text
    assert len([item for item in messages if item["type"] == "http.response.start"]) == 1
    assert messages[-1]["more_body"] is True
    assert all(record.exc_info is None for record in caplog.records)

