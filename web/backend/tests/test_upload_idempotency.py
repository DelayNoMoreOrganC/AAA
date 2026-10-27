"""Fictional ASGI uploads: retries preserve one source without bypassing ACLs."""
import asyncio
from io import BytesIO

from PIL import Image
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tests.test_file_import_api import upload_context, pdf_bytes
from app.database import migrate_upload_columns
from app.models import Case, CaseFile
from app.routers import cases


async def send(ctx, payload, *, key="upload-fixture-001", filename="虚构材料.pdf", doc_type="default", case_id="case-a", headers=None):
    request_headers = dict(headers or {})
    if key is not None:
        request_headers["Idempotency-Key"] = key
    return await ctx.client.post(f"/api/cases/{case_id}/files", headers=request_headers,
        data={"doc_type": doc_type}, files={"file": (filename, payload)})


async def records(ctx):
    async with ctx.sessions() as db:
        return list((await db.scalars(select(CaseFile))).all())


def track_normalizer(monkeypatch):
    original, calls = cases.normalize_import, []
    def run(*args):
        calls.append(args[0])
        return original(*args)
    monkeypatch.setattr(cases, "normalize_import", run)
    return calls


@pytest.mark.asyncio
async def test_lost_success_response_retry_returns_original_record_without_normalizing_twice(upload_context, monkeypatch):
    ctx = upload_context
    calls = track_normalizer(monkeypatch)
    payload = pdf_bytes("Fictional same source")
    first = await send(ctx, payload)
    second = await send(ctx, payload)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(await records(ctx)) == len(calls) == 1
    assert len(list(ctx.root.rglob("original.pdf"))) == 1
    assert (ctx.root / (await records(ctx))[0].stored_name).read_bytes() == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["bytes", "filename", "doc_type"])
async def test_same_key_different_payload_is_conflict_without_replacing_original(upload_context, change):
    ctx = upload_context
    payload = pdf_bytes("Fictional first")
    first = await send(ctx, payload)
    second = await send(ctx, pdf_bytes("Fictional different") if change == "bytes" else payload,
        filename="另一虚构材料.pdf" if change == "filename" else "虚构材料.pdf",
        doc_type="evidence" if change == "doc_type" else "default")
    assert first.status_code == 200 and second.status_code == 409
    rows = await records(ctx)
    assert len(rows) == 1 and rows[0].id == first.json()["id"]
    assert (ctx.root / rows[0].stored_name).read_bytes() == payload
    assert len(list(ctx.root.rglob("original.pdf"))) == 1


@pytest.mark.asyncio
async def test_no_key_keeps_legacy_deliberate_duplicate_uploads(upload_context):
    ctx = upload_context
    payload = pdf_bytes("Fictional duplicate explicitly selected twice")
    first, second = await send(ctx, payload, key=None), await send(ctx, payload, key=None)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert len(await records(ctx)) == 2
    assert all(row.upload_request_id is None for row in await records(ctx))


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{"X-Test-User": "peer"}, {"X-Test-Org": "org-b"}])
async def test_known_retry_key_does_not_bypass_case_ownership(upload_context, headers):
    ctx = upload_context
    payload = pdf_bytes("Fictional private")
    assert (await send(ctx, payload)).status_code == 200
    assert (await send(ctx, payload, headers=headers)).status_code == 404
    assert len(await records(ctx)) == 1


@pytest.mark.asyncio
async def test_request_identity_is_scoped_to_case_and_authenticated_user(upload_context):
    ctx = upload_context
    async with ctx.sessions() as db:
        db.add(Case(id="case-second", title="第二虚构案件", org_id="org-a", created_by="test-user", case_type="civil"))
        await db.commit()
    payload = pdf_bytes("Fictional scoped identity")
    first = await send(ctx, payload)
    other_case = await send(ctx, payload, case_id="case-second")
    admin = await send(ctx, payload, headers={"X-Test-User": "another-admin", "X-Test-Role": "admin"})
    assert first.status_code == other_case.status_code == admin.status_code == 200
    assert len({first.json()["id"], other_case.json()["id"], admin.json()["id"]}) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["", " ", "wrong/key", "x" * 129])
async def test_invalid_request_key_is_rejected_before_storing_bytes(upload_context, key):
    ctx = upload_context
    assert (await send(ctx, pdf_bytes("Fictional"), key=key)).status_code == 400
    assert await records(ctx) == []
    assert not list(ctx.root.rglob("original.pdf"))


