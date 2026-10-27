"""Whole-unit edits against synthetic documents; no OCR/model/browser calls."""
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import fitz
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_file_import_api import upload_context, upload
from tests.test_task_workflow import wire_storage, capture_start
from app.models import ArchiveTask, Case, CaseFile, TaskStatus
from app.routers import tasks
from app.services import document_classification as dc
from app.services.analysis_snapshot import load_analysis, save_snapshot, snapshot_path, task_work_dir
from app.services.task_sources import build_source_manifest, source_version
from app.services.task_workflow import analyze_with_parent


async def fixture_task(ctx, monkeypatch):
    import archive_pipeline as ap
    from pdf_doc_locator import DocumentUnit
    wire_storage(ctx, monkeypatch)
    with fitz.open() as document:
        for number in range(3):
            document.new_page().insert_text((72, 72), f"FICTIONAL PAGE {number}")
        content = document.tobytes()
    assert (await upload(ctx, name="虚构综合材料.pdf", content=content)).status_code == 200
    async with ctx.sessions() as db:
        files = list((await db.scalars(select(CaseFile))).all())
        manifest = build_source_manifest(files)
        analysis = ap.ArchiveAnalysis("civil", files[0].abs_path, {"委托人":"虚构甲", "合同号":"人工保留"}, {},
            [DocumentUnit(0, "poa", 0, 1, catalog_seq=4, source_path=files[0].abs_path, confidence=.4),
             DocumentUnit(1, "judgment", 2, 2, catalog_seq=14, source_path=files[0].abs_path)],
            set(), [], source_paths=[files[0].abs_path])
        analysis.low_confidence_items = [{"doc_id":0,"catalog_seq":4,"pages":[0,1]}]
        dc.refresh_catalog(analysis)
        from app.services.archive_service import _build_catalog_status
        from app.services.task_workflow import analysis_issues, issue
        independent = issue("ocr", "虚构OCR复核", detail={"page":3})
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.awaiting_review,
            revision=1, fields=analysis.fields, manual_fields={"合同号":"人工保留"}, source_manifest=manifest,
            source_version=source_version(manifest, "civil"), catalog_status=_build_catalog_status(analysis),
            issues=analysis_issues(analysis, manifest)+[independent], checkpoint="analyzed", phase="needs_input")
        db.add(task)
        await db.commit()
        work = task_work_dir("org-a", "case-a", task.id)
        save_snapshot(work, analysis, base_name="虚构测试", metadata={"source_version":task.source_version,"revision":1})
    return task.id, work, manifest


async def edit(ctx, task_id, key, revision=1, **kwargs):
    return await ctx.client.patch(f"/api/tasks/{task_id}/documents/{key}/classification", json={
        "expected_revision":revision,"doc_type":"contract","catalog_seq":3,"reason":"已逐页核对虚构合同",**kwargs})


@pytest.mark.asyncio
async def test_classification_syncs_full_snapshot_after_field_save(upload_context, monkeypatch):
    ctx = upload_context
    task_id, work, manifest = await fixture_task(ctx, monkeypatch)
    path = Path(snapshot_path(work))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["workflow"].update(source_manifest=manifest, manual_fields={"合同号":"人工保留"},
                            field_save_origin={"target": {"revision": 1}})
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    key = (await ctx.client.get(f"/api/tasks/{task_id}/documents")).json()["documents"][0]["unit_key"]
    saved = await edit(ctx, task_id, key)
    assert saved.status_code == 200, saved.text
    from app.services.field_snapshot_state import reconcile_field_snapshot
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, task_id)
        assert reconcile_field_snapshot(task, work) is False
        analysis, snapshot = load_analysis(work)
        assert snapshot["workflow"]["manual_fields"] == task.manual_fields
        assert snapshot["workflow"]["field_save_origin"] is None
        assert analysis.fields["合同号"] == "人工保留"
    # A snapshot from the older classification saver can be repaired by an
    # explicit repeat save; never suppress it as an already-completed request.
    data = json.loads(path.read_text(encoding="utf-8"))
    data["workflow"]["manual_fields"] = {"合同号":"人工保留"}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    repaired = await edit(ctx, task_id, key, revision=2)
    assert repaired.status_code == 200 and repaired.json()["revision"] == 3
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, task_id)
        assert reconcile_field_snapshot(task, work) is False


