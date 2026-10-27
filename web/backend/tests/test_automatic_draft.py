"""Synthetic automatic delivery: real DOCX/merge/ZIP, stubbed model and PDF renderer."""
import copy
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
import zipfile

import fitz
import pytest
import pytest_asyncio
from sqlalchemy import select

from tests.test_file_import_api import upload_context, upload
from tests.test_task_workflow import fixture_analysis, wire_storage
from app.models import ArchiveTask, Case, CaseFile, TaskStatus
from app.routers import tasks
from app.services import archive_service, recovery, browser_pdf_service, output_export
from app.services.analysis_snapshot import save_snapshot, load_snapshot_data, snapshot_path, _atomic_write, task_work_dir, SYSTEM_TEMPLATE_NAMES
from app.services.task_sources import build_source_manifest, source_version, fields_digest


@pytest_asyncio.fixture
async def draft_context(upload_context, monkeypatch):
    from app.core.v4_bridge import init_v4_path
    init_v4_path()
    import archive_pipeline as ap
    import archive_catalog as ac
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    with fitz.open() as pdf:
        for label in ("UNIQUE_SYNTHETIC_SOURCE_A", "UNIQUE_SYNTHETIC_SOURCE_B"):
            pdf.new_page().insert_text((72, 72), label)
        content = pdf.tobytes()
    await upload(ctx, name="完全虚构材料.pdf", content=content)
    async with ctx.sessions() as db:
        ctx.files = list((await db.scalars(select(CaseFile))).all())
    ctx.manifest = build_source_manifest(ctx.files)
    ctx.version = source_version(ctx.manifest, "civil")
    ctx.analysis = fixture_analysis(ctx.files[0].abs_path, {"委托人":"完全虚构客户", "合同号":"虚构合同1",
        "_ocr_review":[{"source_path":ctx.files[0].abs_path,"page":1,"reason":"虚构识别疑问仍待核对"}]})
    ctx.analysis.doc_spans[0].end_page = 1
    catalog = ac.get_catalog("civil")
    ctx.analysis.found_seqs = ap.compute_found_seqs(catalog, ctx.analysis.doc_spans, {})
    ctx.analysis.found_seqs.update(item.seq for item in catalog if item.source == "system")
    ctx.analysis.missing_items = ap.compute_missing_items("civil", catalog, ctx.analysis.found_seqs)
    ctx.issues = [{"id":"synthetic-ocr", "kind":"ocr", "blocking":True, "message":"虚构识别疑问仍待核对"}]
    ctx.exported, ctx.rendered = [], []
    ctx.base_config = {"output":{"preview_only":True}}
    async def case_context(*args):
        return SimpleNamespace(case_type="civil", stage=""), ctx.files, copy.deepcopy(ctx.base_config)
    async def org_name(*args): return "完全虚构测试律所"
    async def inline(fn, *args, **kwargs): return fn(*args, **kwargs)
    async def task_config(*args, **kwargs): return copy.deepcopy(ctx.base_config)
    async def ready(*args, **kwargs): return {"ready":True,"issues":[]}
    def render(fields, organization, work, log):
        ctx.rendered.append(work)
        directory = Path(work) / "browser_pdf"
        directory.mkdir(parents=True, exist_ok=True)
        result = {}
        for name in SYSTEM_TEMPLATE_NAMES:
            path = directory / (name + ".pdf")
            with fitz.open() as pdf:
                pdf.new_page(width=595.28,height=841.89).insert_text((72,72),"SYNTHETIC_SYSTEM_FORM")
                pdf.save(path)
            result[name] = str(path)
        return result
    def cover(name, fields, organization, path, log=print, *, derived_output=None):
        with fitz.open() as pdf:
            pdf.new_page(width=595.28,height=841.89).insert_text((72,72),str(derived_output["volume_page_count"])+" 页",fontname="china-s")
            pdf.save(path)
        return str(path)
    def export(work, *args): ctx.exported.append(work); return str(work)
    monkeypatch.setattr(archive_service,"_load_case_context",case_context)
    monkeypatch.setattr(archive_service,"_load_org_name",org_name)
    monkeypatch.setattr(archive_service,"archive_pipeline",lambda:ap)
    monkeypatch.setattr(archive_service,"render_system_form_pdfs",render)
    monkeypatch.setattr(archive_service,"get_settings",lambda:SimpleNamespace(preview_only=True))
    monkeypatch.setattr(archive_service,"run_word",inline)
    monkeypatch.setattr(archive_service,"task_config",task_config)
    monkeypatch.setattr(archive_service,"check_readiness",ready)
    monkeypatch.setattr(tasks,"check_readiness",ready)
    monkeypatch.setattr(browser_pdf_service,"render_form_pdf",cover)
    monkeypatch.setattr(output_export,"export_archive",export)
    ctx.analysis_calls = []
    def analyze(*args, **kwargs):
        ctx.analysis_calls.append(True)
        return copy.deepcopy(ctx.analysis)
    monkeypatch.setattr(ap,"analyze_archive",analyze)
    return ctx