@pytest.mark.asyncio
async def test_failed_import_does_not_reserve_key_and_same_request_can_retry(upload_context, monkeypatch):
    ctx = upload_context
    payload = pdf_bytes("Fictional retry after conversion failure")
    original = cases.normalize_import
    def fail(*_):
        raise cases.ImportFailure("虚构测试导入失败", 422)
    monkeypatch.setattr(cases, "normalize_import", fail)
    assert (await send(ctx, payload)).status_code == 422
    assert await records(ctx) == [] and not list(ctx.root.rglob("original.pdf"))
    monkeypatch.setattr(cases, "normalize_import", original)
    assert (await send(ctx, payload)).status_code == 200
    assert len(await records(ctx)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("after_commit", [False, True])
async def test_commit_ack_failure_preserves_committed_bytes_or_allows_retry(upload_context, monkeypatch, after_commit):
    ctx = upload_context
    payload = pdf_bytes("Fictional commit acknowledgement")
    original_commit = AsyncSession.commit
    calls = 0
    async def fail_once(db):
        nonlocal calls
        calls += 1
        if calls == 1:
            if after_commit:
                await original_commit(db)
            raise RuntimeError("synthetic commit acknowledgement failure")
        await original_commit(db)
    monkeypatch.setattr(AsyncSession, "commit", fail_once)
    if after_commit:
        assert (await send(ctx, payload)).status_code == 200
    else:
        failure = await send(ctx, payload)
        assert failure.status_code == 500
        assert "synthetic commit" not in failure.text
        assert await records(ctx) == []
        assert not list(ctx.root.rglob("original.pdf"))
    retry = await send(ctx, payload)
    assert retry.status_code == 200
    rows = await records(ctx)
    assert len(rows) == 1
    assert (ctx.root / rows[0].stored_name).read_bytes() == payload


@pytest.mark.asyncio
async def test_same_key_concurrent_requests_share_one_material(upload_context, monkeypatch):
    ctx = upload_context
    # A contended asyncio.Lock binds to its loop. pytest opens a new loop per
    # test, unlike the one-loop ASGI worker; do not inherit a previous test's
    # already-closed loop. All three uploads still share one real lock here.
    monkeypatch.setattr(cases.task_manager, "_case_locks", {})
    calls = track_normalizer(monkeypatch)
    payload = pdf_bytes("Fictional parallel retry")
    responses = await asyncio.gather(*(send(ctx, payload) for _ in range(3)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["id"] for r in responses}) == len(await records(ctx)) == len(calls) == 1


@pytest.mark.asyncio
async def test_unique_constraint_handles_receipt_committed_after_lookup(upload_context, monkeypatch):
    ctx = upload_context
    payload = pdf_bytes("Fictional cross-worker commit race")
    first = await send(ctx, payload)
    original_lookup = cases._upload_receipt
    calls = 0
    async def missing_once(*args):
        nonlocal calls
        calls += 1
        return None if calls == 1 else await original_lookup(*args)
    # Simulates another worker committing between lookup and INSERT. The
    # resulting unique-index conflict and rollback are real SQLite operations.
    monkeypatch.setattr(cases, "_upload_receipt", missing_once)
    second = await send(ctx, payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(await records(ctx)) == len(list(ctx.root.rglob("original.pdf"))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("damaged", ["original", "normalized", "missing"])
async def test_retry_refuses_changed_or_missing_stored_source(upload_context, damaged):
    ctx = upload_context
    image = BytesIO()
    Image.new("RGB", (30, 40), "white").save(image, format="PNG")
    payload = image.getvalue()
    first = await send(ctx, payload, filename="虚构图片.png")
    assert first.status_code == 200
    stored = ctx.root / (await records(ctx))[0].stored_name
    if damaged == "missing":
        stored.unlink()
    elif damaged == "normalized":
        stored.write_bytes(pdf_bytes("Fictional changed normalized page"))
    else:
        (stored.parent / "original.png").write_bytes(b"synthetic corruption")
    assert (await send(ctx, payload, filename="虚构图片.png")).status_code == 409
    assert len(await records(ctx)) == 1
    assert len(list(ctx.root.rglob("original.png"))) == 1


@pytest.mark.asyncio
async def test_retry_does_not_revert_subsequent_file_classification(upload_context):
    ctx = upload_context
    payload = pdf_bytes("Fictional later user classification")
    first = await send(ctx, payload)
    edited = await ctx.client.patch(f"/api/cases/case-a/files/{first.json()['id']}", json={"doc_type": "evidence"})
    assert edited.status_code == 200
    retry = await send(ctx, payload)
    assert retry.status_code == 200 and retry.json()["doc_type"] == "evidence"
    assert retry.json()["id"] == first.json()["id"]


@pytest.mark.asyncio
async def test_additive_upload_migration_preserves_legacy_rows_and_is_repeatable():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE TABLE case_files (id VARCHAR(32) PRIMARY KEY, case_id VARCHAR(32), filename TEXT)")
            await conn.exec_driver_sql("INSERT INTO case_files(id, case_id, filename) VALUES ('old', 'case', 'original')")
            await migrate_upload_columns(conn)
            await migrate_upload_columns(conn)
            assert (await conn.exec_driver_sql("SELECT id, filename, upload_request_id FROM case_files")).one() == ("old", "original", None)
            await conn.exec_driver_sql("INSERT INTO case_files(id, case_id, upload_owner_id, upload_request_id) VALUES ('a', 'case', 'owner', 'request')")
            with pytest.raises(IntegrityError):
                await conn.exec_driver_sql("INSERT INTO case_files(id, case_id, upload_owner_id, upload_request_id) VALUES ('b', 'case', 'owner', 'request')")
    finally:
        await engine.dispose()