@pytest.mark.asyncio
async def test_counsel_unknown_can_be_explicitly_reviewed_into_existing_work_record(upload_context, monkeypatch):
    ctx = upload_context
    task_id, work, manifest = await fixture_task(ctx, monkeypatch)
    analysis, _ = load_analysis(work)
    analysis.case_type = "counsel"
    for unit in analysis.doc_spans:
        unit.doc_type, unit.catalog_seq = "unknown", 5
    dc.refresh_catalog(analysis)
    from app.services.archive_service import _build_catalog_status
    from app.services.task_workflow import analysis_issues
    async with ctx.sessions() as db:
        case = await db.get(Case, "case-a")
        case.case_type = "counsel"
        task = await db.get(ArchiveTask, task_id)
        task.source_version = source_version(manifest, "counsel")
        task.catalog_status = _build_catalog_status(analysis)
        task.issues = analysis_issues(analysis, manifest)
        await db.commit()
        save_snapshot(work, analysis, base_name="虚构顾问材料", metadata={"source_version":task.source_version,"revision":1})
    source_before = Path(manifest[0]["path"]).read_bytes()
    response = await ctx.client.get(f"/api/tasks/{task_id}/documents")
    assert response.status_code == 200
    option = next(o for o in response.json()["options"] if o["catalog_seq"] == 5)
    assert option["doc_type"] == "unknown"
    key = response.json()["documents"][0]["unit_key"]
    assert (await edit(ctx, task_id, key, doc_type="unknown", catalog_seq=5, reason=" ")).status_code == 400
    assert (await edit(ctx, task_id, key, doc_type="unknown", catalog_seq=5, start_page=1)).status_code == 422
    saved = await edit(ctx, task_id, key, doc_type="unknown", catalog_seq=5, reason="已核对为顾问事务办理记录")
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    row = saved.json()["documents"][0]
    assert row["catalog_seq"] == 5 and row["classification_origin"] == "human"
    assert (row["page_start"], row["page_end"]) == (1, 2)
    assert Path(manifest[0]["path"]).read_bytes() == source_before
    effective, _ = load_analysis(work)
    assert [(u.start_page, u.end_page) for u in effective.doc_spans] == [(0, 1), (2, 2)]
    assert effective.doc_spans[0].manual_catalog_seq == 5
    assert not any(i["kind"] == "classification" and i["detail"].get("doc_id") == 0 for i in saved.json()["task"]["issues"])
    stale = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json={"confirmed_revision":1,"confirmation":True})
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_edit_preserves_evidence_rejects_old_confirmation_and_is_idempotent(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    task_id, work, manifest = await fixture_task(ctx, monkeypatch)
    before = Path(manifest[0]["path"]).read_bytes()
    rows = (await ctx.client.get(f"/api/tasks/{task_id}/documents")).json()
    assert rows["editable"] and len(rows["documents"]) == 2
    assert rows["documents"][0]["page_start"] == 1 and rows["documents"][0]["page_end"] == 2
    assert "source_path" not in rows["documents"][0]
    key = rows["documents"][0]["unit_key"]
    response = await edit(ctx, task_id, key)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["revision"] == 2
    assert result["documents"][0]["classification_origin"] == "human"
    assert result["task"]["fields"]["合同号"] == "人工保留"
    assert [i["kind"] for i in result["task"]["issues"] if i["kind"] != "form_draft"] == ["ocr"]
    assert all(not i["blocking"] for i in result["task"]["issues"] if i["kind"] == "form_draft")
    found = {i["seq"] for i in result["task"]["catalog_status"] if i["found"]}
    assert 3 in found and 4 not in found and {0,1,16,17,18}.issubset(found)
    assert Path(manifest[0]["path"]).read_bytes() == before
    analysis, _ = load_analysis(work)
    assert [(u.start_page,u.end_page) for u in analysis.doc_spans] == [(0,1),(2,2)]
    assert analysis.doc_spans[0].manual_catalog_seq == 3
    snapshot = Path(snapshot_path(work))
    saved = (snapshot.read_bytes(), snapshot.stat().st_mtime_ns)
    duplicate = await edit(ctx, task_id, key)
    assert duplicate.status_code == 200 and duplicate.json()["revision"] == 2
    assert (snapshot.read_bytes(), snapshot.stat().st_mtime_ns) == saved
    assert (await edit(ctx, task_id, key, revision=1, doc_type="evidence",catalog_seq=7)).status_code == 409
    stale = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json={"confirmed_revision":1,"confirmation":True})
    assert stale.status_code == 409
    assert capture_start == []