async def create_review(ctx, *, status=TaskStatus.awaiting_review, verified_required=False):
    catalog = archive_service._build_catalog_status(ctx.analysis)
    if verified_required:
        missing = next(item for item in catalog if not item["found"])
        missing.update(requirement="required",legal_requirement_verified=True)
    async with ctx.sessions() as db:
        task = ArchiveTask(case_id="case-a",created_by="test-user",status=status,revision=3,
            source_manifest=ctx.manifest,source_version=ctx.version,fields=copy.deepcopy(ctx.analysis.fields),
            requested_operation="draft",issues=copy.deepcopy(ctx.issues),catalog_status=catalog)
        db.add(task); await db.commit()
        ctx.task_id = task.id
    ctx.work = Path(task_work_dir("org-a","case-a",ctx.task_id))
    save_snapshot(str(ctx.work),ctx.analysis,base_name="完全虚构草稿",metadata={"source_version":ctx.version,"revision":3})
    return ctx.task_id


async def make_draft(ctx):
    await archive_service.run_assemble(ctx.task_id,"case-a","org-a","test-user",draft=True)
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask,ctx.task_id)
        assert task.status == TaskStatus.awaiting_review, task.error
        assert task.phase == "draft_ready" and task.artifacts["valid"]
        assert task.confirmation is None and not task.rule_readiness["formal_ready"]
        return task


def assert_nine_complete(task):
    assert task.artifacts["delivery_kind"] == "draft"
    entries = task.artifacts["artifacts"]
    assert len(entries) == 9
    assert len(list(Path(task.output_docx_dir).glob("*.docx"))) == 5
    with zipfile.ZipFile(Path(task.artifacts["result_dir"],"归档包.zip")) as package:
        assert len(package.namelist()) == 8
        for entry in entries:
            if entry["key"] != "package_zip":
                assert hashlib.sha256(package.read(Path(entry["path"]).name)).hexdigest() == entry["sha256"]
    report = json.loads(Path(task.artifacts["result_dir"],"归档质检清单.json").read_text(encoding="utf-8"))
    assert report["automatically_generated_draft"] is True
    assert report["values_status"] == "自动整理，尚未经人工最终确认"
    assert report["source_page_conservation"] == "passed" and report["original_pages_included"] == 2
    assert report["missing_items"] and report["unresolved_review_items"]
    assert not report["review_decisions"]
    with fitz.open(task.output_pdf) as pdf:
        text = "\n".join(page.get_text() for page in pdf)
        for label in ("UNIQUE_SYNTHETIC_SOURCE_A","UNIQUE_SYNTHETIC_SOURCE_B"):
            assert text.count(label) == 1
        assert pdf.get_toc() and any(page.get_links() for page in pdf)
        for number,page in enumerate(pdf,1):
            assert page.get_label() == ""
            assert not re.search(rf"GD\s+{number}\s*/\s*{len(pdf)}\s*$",page.get_text())
        assert task.artifacts["pagination"]["mode"] == "draft"
        assert task.artifacts["derived_output"]["volume_page_count"] == len(pdf)


