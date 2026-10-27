"""Synthetic case ACL integration tests; no model or real client material."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketState

from tests.test_file_import_api import upload_context, upload
from tests.test_task_workflow import wire_storage, fixture_analysis
from app.models import ArchiveTask, Case, CaseFile, TaskStatus, User, Role
from app.routers import tasks
from app.security import create_access_token
from app.services import archive_service, recovery
from app.services.analysis_snapshot import task_work_dir, save_snapshot
from app.services.task_sources import build_source_manifest, source_version


OWNER = {}
OTHER = {"X-Test-User": "colleague"}
ADMIN = {"X-Test-User": "org-admin", "X-Test-Role": "admin"}
FOREIGN_ADMIN = {"X-Test-User": "foreign-admin", "X-Test-Role": "admin", "X-Test-Org": "org-b"}


async def seed(ctx, monkeypatch):
    wire_storage(ctx, monkeypatch)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", ctx.sessions)
    response = await upload(ctx)
    assert response.status_code == 200
    async with ctx.sessions() as db:
        db.add_all([
            User(id="colleague", username="colleague", hashed_password="unused", org_id="org-a", role=Role.lawyer),
            User(id="org-admin", username="org-admin", hashed_password="unused", org_id="org-a", role=Role.admin),
            User(id="foreign-admin", username="foreign-admin", hashed_password="unused", org_id="org-b", role=Role.admin),
            Case(id="legacy", title="虚构历史无创建人案件", case_type="civil", org_id="org-a", created_by=None),
        ])
        files = list((await db.scalars(select(CaseFile))).all())
        manifest = build_source_manifest(files)
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.done,
                           source_manifest=manifest, source_version=source_version(manifest, "civil"),
                           fields={"委托人": "虚构甲"}, catalog_status=[], log_text="归档助理：来源核对完成，已处理 42 / 42 个页面片段")
        db.add(task)
        await db.flush()
        work = Path(task_work_dir("org-a", "case-a", task.id))
        save_snapshot(str(work), fixture_analysis(files[0].abs_path), base_name="synthetic-acl")
        docs = work / "docx"
        docs.mkdir()
        from docx import Document
        document = Document()
        document.add_paragraph("Synthetic ACL fixture")
        from app.services.analysis_snapshot import SYSTEM_TEMPLATE_NAMES
        paths = {}
        for name in SYSTEM_TEMPLATE_NAMES:
            document.save(docs / (name + ".docx"))
            paths["docx:" + name] = docs / (name + ".docx")
        pdf = work / "synthetic.pdf"
        pdf.write_bytes(Path(files[0].abs_path).read_bytes())
        paths["archive_pdf"] = pdf
        quality = work / "quality.json"
        quality.write_text(json.dumps({"synthetic": True}), encoding="utf-8")
        paths["quality_json"] = quality
        html = work / "quality.html"
        html.write_text("<html>Synthetic ACL fixture</html>", encoding="utf-8")
        paths["quality_html"] = html
        package = work / "归档包.zip"
        with zipfile.ZipFile(package, "w") as bundle:
            for path in paths.values():
                bundle.write(path, path.name)
        paths["package_zip"] = package
        task.output_pdf, task.output_docx_dir = str(pdf), str(docs)
        # This fixture tests authorization and byte-change detection only;
        # actual nine-artifact generation is exercised in test_task_workflow.
        task.artifacts = {"valid": True, "result_dir": str(work), "revision": task.revision,
                          "source_version": task.source_version, "artifacts": [
            {"key": key, "path": str(path), "size": path.stat().st_size,
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for key, path in paths.items()]}
        await db.commit()
        return task.id, files[0].id


@pytest.mark.asyncio
async def test_case_reads_downloads_and_evidence_require_owner_or_org_admin(upload_context, monkeypatch):
    ctx = upload_context
    task_id, file_id = await seed(ctx, monkeypatch)
    paths = ["/api/cases/case-a", f"/api/cases/case-a/files/{file_id}/original",
             f"/api/cases/case-a/files/{file_id}/page/1", f"/api/tasks/{task_id}",
             f"/api/tasks/{task_id}/evidence", f"/api/tasks/{task_id}/download/archive",
             f"/api/tasks/{task_id}/download/zip", f"/api/tasks/{task_id}/docx/档案卷宗",
             f"/api/tasks/{task_id}/templates", f"/api/tasks/{task_id}/preview-fields/档案卷宗"]
    for headers, allowed in [(OWNER, True), (ADMIN, True), (OTHER, False), (FOREIGN_ADMIN, False)]:
        listed = (await ctx.client.get("/api/cases", headers=headers)).json()
        assert ("case-a" in {case["id"] for case in listed}) is allowed
        for path in paths:
            response = await ctx.client.get(path, headers=headers)
            assert response.status_code == (200 if allowed else 404), (headers, path, response.text[:200])
    assert (await ctx.client.get("/api/cases/legacy")).status_code == 404
    assert (await ctx.client.get("/api/cases/legacy", headers=OTHER)).status_code == 404
    assert (await ctx.client.get("/api/cases/legacy", headers=ADMIN)).status_code == 200
    assert (await ctx.client.get("/api/cases/legacy", headers=FOREIGN_ADMIN)).status_code == 404


@pytest.mark.asyncio
async def test_nonowner_mutations_and_template_routes_are_rejected(upload_context, monkeypatch):
    ctx = upload_context
    task_id, file_id = await seed(ctx, monkeypatch)
    operations = [
        ("POST", "/api/cases/case-a/generate", {"order_mode": "catalog"}),
        ("POST", f"/api/tasks/{task_id}/resume", None),
        ("PATCH", f"/api/tasks/{task_id}/fields", {"fields": {"委托人": "forged"}}),
        ("POST", f"/api/tasks/{task_id}/regenerate-templates", {"fields": {}}),
        ("POST", f"/api/tasks/{task_id}/assemble", {"confirmation": True, "confirmed_revision": 1, "skipped": []}),
        ("POST", f"/api/tasks/{task_id}/complete-review", None),
        ("PUT", f"/api/tasks/{task_id}/preview-fields/档案卷宗", {"values": {}}),
        ("GET", f"/api/tasks/{task_id}/preview/档案卷宗", None),
        ("POST", f"/api/tasks/{task_id}/refill", {"fields": {}}),
        ("DELETE", f"/api/tasks/{task_id}", None),
        ("PATCH", f"/api/cases/case-a/files/{file_id}", {"doc_type": "default"}),
        ("DELETE", f"/api/cases/case-a/files/{file_id}", None),
    ]
    for headers in (OTHER, FOREIGN_ADMIN):
        for method, path, body in operations:
            response = await ctx.client.request(method, path, headers=headers, **({"json": body} if body is not None else {}))
            assert response.status_code == 404, (method, path, response.text)
        assert (await ctx.client.post("/api/cases/case-a/files", headers=headers,
                files={"file": ("not-read.pdf", b"not read")}, data={"doc_type": "default"})).status_code == 404
        assert (await ctx.client.put(f"/api/tasks/{task_id}/docx/档案卷宗", headers=headers,
                files={"file": ("not-read.docx", b"not read")})).status_code == 404
    for headers in (OWNER, ADMIN):
        assert (await ctx.client.post(f"/api/tasks/{task_id}/resume", headers=headers)).status_code == 200
        assert (await ctx.client.post("/api/cases/case-a/generate", headers=headers, json={})).json()["id"] == task_id
    changed = await ctx.client.patch(f"/api/tasks/{task_id}/fields", headers=ADMIN, json={"fields": {"委托人": "管理员按虚构原件核对"}})
    assert changed.status_code == 200
    assert changed.json()["fields"]["委托人"] == "管理员按虚构原件核对"


@pytest.mark.asyncio
async def test_websocket_does_not_stream_colleague_or_foreign_case_logs(upload_context, monkeypatch):
    ctx = upload_context
    task_id, _ = await seed(ctx, monkeypatch)
    class Socket:
        application_state = WebSocketState.CONNECTED
        def __init__(self, actor, org):
            token = create_access_token(actor, {"org": org, "role": "admin"})
            self.headers = {"sec-websocket-protocol": "gd-workstation, gd-token." + token}
            self.query_params = {"token": "ignored-invalid-url-token"}
            self.sent = []
            self.protocol = None
        async def accept(self, subprotocol=None): self.protocol = subprotocol
        async def send_json(self, value): self.sent.append(value)
        async def close(self, code=1000): self.application_state = WebSocketState.DISCONNECTED
    class Tracker:
        log_lines = ["归档助理：来源核对完成，已处理 42 / 42 个页面片段"]
        async def subscribe(self):
            queue = asyncio.Queue()
            queue.put_nowait({"type": "done"})
            return queue
        async def unsubscribe(self, queue): pass
    monkeypatch.setattr(tasks.task_manager, "get_tracker", lambda _: Tracker())
    monkeypatch.setattr(tasks.task_manager, "is_running", lambda _: False)
    for actor, org, allowed in [("test-user", "org-a", True), ("org-admin", "org-a", True),
                                ("colleague", "org-a", False), ("foreign-admin", "org-b", False)]:
        socket = Socket(actor, org)
        await tasks.task_ws(socket, task_id)
        assert socket.protocol == "gd-workstation"
        has_log = any(item.get("text") == "归档助理：来源核对完成，已处理 42 / 42 个页面片段" for item in socket.sent)
        assert has_log is allowed
        if not allowed:
            assert socket.sent == [{"type": "error", "error": "task not found"}]


@pytest.mark.asyncio
async def test_background_context_and_recovery_apply_same_case_permission(upload_context, monkeypatch):
    ctx = upload_context
    task_id, _ = await seed(ctx, monkeypatch)
    async def config(*_args, **kwargs): return {}
    monkeypatch.setattr(archive_service, "build_v4_config", config)
    for actor, allowed in [("test-user", True), ("org-admin", True), ("colleague", False), ("foreign-admin", False)]:
        assert bool(await archive_service._load_case_context("case-a", "org-a", actor)) is allowed
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, task_id)
        task.status = TaskStatus.running
        task.created_by = "colleague"
        await db.commit()
    launched = []
    def start(task_id, coroutine):
        launched.append(task_id)
        coroutine.close()
    monkeypatch.setattr(recovery, "AsyncSessionLocal", ctx.sessions)
    monkeypatch.setattr(tasks.task_manager, "start", start)
    await recovery.recover_interrupted_tasks()
    async with ctx.sessions() as db:
        assert (await db.get(ArchiveTask, task_id)).status == TaskStatus.failed
    assert launched == []


@pytest.mark.asyncio
async def test_org_admin_cannot_gain_foreign_access_through_account_management(upload_context, monkeypatch):
    ctx = upload_context
    await seed(ctx, monkeypatch)
    orgs = await ctx.client.get("/api/admin/orgs", headers=ADMIN)
    assert orgs.status_code == 200
    assert [item["id"] for item in orgs.json()] == ["org-a"]
    listed = await ctx.client.get("/api/admin/users", headers=ADMIN)
    assert listed.status_code == 200
    assert all(item["org_id"] == "org-a" for item in listed.json())
    assert "foreign-admin" not in {item["id"] for item in listed.json()}
    assert (await ctx.client.post("/api/admin/users", headers=ADMIN, json={
        "username": "foreign-created", "password": "synthetic-only-password", "role": "admin", "org_id": "org-b"
    })).status_code == 403
    assert (await ctx.client.put("/api/admin/users/foreign-admin", headers=ADMIN,
            json={"password": "reset-attempt", "role": "lawyer", "is_active": False})).status_code == 404
    assert (await ctx.client.delete("/api/admin/users/foreign-admin", headers=ADMIN)).status_code == 404
    assert (await ctx.client.post("/api/admin/orgs", headers=ADMIN, json={"name": "unauthorized organization"})).status_code == 403
    assert (await ctx.client.get("/api/admin/users", headers=OWNER)).status_code == 403
    created = await ctx.client.post("/api/admin/users", headers=ADMIN, json={
        "username": "own-created", "password": "synthetic-only-password", "role": "lawyer"
    })
    assert created.status_code == 201
    assert created.json()["org_id"] == "org-a"
    updated = await ctx.client.put("/api/admin/users/colleague", headers=ADMIN, json={"display_name": "本机构虚构同事"})
    assert updated.status_code == 200
    async with ctx.sessions() as db:
        foreign = await db.get(User, "foreign-admin")
        assert foreign.hashed_password == "unused" and foreign.is_active and foreign.role == Role.admin


@pytest.mark.asyncio
@pytest.mark.parametrize("actor,revocation", [("test-user", "disable"), ("org-admin", "demote")])
async def test_live_websocket_stops_before_next_log_after_access_revocation(upload_context, monkeypatch, actor, revocation):
    ctx = upload_context
    task_id, _ = await seed(ctx, monkeypatch)
    class Socket:
        application_state = WebSocketState.CONNECTED
        headers = {"sec-websocket-protocol": "gd-workstation, gd-token." + create_access_token(actor, {"org": "org-a"})}
        query_params = {}
        def __init__(self):
            self.sent, self.code = [], None
        async def accept(self, subprotocol=None): pass
        async def send_json(self, value):
            self.sent.append(value)
            if value.get("type") == "progress":
                async with ctx.sessions() as db:
                    target = await db.get(User, actor)
                    if revocation == "disable":
                        target.is_active = False
                    else:
                        target.role = Role.lawyer
                    await db.commit()
        async def close(self, code=1000):
            self.code = code
            self.application_state = WebSocketState.DISCONNECTED
    class Tracker:
        log_lines = []
        async def subscribe(self):
            queue = asyncio.Queue()
            queue.put_nowait({"type": "log", "text": "PRIVATE AFTER REVOCATION"})
            queue.put_nowait({"type": "done"})
            return queue
        async def unsubscribe(self, queue): pass
    monkeypatch.setattr(tasks.task_manager, "get_tracker", lambda _: Tracker())
    monkeypatch.setattr(tasks.task_manager, "is_running", lambda _: False)
    socket = Socket()
    await tasks.task_ws(socket, task_id)
    assert socket.code == 4403
    assert not any(item.get("text") == "PRIVATE AFTER REVOCATION" for item in socket.sent)


@pytest.mark.asyncio
async def test_websocket_rejects_query_credentials_without_safe_subprotocol():
    class Socket:
        headers = {}
        query_params = {"token": create_access_token("test-user", {"org": "org-a"})}
        code = None
        async def close(self, code=1000): self.code = code
        async def accept(self, subprotocol=None): raise AssertionError("Query token must not be accepted")
    socket = Socket()
    await tasks.task_ws(socket, 1)
    assert socket.code == 4401