@pytest.mark.asyncio
async def test_acl_invalid_inputs_running_and_source_changes(upload_context, monkeypatch):
    ctx=upload_context
    task_id, work, _ = await fixture_task(ctx, monkeypatch)
    url=f"/api/tasks/{task_id}/documents"
    key=(await ctx.client.get(url)).json()["documents"][0]["unit_key"]
    for headers in ({"X-Test-User":"peer"},{"X-Test-Org":"org-b","X-Test-Role":"admin"}):
        assert (await ctx.client.get(url,headers=headers)).status_code == 404
        assert (await ctx.client.patch(url+f"/{key}/classification",headers=headers,json={"expected_revision":1,"doc_type":"contract","catalog_seq":3,"reason":"虚构"})).status_code == 404
    assert (await ctx.client.get(url,headers={"X-Test-User":"admin","X-Test-Role":"admin"})).status_code == 200
    assert (await edit(ctx,task_id,key,catalog_seq=0)).status_code == 409
    assert (await edit(ctx,task_id,key,start_page=2)).status_code == 422
    assert (await edit(ctx,task_id,key,reason=" ")).status_code == 400
    assert (await edit(ctx,task_id,"not-a-unit")).status_code == 409
    async with ctx.sessions() as db:
        task=await db.get(ArchiveTask,task_id); task.status=TaskStatus.running; await db.commit()
    assert not (await ctx.client.get(url)).json()["editable"]
    assert (await edit(ctx,task_id,key)).status_code == 409
    async with ctx.sessions() as db:
        task=await db.get(ArchiveTask,task_id); task.status=TaskStatus.awaiting_review; await db.commit()
    await upload(ctx,name="新增虚构材料.pdf")
    assert (await ctx.client.get(url)).json()["source_changed"]
    assert (await edit(ctx,task_id,key)).status_code == 409


@pytest.mark.asyncio
async def test_commit_interruption_blocks_confirmation_and_allows_safe_retry(upload_context, monkeypatch):
    ctx=upload_context
    task_id,work,_=await fixture_task(ctx,monkeypatch)
    key=(await ctx.client.get(f"/api/tasks/{task_id}/documents")).json()["documents"][0]["unit_key"]
    real_commit=AsyncSession.commit
    async def fail_commit(self):
        raise RuntimeError("synthetic commit failure")
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession,"commit",fail_commit)
        assert (await edit(ctx,task_id,key)).status_code == 409
    assert AsyncSession.commit is real_commit
    # Snapshot is ahead; DB is the authority. The edit screen projects old data.
    listed=(await ctx.client.get(f"/api/tasks/{task_id}/documents")).json()
    assert listed["revision"]==1 and listed["documents"][0]["catalog_seq"]==4 and listed["editable"]
    assemble=await ctx.client.post(f"/api/tasks/{task_id}/assemble",json={"confirmation":True,"confirmed_revision":1})
    assert assemble.status_code==409 and "快照" in assemble.json()["detail"]
    field_edit=await ctx.client.patch(f"/api/tasks/{task_id}/fields",json={"fields":{"委托人":"虚构新值"}})
    assert field_edit.status_code==409
    from app.services.case_assistant import load_context, SourceUnavailable
    async with ctx.sessions() as db:
        authoritative=await db.get(ArchiveTask,task_id)
        files=list((await db.scalars(select(CaseFile))).all())
        with pytest.raises(SourceUnavailable,match="分类草稿"):
            load_context(authoritative,files,"org-a")
    retry=await edit(ctx,task_id,key)
    assert retry.status_code==200 and retry.json()["revision"]==2
    async with ctx.sessions() as db:
        task=await db.get(ArchiveTask,task_id)
        dc.verify_classification(task,load_analysis(work)[0])