@pytest.mark.asyncio
async def test_new_generate_automatically_delivers_real_nine_artifact_draft(draft_context, monkeypatch):
    ctx = draft_context
    launched = []
    def capture(task_id, coroutine): launched.append(task_id); coroutine.close()
    monkeypatch.setattr(tasks.task_manager,"start",capture)
    response = await ctx.client.post("/api/cases/case-a/generate",json={})
    assert response.status_code == 201, response.text
    ctx.task_id = response.json()["id"]
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask,ctx.task_id)
        assert task.requested_operation == "analyze_and_draft" and task.confirmation is None
    assert launched == [ctx.task_id]
    # Only analysis is stubbed. Production run_archive invokes production run_assemble.
    await archive_service.run_archive(ctx.task_id,"case-a","org-a","test-user")
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask,ctx.task_id)
        assert task.status == TaskStatus.awaiting_review and task.phase == "draft_ready",task.error
        assert task.requested_operation == "draft" and task.confirmation is None
        assert task.artifacts["valid"] and not task.rule_readiness["formal_ready"]
        assert_nine_complete(task)
    assert len(ctx.analysis_calls) == 1 and len(ctx.exported) == 1
    result = (await ctx.client.get(f"/api/tasks/{ctx.task_id}")).json()
    assert result["delivery_kind"] == "draft" and result["has_archive"] and result["has_docx"]
    assert len(result["artifacts"]) == 9 and result["status"] != "done"


