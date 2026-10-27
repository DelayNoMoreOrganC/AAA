"""API regressions for material ownership and immutable upload storage."""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import sys

import fitz
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from PIL import Image
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app
from app.database import Base, get_db
from app.deps import get_current_user
from app.models import ArchiveTask, Case, CaseFile, Org, Role, TaskStatus, User
from app.routers import cases, tasks


def pdf_bytes(label):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), label)
        return doc.tobytes()


@pytest_asyncio.fixture
async def upload_context(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add_all([Org(id="org-a", name="虚构律所甲"), Org(id="org-b", name="虚构律所乙")])
        session.add(User(id="test-user", org_id="org-a", username="test-owner", hashed_password="synthetic-unused", role=Role.lawyer))
        session.add(Case(id="case-a", title="虚构测试案件", case_type="civil", org_id="org-a", created_by="test-user"))
        await session.commit()
    monkeypatch.setattr(cases, "ORGS_DIR", tmp_path)

    async def test_db():
        async with sessions() as session:
            yield session

    async def test_user(request: Request):
        return SimpleNamespace(id=request.headers.get("X-Test-User", "test-user"),
                               org_id=request.headers.get("X-Test-Org", "org-a"),
                               role=Role(request.headers.get("X-Test-Role", "lawyer")), is_active=True)

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_current_user] = test_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(client=client, sessions=sessions, root=tmp_path)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        await engine.dispose()


async def upload(context, name="材料.pdf", content=None):
    return await context.client.post("/api/cases/case-a/files", files={"file": (name, content or pdf_bytes("Fictional PDF"))}, data={"doc_type": "default"})


@pytest.mark.asyncio
async def test_same_filename_does_not_overwrite_and_delete_is_independent(upload_context):
    ctx = upload_context
    first_bytes, second_bytes = pdf_bytes("First fictional item"), pdf_bytes("Second fictional item")
    first = await upload(ctx, content=first_bytes)
    second = await upload(ctx, content=second_bytes)
    assert first.status_code == second.status_code == 200
    async with ctx.sessions() as session:
        files = (await session.scalars(select(CaseFile).order_by(CaseFile.created_at))).all()
        first_path, second_path = [ctx.root / f.stored_name for f in files]
    assert first_path != second_path
    assert first_path.read_bytes() == first_bytes
    assert second_path.read_bytes() == second_bytes
    deleted = await ctx.client.delete("/api/cases/case-a/files/" + first.json()["id"])
    assert deleted.status_code == 204
    assert not first_path.exists()
    assert second_path.read_bytes() == second_bytes
    original = await ctx.client.get("/api/cases/case-a/files/" + second.json()["id"] + "/original")
    assert original.content == second_bytes


@pytest.mark.asyncio
async def test_other_org_cannot_read_update_or_delete_material(upload_context):
    ctx = upload_context
    result = await upload(ctx)
    file_id = result.json()["id"]
    url = "/api/cases/case-a/files/" + file_id
    headers = {"X-Test-Org": "org-b"}
    assert (await ctx.client.get(url + "/original", headers=headers)).status_code == 404
    assert (await ctx.client.patch(url, json={"doc_type": "default"}, headers=headers)).status_code == 404
    assert (await ctx.client.delete(url, headers=headers)).status_code == 404
    assert (await ctx.client.get(url + "/original")).status_code == 200


@pytest.mark.asyncio
async def test_invalid_pdf_is_not_saved_as_success(upload_context):
    ctx = upload_context
    result = await upload(ctx, content=b"not a PDF")
    assert result.status_code == 400
    async with ctx.sessions() as session:
        assert list((await session.scalars(select(CaseFile))).all()) == []
    assert not list(ctx.root.rglob("original.pdf"))


@pytest.mark.asyncio
async def test_demo_conversion_failure_returns_detail_and_rolls_back(upload_context, monkeypatch):
    from app.routers import demo
    from app.services.file_import_service import ImportFailure
    ctx = upload_context
    monkeypatch.setattr(demo, "ORGS_DIR", ctx.root)
    monkeypatch.setattr(demo, "DATA_DIR", ctx.root)

    def fictional_input(directory, kind):
        source = directory / 'fictional.docx'
        source.write_bytes(b'fictional-test-only')
        return [source]

    def fail(*_args):
        raise ImportFailure('DOCX 转换失败，虚构测试错误', 422)

    monkeypatch.setattr(demo, 'create_demo_inputs', fictional_input)
    monkeypatch.setattr(demo, 'normalize_import', fail)
    result = await ctx.client.post('/api/demo/cases', json={'kind':'mixed'})
    assert result.status_code == 422
    assert result.json()['detail'] == 'DOCX 转换失败，虚构测试错误'
    async with ctx.sessions() as session:
        assert [case.id for case in (await session.scalars(select(Case))).all()] == ['case-a']
        assert list((await session.scalars(select(CaseFile))).all()) == []
    assert not list(ctx.root.rglob('original.docx'))


@pytest.mark.asyncio
async def test_oversized_upload_is_rejected_and_partial_file_removed(upload_context, monkeypatch):
    ctx = upload_context
    monkeypatch.setattr(cases._settings, "max_upload_mb", 1)
    result = await upload(ctx, content=b"%PDF-1.4\n" + b"0" * (1024 * 1024))
    assert result.status_code == 413
    assert not list(ctx.root.rglob("original.pdf"))