@pytest.mark.asyncio
async def test_interruption_does_not_resolve_an_uncommitted_other_unit_issue(upload_context,monkeypatch):
    ctx=upload_context
    task_id,work,_=await fixture_task(ctx,monkeypatch)
    rows=(await ctx.client.get(f"/api/tasks/{task_id}/documents")).json()["documents"]
    async def failed(self): raise RuntimeError("synthetic commit failure")
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession,"commit",failed)
        assert (await edit(ctx,task_id,rows[0]["unit_key"])).status_code==409
    edited=await edit(ctx,task_id,rows[1]["unit_key"],doc_type="evidence",catalog_seq=7)
    assert edited.status_code==200
    issues=edited.json()["task"]["issues"]
    assert any(i["kind"]=="classification" and i["detail"]["doc_id"]==0 for i in issues)
    assert edited.json()["documents"][0]["catalog_seq"]==4


@pytest.mark.asyncio
async def test_unit_tampering_is_bound_to_confirmation_and_metadata_is_not_client_editable(upload_context,monkeypatch):
    ctx=upload_context
    task_id,work,_=await fixture_task(ctx,monkeypatch)
    key=(await ctx.client.get(f"/api/tasks/{task_id}/documents")).json()["documents"][0]["unit_key"]
    assert (await edit(ctx,task_id,key)).status_code==200
    for field in (dc.DECISIONS,dc.DIGEST,dc.REVIEW):
        assert (await ctx.client.patch(f"/api/tasks/{task_id}/fields",json={"fields":{field:{}}})).status_code==400
    path=Path(snapshot_path(work)); data=json.loads(path.read_text(encoding="utf-8"))
    data["doc_spans"][0]["catalog_seq"]=7
    path.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
    response=await ctx.client.post(f"/api/tasks/{task_id}/assemble",json={"confirmation":True,"confirmed_revision":2})
    assert response.status_code==409 and "快照" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reclassified_volume_preserves_each_source_page_once_and_navigation(upload_context,monkeypatch):
    import archive_catalog as ac
    import catalog_toc
    from pdf_archive_merger import build_full_archive, _catalog_item_matches_unit
    from app.services.analysis_snapshot import SYSTEM_TEMPLATE_NAMES
    ctx=upload_context
    task_id,work,manifest=await fixture_task(ctx,monkeypatch)
    key=(await ctx.client.get(f"/api/tasks/{task_id}/documents")).json()["documents"][0]["unit_key"]
    assert (await edit(ctx,task_id,key)).status_code==200
    analysis,_=load_analysis(work)
    generated={}
    for index,name in enumerate(SYSTEM_TEMPLATE_NAMES):
        path=ctx.root/f"fictional-form-{index}.pdf"
        with fitz.open() as document:
            document.new_page().insert_text((72,72),f"FICTIONAL SYSTEM FORM {index}")
            document.save(path)
        generated[name]=str(path)
    monkeypatch.setattr(catalog_toc,"catalog_toc_to_pdf",lambda *a,**k:False)
    before=Path(manifest[0]["path"]).read_bytes()
    output=ctx.root/"fictional-reclassified-volume.pdf"
    result=build_full_archive(case_type="civil",original_pdf=analysis.original_pdf,
        generated_templates=generated,doc_spans=analysis.doc_spans,supplements={},skipped=[],
        output_pdf=str(output),docx_to_pdf_func=lambda *a,**k:(_ for _ in ()).throw(AssertionError("No Word conversion")),log=lambda _:None)
    assert result.success and result.original_pages_included==3
    assert Path(manifest[0]["path"]).read_bytes()==before
    with fitz.open(output) as document:
        text="\n".join(page.get_text() for page in document)
        assert all(text.count(f"FICTIONAL PAGE {i}")==1 for i in range(3))
        assert len(document)==9
        assert document.get_toc() and any(page.get_links() for page in document)
        assert all(page.get_label()==str(i+1) and re.search(r"GD\s+"+str(i+1)+r"\s*/\s*"+str(len(document))+r"\s*$",page.get_text()) for i,page in enumerate(document))
    # Explicit human destination must win even for an old inconsistent doc_type.
    unit=copy.deepcopy(analysis.doc_spans[0]);unit.doc_type="poa"
    catalog=ac.get_catalog("civil")
    assert not _catalog_item_matches_unit(next(item for item in catalog if item.seq==4),unit,ac.MANUAL_KEY_DOC_TYPES)