@pytest.mark.asyncio
async def test_required_missing_and_unresolved_issues_allow_draft_but_not_final_confirmation(draft_context):
    ctx = draft_context
    await create_review(ctx,verified_required=True)
    task = await make_draft(ctx)
    assert_nine_complete(task)
    assert task.issues == ctx.issues and not (task.fields or {}).get("_issue_decisions")
    assert not (task.fields or {}).get("_review_decisions")
    # Simulate a server-verified required rule (current bundled references are
    # intentionally unverified); final review must still retain this draft.
    async with ctx.sessions() as db:
        saved=await db.get(ArchiveTask,ctx.task_id)
        catalog=copy.deepcopy(saved.catalog_status)
        next(item for item in catalog if not item["found"]).update(requirement="required",legal_requirement_verified=True)
        saved.catalog_status=catalog
        await db.commit()
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/assemble",json={
        "confirmation":True,"confirmed_revision":3,"skipped":[]})
    assert response.status_code == 409
    async with ctx.sessions() as db:
        assert (await db.get(ArchiveTask,ctx.task_id)).confirmation is None
    # Failed formal confirmation must not revoke the usable draft just delivered.
    assert (await ctx.client.get(f"/api/tasks/{ctx.task_id}/download/archive")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary",["peer","cross_org","revision","new_source","bytes","stage","snapshot_fields","snapshot_version"])
async def test_draft_endpoint_checks_acl_revision_sources_and_snapshot(draft_context,monkeypatch,boundary):
    ctx = draft_context
    await create_review(ctx)
    started = []
    def capture(task_id,coro): started.append(task_id); coro.close()
    monkeypatch.setattr(tasks.task_manager,"start",capture)
    body,headers = {"expected_revision":3},{}
    if boundary == "peer": headers={"X-Test-User":"peer"}
    elif boundary == "cross_org": headers={"X-Test-Role":"admin","X-Test-Org":"org-b"}
    elif boundary == "revision": body["expected_revision"]=2
    elif boundary == "new_source": await upload(ctx,name="未分析虚构补件.pdf")
    elif boundary == "bytes":
        path=Path(ctx.files[0].abs_path); path.write_bytes(path.read_bytes()+b"changed")
    elif boundary == "stage":
        async with ctx.sessions() as db:
            (await db.get(Case,"case-a")).stage="execution"; await db.commit()
    else:
        snapshot=load_snapshot_data(str(ctx.work))
        if boundary == "snapshot_fields": snapshot["fields"]["委托人"]="未提交虚构值"
        else: snapshot["workflow"]["source_version"]="older-version"
        _atomic_write(snapshot_path(str(ctx.work)),snapshot)
    response=await ctx.client.post(f"/api/tasks/{ctx.task_id}/draft",json=body,headers=headers)
    assert response.status_code == (404 if boundary in ("peer","cross_org") else 409),response.text
    assert started == [] and ctx.rendered == []


@pytest.mark.asyncio
@pytest.mark.parametrize("damage",["missing_word","changed_word","missing_zip","renderer_upgrade"])
async def test_draft_idempotency_damage_rebuild_and_download_are_truthful(draft_context,monkeypatch,damage):
    ctx=draft_context
    await create_review(ctx)
    original=await make_draft(ctx)
    started=[]
    def capture(task_id,coro): started.append(task_id); coro.close()
    monkeypatch.setattr(tasks.task_manager,"start",capture)
    url=f"/api/tasks/{ctx.task_id}"
    paths=[Path(item["path"]) for item in original.artifacts["artifacts"]]
    before={str(path):(path.stat().st_mtime_ns,hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths}
    for _ in range(2):
        repeated=await ctx.client.post(url+"/draft",json={"expected_revision":3})
        assert repeated.status_code == 200 and repeated.json()["delivery_kind"] == "draft"
    assert not started
    assert before == {str(path):(path.stat().st_mtime_ns,hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths}
    for suffix in ("download/archive","download/zip","docx/档案卷宗"):
        assert (await ctx.client.get(url+"/"+suffix)).status_code == 200
        assert (await ctx.client.get(url+"/"+suffix,headers={"X-Test-User":"peer"})).status_code == 404
    target=next(path for path in paths if path.suffix == (".zip" if damage == "missing_zip" else ".docx"))
    if damage == "renderer_upgrade":
        async with ctx.sessions() as db:
            task=await db.get(ArchiveTask,ctx.task_id)
            task.artifacts=dict(task.artifacts, renderer_version="previous-redrawn-forms")
            await db.commit()
        response=await ctx.client.post(url+"/draft",json={"expected_revision":3})
        assert response.status_code == 200 and response.json()["status"] == "running"
        assert started == [ctx.task_id]
        assert all(path.is_file() for path in paths)
        return
    if damage == "changed_word":
        data=bytearray(target.read_bytes()); data[-1]^=1; target.write_bytes(data)
    else: target.unlink()
    read=(await ctx.client.get(url)).json()
    assert read["phase"] == "artifacts_invalid" and read["status"] == "failed"
    assert read["artifacts"] == [] and not read["has_archive"] and not read["delivery_kind"]
    for suffix in ("download/archive","download/zip","docx/档案卷宗"):
        assert (await ctx.client.get(url+"/"+suffix)).status_code == 409
    response=await ctx.client.post(url+"/draft",json={"expected_revision":3})
    assert response.status_code == 200 and response.json()["status"] == "running"
    assert started == [ctx.task_id]
    rebuilt=await make_draft(ctx)
    assert rebuilt.revision == 3 and rebuilt.output_pdf != original.output_pdf
    assert ctx.analysis_calls == []
    assert_nine_complete(rebuilt)


@pytest.mark.asyncio
async def test_saved_field_edit_invalidates_draft_and_old_confirmation(draft_context):
    ctx=draft_context
    await create_review(ctx)
    original=await make_draft(ctx)
    content=Path(original.output_pdf).read_bytes()
    response=await ctx.client.patch(f"/api/tasks/{ctx.task_id}/fields",json={"fields":{"合同号":"人工虚构新合同"}})
    assert response.status_code == 200,response.text
    result=response.json()
    assert result["revision"] == 4 and not result["has_archive"] and result["artifacts"] == []
    assert result["delivery_kind"] == "" and Path(original.output_pdf).read_bytes() == content
    assert (await ctx.client.get(f"/api/tasks/{ctx.task_id}/download/archive")).status_code == 409
    assert (await ctx.client.post(f"/api/tasks/{ctx.task_id}/draft",json={"expected_revision":3})).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("reviewed", [False, True])
async def test_renderer_upgrade_preserves_saved_inputs_revision_and_previous_generation(draft_context, monkeypatch, reviewed):
    """Render repair must not refresh business drafts, even when they are old."""
    ctx = draft_context
    ctx.analysis.fields.update({"案情简介": "已保存的虚构摘要", "项目名称": "", "_form_drafts": {"version": 1}})
    await create_review(ctx)
    original = await make_draft(ctx)
    original_digest = fields_digest(original.fields, original.order_mode)
    snapshot_fields = copy.deepcopy(load_snapshot_data(str(ctx.work))["fields"])
    old_bytes = {entry["path"]: Path(entry["path"]).read_bytes() for entry in original.artifacts["artifacts"]}
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        task.artifacts = dict(task.artifacts, renderer_version="previous-original-renderer")
        if reviewed:
            task.status = TaskStatus.done
            task.phase = "completed"
            task.artifacts = dict(task.artifacts, delivery_kind="reviewed")
        await db.commit()
    started = []
    def capture(task_id, coroutine):
        started.append(task_id)
        coroutine.close()
    def forbidden_refresh(*args, **kwargs):
        raise AssertionError("Renderer-only rebuild must not rederive saved fields")
    monkeypatch.setattr(tasks.task_manager, "start", capture)
    monkeypatch.setattr(archive_service, "refresh_form_drafts", forbidden_refresh)
    response = await ctx.client.post(f"/api/tasks/{ctx.task_id}/draft", json={"expected_revision": original.revision})
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == original.revision
    assert fields_digest(response.json()["fields"], original.order_mode) == original_digest
    assert load_snapshot_data(str(ctx.work))["fields"] == snapshot_fields
    assert started == [ctx.task_id]
    rebuilt = await make_draft(ctx)
    assert rebuilt.revision == original.revision and rebuilt.source_version == original.source_version
    assert fields_digest(rebuilt.fields, rebuilt.order_mode) == original_digest
    assert load_snapshot_data(str(ctx.work))["fields"] == snapshot_fields
    assert rebuilt.artifacts["previous_generation"]["result_dir"] == original.artifacts["result_dir"]
    assert rebuilt.artifacts["result_dir"] != original.artifacts["result_dir"]
    assert all(Path(path).read_bytes() == content for path, content in old_bytes.items())
    assert ctx.analysis_calls == []
    assert_nine_complete(rebuilt)


@pytest.mark.asyncio
async def test_startup_recovery_rebuilds_draft_same_revision_without_model_or_confirmation(draft_context,monkeypatch):
    ctx=draft_context
    await create_review(ctx,status=TaskStatus.running)
    original=copy.deepcopy(ctx.analysis.fields)
    queued=[]
    monkeypatch.setattr(tasks.task_manager,"start",lambda task_id,coro:queued.append((task_id,coro)))
    await recovery.recover_interrupted_tasks()
    assert len(queued) == 1 and queued[0][0] == ctx.task_id
    await queued[0][1]
    async with ctx.sessions() as db:
        task=await db.get(ArchiveTask,ctx.task_id)
        assert task.status == TaskStatus.awaiting_review and task.phase == "draft_ready",task.error
        assert task.revision == 3 and task.confirmation is None
        assert {key:task.fields[key] for key in original} == original
        assert_nine_complete(task)
    assert not ctx.analysis_calls


@pytest.mark.asyncio
async def test_draft_after_field_save_does_not_rederive_committed_drafts(draft_context,monkeypatch):
    ctx=draft_context
    await create_review(ctx)
    saved=await ctx.client.patch(f"/api/tasks/{ctx.task_id}/fields",json={"fields":{"立卷人":"虚构流程验收员"}})
    assert saved.status_code==200,saved.text
    before=saved.json();snapshot=copy.deepcopy(load_snapshot_data(str(ctx.work)))
    assert before['fields']['_form_drafts']['fields']
    def forbidden(*args,**kwargs):
        raise AssertionError('Generating committed edited fields cannot refresh draft wording')
    started=[]
    monkeypatch.setattr(archive_service,'refresh_form_drafts',forbidden)
    monkeypatch.setattr(tasks.task_manager,'start',lambda task_id,coro:(started.append(task_id),coro.close()))
    response=await ctx.client.post(f"/api/tasks/{ctx.task_id}/draft",json={'expected_revision':before['revision']})
    assert response.status_code==200,response.text
    assert response.json()['fields']==before['fields'] and response.json()['revision']==before['revision']
    assert load_snapshot_data(str(ctx.work))==snapshot and started==[ctx.task_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch",["fields","version"])
async def test_direct_draft_recovery_cannot_publish_uncommitted_snapshot(draft_context,mismatch):
    ctx=draft_context
    await create_review(ctx,status=TaskStatus.running)
    data=load_snapshot_data(str(ctx.work))
    if mismatch == "fields": data["fields"]["委托人"]="只写入快照的虚构值"
    else: data["workflow"]["source_version"]="mismatching-version"
    _atomic_write(snapshot_path(str(ctx.work)),data)
    await archive_service.run_assemble(ctx.task_id,"case-a","org-a","test-user",draft=True)
    async with ctx.sessions() as db:
        task=await db.get(ArchiveTask,ctx.task_id)
        assert task.status == TaskStatus.failed and not task.output_pdf and not task.artifacts
    assert not ctx.rendered and not ctx.exported and not ctx.analysis_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_failure",[False,True])
async def test_legacy_first_draft_derives_forms_keeps_manual_values_and_rolls_back_safely(draft_context,monkeypatch,commit_failure):
    from sqlalchemy.ext.asyncio import AsyncSession
    ctx=draft_context
    manual={"委托人":"人工虚构委托人","案由":"虚构合同争议","法院文件清单":"人工保留的清单文字"}
    ctx.analysis.fields.update(manual)
    await create_review(ctx)
    async with ctx.sessions() as db:
        task=await db.get(ArchiveTask,ctx.task_id)
        task.manual_fields=manual
        await db.commit()
    original=load_snapshot_data(str(ctx.work))
    assert "_form_drafts" not in original["fields"]
    starts=[]
    def capture(task_id,coro): starts.append(task_id); coro.close()
    monkeypatch.setattr(tasks.task_manager,"start",capture)
    real_commit=AsyncSession.commit
    if commit_failure:
        async def fail(self): raise OSError("SYNTHETIC_PRIVATE_STORAGE_ERROR")
        monkeypatch.setattr(AsyncSession,"commit",fail)
        failed=await ctx.client.post(f"/api/tasks/{ctx.task_id}/draft",json={"expected_revision":3})
        assert failed.status_code == 503 and "SYNTHETIC_PRIVATE" not in failed.text
        assert starts == [] and load_snapshot_data(str(ctx.work)) == original
        async with ctx.sessions() as db:
            task=await db.get(ArchiveTask,ctx.task_id)
            assert task.revision == 3 and task.status == TaskStatus.awaiting_review
            assert task.fields == original["fields"] and task.manual_fields == manual
        monkeypatch.setattr(AsyncSession,"commit",real_commit)
    response=await ctx.client.post(f"/api/tasks/{ctx.task_id}/draft",json={"expected_revision":3})
    assert response.status_code == 200,response.text
    data=response.json()
    assert data["revision"] == 4 and data["status"] == "running"
    assert all(data["fields"][key] == value for key,value in manual.items())
    assert data["fields"]["_form_drafts"]["fields"]["案情简介"]["status"] == "generated"
    assert "人工虚构委托人" in data["fields"]["案情简介"]
    assert data["fields"]["_form_drafts"]["fields"]["法院文件清单"]["status"] == "human_modified"
    assert load_snapshot_data(str(ctx.work))["fields"] == data["fields"]
    assert starts == [ctx.task_id] and ctx.analysis_calls == []