@pytest.mark.asyncio
async def test_image_import_retains_original_and_exposes_pdf_to_archive(upload_context):
    ctx = upload_context
    raw = BytesIO()
    with Image.new("RGB", (60, 90), "white") as image:
        image.save(raw, format="PNG")
    result = await upload(ctx, "虚构扫描.png", raw.getvalue())
    assert result.status_code == 200
    item = result.json()
    assert item["filename"] == "虚构扫描.png"
    async with ctx.sessions() as session:
        record = await session.get(CaseFile, item["id"])
        path = ctx.root / record.stored_name
    assert path.suffix == ".pdf"
    with fitz.open(path) as document:
        assert document.page_count == 1
    original = await ctx.client.get("/api/cases/case-a/files/" + item["id"] + "/original")
    assert original.content == raw.getvalue()


@pytest.mark.asyncio
async def test_material_cannot_be_deleted_while_review_snapshot_uses_it(upload_context):
    ctx = upload_context
    result = await upload(ctx)
    async with ctx.sessions() as session:
        task = ArchiveTask(case_id="case-a", status=TaskStatus.awaiting_review)
        session.add(task)
        await session.commit()
        task_id = task.id
    detail = await ctx.client.get("/api/cases/case-a")
    assert detail.json()["last_task_id"] == task_id
    assert detail.json()["last_task_status"] == "awaiting_review"
    listing = await ctx.client.get("/api/cases")
    assert listing.json()[0]["last_task_id"] == task_id
    original_url = "/api/cases/case-a/files/" + result.json()["id"]
    assert (await ctx.client.delete(original_url)).status_code == 409
    assert (await ctx.client.get(original_url + "/original")).status_code == 200


@pytest.mark.asyncio
async def test_invalid_material_type_does_not_create_a_file(upload_context):
    ctx = upload_context
    result = await ctx.client.post("/api/cases/case-a/files", files={"file": ("file.pdf", pdf_bytes("Fictional"))}, data={"doc_type": "not-a-doc-type"})
    assert result.status_code == 400
    assert not list(ctx.root.rglob("original.pdf"))


async def review_task(context, fields, missing=True):
    async with context.sessions() as session:
        task = ArchiveTask(
            case_id="case-a", status=TaskStatus.awaiting_review, fields=fields,
            catalog_status=[{"seq": 5, "found": False, "name": "虚构材料"}] if missing else [],
        )
        session.add(task)
        await session.commit()
        return task.id


def isolate_assembly(monkeypatch):
    launched = []

    def record_start(task_id, coroutine):
        launched.append(task_id)
        coroutine.close()

    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(capabilities={"archive_assembly": True}, preview_only=True))
    monkeypatch.setattr(tasks.task_manager, "is_running", lambda task_id: False)
    monkeypatch.setattr(tasks.task_manager, "start", record_start)
    async def unchanged(*args):
        return False
    # This fixture isolates review/approval validation from source hashing.
    monkeypatch.setattr(tasks, "_source_changed", unchanged)
    return launched


@pytest.mark.asyncio
@pytest.mark.parametrize("decisions,skipped", [
    ({}, [5]),
    ({"5": {"action": "pending", "reason": ""}}, [5]),
    ({"5": {"action": "skip", "reason": "  "}}, [5]),
    ({"5": {"action": "not_applicable", "reason": ""}}, [5]),
    ({"5": {"action": "invented", "reason": "test"}}, [5]),
    (["not-a-map"], [5]),
    ({"5": {"action": "not_applicable"}}, []),
    ({"5": {"action": "not_applicable"}}, [5, 6]),
    ({"5": {"action": "not_applicable"}}, [5, 5]),
])
async def test_assembly_cannot_bypass_saved_missing_item_decisions(upload_context, monkeypatch, decisions, skipped):
    ctx = upload_context
    launched = isolate_assembly(monkeypatch)
    task_id = await review_task(ctx, {"_review_decisions": decisions})
    response = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json={"skipped": skipped})
    assert response.status_code == 409
    assert launched == []
    async with ctx.sessions() as session:
        assert (await session.get(ArchiveTask, task_id)).status == TaskStatus.awaiting_review


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [{"action": "skip", "reason": "虚构测试中暂未收到"}, {"action": "not_applicable", "reason": "虚构案件没有该程序"}])
async def test_assembly_accepts_explicit_saved_decisions(upload_context, monkeypatch, decision):
    ctx = upload_context
    launched = isolate_assembly(monkeypatch)
    task_id = await review_task(ctx, {"_review_decisions": {"5": decision}})
    response = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json={"skipped": [5], "confirmation": True, "confirmed_revision": 1})
    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert launched == [task_id]


@pytest.mark.asyncio
async def test_complete_catalog_does_not_require_fake_missing_decisions(upload_context, monkeypatch):
    ctx = upload_context
    launched = isolate_assembly(monkeypatch)
    task_id = await review_task(ctx, {}, missing=False)
    response = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json={"skipped": [], "confirmation": True, "confirmed_revision": 1})
    assert response.status_code == 200
    assert launched == [task_id]