@pytest.mark.asyncio
async def test_reclassifying_stale_decision_uses_current_auto_baseline(upload_context,monkeypatch):
    ctx=upload_context
    task_id,work,manifest=await fixture_task(ctx,monkeypatch)
    key=(await ctx.client.get(f"/api/tasks/{task_id}/documents")).json()["documents"][0]["unit_key"]
    assert (await edit(ctx,task_id,key)).status_code==200
    async with ctx.sessions() as db:
        prior=await db.get(ArchiveTask,task_id)
    analysis,_=load_analysis(work)
    # Same bytes and boundaries; whole-file input classification changed.
    current=copy.deepcopy(manifest);current[0]["doc_type"]="evidence"
    analysis.doc_spans[0].doc_type="evidence";analysis.doc_spans[0].catalog_seq=7
    analysis.doc_spans[0].manual_catalog_seq=None
    records=prior.fields[dc.DECISIONS]
    dc.apply_decisions(analysis,current,records)
    assert analysis.fields[dc.REVIEW] and analysis.doc_spans[0].doc_type=="evidence"
    task=SimpleNamespace(fields=copy.deepcopy(analysis.fields),source_manifest=current,revision=1)
    body=SimpleNamespace(doc_type="contract",catalog_seq=3,reason="重新核对本轮分析")
    fresh=dc.change_classification(task,analysis,{},key,body,"synthetic-actor")
    assert fresh[key]["original_doc_type"]=="evidence"
    dc.apply_decisions(analysis,current,fresh,stage="execution")
    assert analysis.doc_spans[0].manual_catalog_seq is None
    assert analysis.doc_spans[0].doc_type=="evidence" and analysis.doc_spans[0].catalog_seq==7


@pytest.mark.asyncio
async def test_snapshot_write_failure_preserves_database_and_can_retry(upload_context,monkeypatch):
    from app.services import analysis_snapshot
    ctx=upload_context
    task_id,work,_=await fixture_task(ctx,monkeypatch)
    path=Path(snapshot_path(work));before=path.read_bytes()
    key=(await ctx.client.get(f"/api/tasks/{task_id}/documents")).json()["documents"][0]["unit_key"]
    def fail(*a,**k): raise OSError("synthetic storage unavailable")
    with monkeypatch.context() as patch:
        patch.setattr(analysis_snapshot,"save_snapshot",fail)
        assert (await edit(ctx,task_id,key)).status_code==409
    assert path.read_bytes()==before
    assert (await ctx.client.get(f"/api/tasks/{task_id}/documents")).json()["revision"]==1
    assert (await edit(ctx,task_id,key)).status_code==200


@pytest.mark.asyncio
async def test_same_choice_reconfirms_stale_record_instead_of_noop(upload_context,monkeypatch):
    from app.services.archive_service import _build_catalog_status
    from app.services.task_workflow import analysis_issues
    ctx=upload_context
    parent_id,work,manifest=await fixture_task(ctx,monkeypatch)
    key=(await ctx.client.get(f"/api/tasks/{parent_id}/documents")).json()["documents"][0]["unit_key"]
    assert (await edit(ctx,parent_id,key)).status_code==200
    analysis,_=load_analysis(work)
    async with ctx.sessions() as db:
        parent=await db.get(ArchiveTask,parent_id)
        case=await db.get(Case,"case-a");case.stage="execution"
        dc.apply_decisions(analysis,manifest,parent.fields[dc.DECISIONS],stage="execution")
        assert analysis.fields[dc.REVIEW] and analysis.doc_spans[0].manual_catalog_seq is None
        child=ArchiveTask(case_id="case-a",created_by="test-user",parent_task_id=parent_id,
            status=TaskStatus.awaiting_review,revision=1,fields=analysis.fields,manual_fields=parent.manual_fields,
            source_manifest=manifest,source_version=source_version(manifest,"civil","execution"),
            catalog_status=_build_catalog_status(analysis,stage="execution"),issues=analysis_issues(analysis,manifest))
        db.add(child);await db.commit()
        child_work=task_work_dir("org-a","case-a",child.id)
        save_snapshot(child_work,analysis,base_name="虚构阶段变化",metadata={"source_version":child.source_version,"case_stage":"execution"})
    response=await edit(ctx,child.id,key)  # identical type, destination and reason
    assert response.status_code==200 and response.json()["revision"]==2
    assert response.json()["documents"][0]["classification_origin"]=="human"
    assert response.json()["documents"][0]["catalog_seq"]==3
    assert not response.json()["task"]["fields"][dc.REVIEW]


@pytest.mark.asyncio
@pytest.mark.parametrize("change",["addition","stage","bytes","boundary","case_type"])
async def test_manual_classification_inheritance_revalidates_source_identity(upload_context,monkeypatch,change):
    import archive_pipeline as ap
    from pdf_doc_locator import DocumentUnit
    from app.services import task_workflow as workflow
    ctx=upload_context
    task_id,work,manifest=await fixture_task(ctx,monkeypatch)
    key=(await ctx.client.get(f"/api/tasks/{task_id}/documents")).json()["documents"][0]["unit_key"]
    assert (await edit(ctx,task_id,key)).status_code==200
    async with ctx.sessions() as db:
        parent=await db.get(ArchiveTask,task_id)
    prior,_=load_analysis(work)
    current=copy.deepcopy(manifest)
    new={"file_id":"new","filename":"虚构新增.pdf","path":str(ctx.root/"new.pdf"),"sha256":"new-hash","pages":1,"doc_type":"default"}
    current.append(new)
    if change=="bytes": current[0]["sha256"]="changed-hash"
    kind="admin" if change=="case_type" else "civil"
    calls=[]
    def analyze(case_type,*,sources,config,log):
        calls.append([s.path for s in sources])
        if len(sources)==1:
            result=ap.ArchiveAnalysis(kind,new["path"],{}, {},[DocumentUnit(0,"evidence",0,0,catalog_seq=7,source_path=new["path"])],set(),[],source_paths=[new["path"]])
        else:
            result=copy.deepcopy(prior); result.case_type=kind
            result.fields={"委托人":"虚构甲"}; result.doc_spans[0].manual_catalog_seq=None
            result.doc_spans[0].doc_type="poa";result.doc_spans[0].catalog_seq=4
        return result
    if change=="boundary":
        current[0]["doc_type"]="evidence"  # force fresh segmentation
        original=analyze
        def analyze(*args,**kwargs):
            result=original(*args,**kwargs);result.doc_spans[0].end_page=0;return result
    monkeypatch.setattr(workflow,"snapshot_exists",lambda *_:True)
    monkeypatch.setattr(workflow,"load_analysis",lambda *_:(copy.deepcopy(prior),{}))
    files=[SimpleNamespace(id=r["file_id"],abs_path=r["path"],doc_type=r["doc_type"]) for r in current]
    engine=SimpleNamespace(analyze_archive=analyze,compute_found_seqs=ap.compute_found_seqs,compute_missing_items=ap.compute_missing_items)
    result,manual,_=analyze_with_parent(engine,SimpleNamespace(source_manifest=current),parent,files,
        {"workflow_case_type":kind,"workflow_stage":"execution" if change=="stage" else ""},"org-a",lambda _:None)
    assert manual["合同号"]==result.fields["合同号"]=="人工保留"
    if change=="addition":
        assert calls==[[new["path"]]]
        assert result.doc_spans[0].manual_catalog_seq==3 and not result.fields[dc.REVIEW]
    else:
        assert result.doc_spans[0].manual_catalog_seq is None
        assert result.fields[dc.REVIEW]
