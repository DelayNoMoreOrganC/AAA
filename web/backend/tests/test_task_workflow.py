"""Synthetic reliability regressions. Model calls are stubs, not AI quality claims."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_file_import_api import upload_context, upload, isolate_assembly
from app import config
from app.database import migrate_task_columns, migrate_case_columns
from app.models import ArchiveTask, CaseFile, TaskStatus, User, Role
from app.routers import tasks
from app.services import archive_service, recovery
from app.services.analysis_snapshot import save_snapshot, task_work_dir
from app.services.task_sources import build_source_manifest, source_version, fields_digest
from app.services.task_workflow import analyze_with_parent, issue, analysis_issues, unresolved_issues


@pytest.fixture
def capture_start(monkeypatch):
    launched = []
    def start(task_id, coroutine):
        launched.append(task_id)
        coroutine.close()
    monkeypatch.setattr(tasks.task_manager, "start", start)
    async def ready(*args, **kwargs):
        return {"ready": True, "issues": []}
    monkeypatch.setattr(tasks, "check_readiness", ready)
    return launched


def wire_storage(ctx, monkeypatch):
    monkeypatch.setattr(config, "ORGS_DIR", ctx.root)
    monkeypatch.setattr(archive_service, "AsyncSessionLocal", ctx.sessions)
    monkeypatch.setattr(recovery, "AsyncSessionLocal", ctx.sessions)


def fixture_analysis(path, fields=None):
    import archive_pipeline as ap
    from pdf_doc_locator import DocumentUnit
    return ap.ArchiveAnalysis("civil", str(path), fields or {"委托人": "虚构甲"}, {},
                              [DocumentUnit(0, "evidence", 0, 0, catalog_seq=7, source_path=str(path))],
                              {0, 1, 7, 16, 17, 18}, [], source_paths=[str(path)])


@pytest.mark.asyncio
async def test_additive_migration_preserves_existing_tasks_and_is_repeatable(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "old.db"))
    async with engine.begin() as connection:
        await connection.exec_driver_sql("CREATE TABLE tasks (id INTEGER PRIMARY KEY, case_id VARCHAR(32), status VARCHAR(30))")
        await connection.exec_driver_sql("INSERT INTO tasks VALUES (1, 'case-a', 'done')")
        await migrate_task_columns(connection)
        await migrate_task_columns(connection)
        row = (await connection.exec_driver_sql("SELECT status, revision, source_manifest, execution_profile, previous_artifacts FROM tasks WHERE id=1")).one()
        assert row == ("done", 1, None, None, None)
        await connection.exec_driver_sql("CREATE TABLE cases (id VARCHAR(32) PRIMARY KEY, case_type VARCHAR(50))")
        await connection.exec_driver_sql("INSERT INTO cases VALUES ('old-case', 'civil')")
        await migrate_case_columns(connection)
        await migrate_case_columns(connection)
        assert (await connection.exec_driver_sql("SELECT case_type, stage FROM cases WHERE id='old-case'")).one() == ("civil", "")
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("case_type,stage", [("civil", "execution"), ("criminal", "investigation"),
                                           ("admin", "first_instance"), ("nonlit", "delivery"),
                                           ("counsel", "renewal"), ("arbitration", "arbitration"),
                                           ("consultation", "consultation")])
async def test_case_type_and_stage_are_validated_and_persisted(upload_context, case_type, stage):
    ctx = upload_context
    response = await ctx.client.post("/api/cases", json={"title": "虚构阶段测试", "case_type": case_type, "stage": stage})
    assert response.status_code == 201
    assert response.json()["stage"] == stage
    detail = (await ctx.client.get("/api/cases/" + response.json()["id"])).json()
    assert detail["case_type"] == case_type
    assert detail["stage"] == stage
    cases = (await ctx.client.get("/api/cases")).json()
    assert next(case for case in cases if case["id"] == detail["id"])["stage"] == stage


@pytest.mark.asyncio
@pytest.mark.parametrize("case_type", ["arbitration", "consultation"])
async def test_missing_original_catalog_stops_before_provider_preflight(upload_context, monkeypatch, case_type):
    ctx = upload_context
    response = await ctx.client.post("/api/cases", json={"title":"虚构未接入原目录", "case_type":case_type})
    assert response.status_code == 201
    async def forbidden(*args, **kwargs):
        raise AssertionError("No provider profile/readiness call before catalog availability")
    monkeypatch.setattr(tasks,"make_profile",forbidden)
    monkeypatch.setattr(tasks,"check_readiness",forbidden)
    result = await ctx.client.post(f"/api/cases/{response.json()['id']}/generate", json={})
    assert result.status_code == 409 and "原目录" in result.json()["detail"]
    async with ctx.sessions() as db:
        assert not (await db.scalars(select(ArchiveTask))).all()


@pytest.mark.asyncio
async def test_unknown_case_type_or_incompatible_stage_is_rejected(upload_context):
    client = upload_context.client
    for body in [{"case_type": "invented"}, {"case_type": "civil", "stage": "investigation"}, {"case_type": "consultation", "stage": "arbitration"}]:
        assert (await client.post("/api/cases", json={"title": "虚构非法类型测试", **body})).status_code == 422
    assert (await client.get("/api/cases/meta/doc-types?case_type=invented")).status_code == 422


def test_processing_stage_is_part_of_input_identity():
    manifest = [{"file_id": "fictional", "sha256": "fixture-hash", "pages": 1, "doc_type": "default"}]
    assert source_version(manifest, "civil", "") == source_version(manifest, "civil")
    assert source_version(manifest, "civil", "first_instance") != source_version(manifest, "civil", "execution")


@pytest.mark.parametrize("case_type", ["civil", "criminal", "admin", "nonlit", "counsel", "arbitration", "consultation"])
def test_initial_empty_business_fields_always_need_review(case_type):
    analysis = fixture_analysis("synthetic.pdf")
    analysis.case_type = case_type
    analysis.fields = {"案件类别": case_type, "案件或项目名称": "系统生成标题",
                       "_agent_summary": {"accepted_fact_count": 0}}
    issues = analysis_issues(analysis)
    empty = [entry for entry in issues if entry["kind"] == "empty_fields"]
    assert len(empty) == 1 and empty[0]["blocking"] is True
    assert unresolved_issues(issues, analysis.fields) == empty
    analysis.fields["合同号"] = "人工核对-001"
    assert not any(entry["kind"] == "empty_fields" for entry in analysis_issues(analysis))


@pytest.mark.parametrize("method,has_evidence,expected_empty", [
    ("derived_form_draft", True, True),
    ("visual_agent_local_evidence", False, True),
    ("visual_agent_local_evidence", True, False),
    ("local_agent", True, False),
    ("human", False, False),
])
def test_project_name_only_counts_when_sourced_or_human(method, has_evidence, expected_empty):
    name = "虚构采购审查项目"
    ref = {"method": method, "value": name}
    if has_evidence:
        ref.update(source_path="synthetic.pdf", page=1, quote="项目名称：" + name)
    analysis = fixture_analysis("synthetic.pdf")
    analysis.fields = {"案件或项目名称": name, "_provenance": {"案件或项目名称": [ref]}}
    assert any(entry["kind"] == "empty_fields" for entry in analysis_issues(analysis)) is expected_empty


@pytest.mark.parametrize("refused", [False, True])
def test_evidence_only_increment_uses_real_agent_empty_result_and_preserves_manual(tmp_path, monkeypatch, refused):
    import archive_pipeline as ap
    import workstation_agent as agent
    from app.services import task_workflow as workflow
    old_path, new_path = str(tmp_path / "old.pdf"), str(tmp_path / "evidence.pdf")
    old = {"file_id":"old", "path":old_path, "sha256":"old", "doc_type":"default", "pages":1, "filename":"old.pdf"}
    new = {"file_id":"new", "path":new_path, "sha256":"new", "doc_type":"evidence", "pages":1, "filename":"evidence.pdf"}
    parent = SimpleNamespace(id=1, case_id="fixture", source_manifest=[old], manual_fields={"合同号":"人工保留-001"})
    task = SimpleNamespace(source_manifest=[old,new])
    previous = fixture_analysis(old_path, {"合同号":"人工保留-001", "委托人":"虚构委托人"})
    previous.fields["_agent_summary"] = {"pages_checked":1, "source_pages_checked":1, "accepted_fact_count":2,
                                          "rejected_fact_count":0, "empty_fact_pages":[], "local":True}
    monkeypatch.setattr(workflow, "snapshot_exists", lambda *_: True)
    monkeypatch.setattr(workflow, "load_analysis", lambda *_: (previous, {}))
    facts = [{"field":"承办律师", "value":"某记录", "page_id":"f1p1c1", "quote":"证据名称：某记录"}] if refused else []
    responses = iter([{"tool":"read_pages", "page_ids":["f1p1c1"]}, {"tool":"record_fields", "facts":facts}])
    monkeypatch.setattr(agent, "request_tool", lambda *_: next(responses))
    calls = []
    def analyze(case_type, *, sources, config, log):
        calls.append([source.path for source in sources])
        raw, metadata = agent.extract_with_agent({new_path:["证据材料清单\n证据名称：某记录"]}, config, log)
        assert raw == {}
        result = fixture_analysis(new_path)
        result.fields = dict(raw, **metadata)
        result.fields["_ocr_review"] = [{"source_path":new_path, "page":1, "reason":"虚构低质照片需查看"}]
        return result
    engine = SimpleNamespace(analyze_archive=analyze, compute_found_seqs=ap.compute_found_seqs, compute_missing_items=ap.compute_missing_items)
    files = [SimpleNamespace(id=row["file_id"], abs_path=row["path"], doc_type=row["doc_type"]) for row in [old,new]]
    output, manual, conflicts = analyze_with_parent(engine, task, parent, files, {"workflow_case_type":"civil"}, "fixture-org", lambda _:None)
    assert calls == [[new_path]]
    assert output.fields["合同号"] == manual["合同号"] == "人工保留-001"
    assert output.source_paths == [old_path,new_path]
    assert [(unit.source_path,unit.start_page,unit.end_page) for unit in output.doc_spans] == [(old_path,0,0),(new_path,0,0)]
    assert not conflicts
    assert output.fields["_agent_summary"]["accepted_fact_count"] == 2
    assert output.fields["_agent_summary"]["this_run_accepted_fact_count"] == 0
    assert output.fields["_agent_summary"]["empty_fact_pages"] == [{"source_path":new_path,"page":1}]
    issues = analysis_issues(output, [old,new])
    assert not any(entry["kind"] == "empty_fields" for entry in issues)
    assert any(entry["kind"] == "ocr" and entry["detail"]["file_id"] == "new" for entry in issues)
    assert any(entry["kind"] == "fact_review" for entry in issues) is refused
    if refused:
        review = next(entry for entry in issues if entry["kind"] == "fact_review")
        assert review["blocking"] is False
        assert review["detail"]["candidates"][0]["file_id"] == "new"
        assert review["detail"]["candidates"][0]["page"] == 1
        assert review["detail"]["pages"] == [{"file_id":"new", "filename":"evidence.pdf", "page":1,
                                                "fields":["承办律师"], "candidate_count":1}]
        assert review not in unresolved_issues(issues, output.fields)
        assert "某记录" not in str(review)


@pytest.mark.asyncio
async def test_generate_is_idempotent_and_freezes_input_bytes_and_classification(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    result = await upload(ctx)
    request = {"idempotency_key": "request-0001"}
    first = await ctx.client.post("/api/cases/case-a/generate", json=request)
    second = await ctx.client.post("/api/cases/case-a/generate", json=request)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert len(capture_start) == 1
    async with ctx.sessions() as session:
        task = await session.get(ArchiveTask, first.json()["id"])
        assert task.source_manifest[0]["sha256"]
        assert task.source_manifest[0]["doc_type"] == "default"
        file = await session.get(CaseFile, result.json()["id"])
        file.doc_type = "evidence"
        await session.commit()
    changed = await ctx.client.get("/api/tasks/" + str(first.json()["id"]))
    assert changed.json()["source_changed"] is True
    stale_request = await ctx.client.post("/api/cases/case-a/generate", json=request)
    assert stale_request.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_duplicate_starts_create_one_task(upload_context, monkeypatch, capture_start):
    import asyncio
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await upload(ctx)
    responses = await asyncio.gather(*(ctx.client.post("/api/cases/case-a/generate", json={"idempotency_key": "concurrent-request-1"}) for _ in range(3)))
    assert all(response.status_code == 201 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    assert len(capture_start) == 1
    async with ctx.sessions() as session:
        assert len((await session.scalars(select(ArchiveTask))).all()) == 1


@pytest.mark.asyncio
async def test_changed_classification_rejects_previous_final_approval(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(capabilities={"archive_assembly": True}, preview_only=True))
    await upload(ctx)
    async with ctx.sessions() as session:
        files = (await session.scalars(select(CaseFile))).all()
        manifest = build_source_manifest(files)
        task = ArchiveTask(case_id="case-a", status=TaskStatus.awaiting_review, fields={}, catalog_status=[], revision=1,
                           source_manifest=manifest, source_version=source_version(manifest, "civil"))
        session.add(task)
        files[0].doc_type = "evidence"
        await session.commit()
        task_id = task.id
    response = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json={"confirmation": True, "confirmed_revision": 1, "skipped": []})
    assert response.status_code == 409
    assert "材料或分类" in response.json()["detail"]
    assert capture_start == []


@pytest.mark.asyncio
@pytest.mark.parametrize("occupied", [False, True])
async def test_verified_required_missing_cannot_be_reclassified_by_client(upload_context, monkeypatch, occupied):
    ctx = upload_context
    launched = isolate_assembly(monkeypatch)
    catalog = {"seq":5,"name":"虚构必需项","found":False,"requirement":"required","legal_requirement_verified":True}
    if occupied:
        catalog = {"seq":5,"found":True,"material_checks":[{"seq":5,"name":"虚构必需子材料",
                    "status":"missing","requirement":"required","legal_requirement_verified":True}]}
    async with ctx.sessions() as session:
        task = ArchiveTask(case_id="case-a", status=TaskStatus.awaiting_review, revision=1,
                           fields={"_review_decisions": {"5": {"action": "not_applicable", "reason": "客户端声明不适用"}}},
                           catalog_status=[catalog],
                           rule_readiness={"formal_ready": True})
        session.add(task)
        await session.commit()
        task_id = task.id
    response = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json={"confirmation": True, "confirmed_revision": 1, "skipped": [5]})
    assert response.status_code == 409
    assert "草稿已保留" in response.json()["detail"]
    assert launched == []
    async with ctx.sessions() as session:
        saved = await session.get(ArchiveTask, task_id)
        assert saved.status == TaskStatus.awaiting_review
        assert saved.rule_readiness["formal_ready"] is False
        assert saved.rule_readiness["unresolved_required_items"][0]["seq"] == 5


@pytest.mark.asyncio
async def test_other_org_cannot_read_task_downloads_or_evidence(upload_context, monkeypatch):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    uploaded = await upload(ctx)
    file_id = uploaded.json()["id"]
    async with ctx.sessions() as session:
        source = await session.get(CaseFile, file_id)
        task = ArchiveTask(case_id="case-a", status=TaskStatus.done, output_pdf=source.abs_path,
                           fields={"_provenance": {"委托人": [{"source_path": source.abs_path, "page": 1, "quote": "Synthetic fixture", "method": "local_agent"}]}})
        session.add(task)
        await session.commit()
        task_id = task.id
    urls = [f"/api/tasks/{task_id}", f"/api/tasks/{task_id}/download/archive", f"/api/tasks/{task_id}/download/zip",
            f"/api/tasks/{task_id}/docx/立案审批表", f"/api/tasks/{task_id}/evidence",
            f"/api/cases/case-a/files/{file_id}/original", f"/api/cases/case-a/files/{file_id}/page/1"]
    for url in urls:
        assert (await ctx.client.get(url, headers={"X-Test-Org": "org-b"})).status_code == 404
    # Legacy fixture has no complete result manifest: owner sees a recoverable
    # integrity failure, while other organizations still cannot discover it.
    assert (await ctx.client.get(f"/api/tasks/{task_id}/download/archive")).status_code == 409
    assert (await ctx.client.get(f"/api/tasks/{task_id}/evidence")).json()["fields"]["委托人"][0]["file_id"] == file_id
    assert (await ctx.client.get(f"/api/cases/case-a/files/{file_id}/page/1")).status_code == 200


@pytest.mark.asyncio
async def test_resume_addition_preserves_parent_and_manual_edits(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await upload(ctx)
    response = await ctx.client.post("/api/cases/case-a/generate", json={})
    old_id = response.json()["id"]
    async with ctx.sessions() as session:
        parent = await session.get(ArchiveTask, old_id)
        parent.status = TaskStatus.awaiting_review
        parent.manual_fields = {"承办律师": "人工核对律师"}
        analysis=fixture_analysis(parent.source_manifest[0]["path"])
        analysis.fields.update(parent.manual_fields)
        parent.fields=analysis.fields
        save_snapshot(task_work_dir("org-a", "case-a", old_id), analysis,
                      base_name="fictional", metadata={"source_version": parent.source_version})
        await session.commit()
    await upload(ctx, name="补充材料.pdf")
    resumed = await ctx.client.post(f"/api/tasks/{old_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["id"] != old_id
    assert resumed.json()["parent_task_id"] == old_id
    async with ctx.sessions() as session:
        child = await session.get(ArchiveTask, resumed.json()["id"])
        assert child.manual_fields == {"承办律师": "人工核对律师"}
        assert len(child.source_manifest) == 2
        assert (await session.get(ArchiveTask, old_id)).status == TaskStatus.awaiting_review


@pytest.mark.asyncio
async def test_saved_edit_bumps_revision_and_old_confirmation_is_rejected(upload_context, monkeypatch):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    isolate_assembly(monkeypatch)
    async with ctx.sessions() as session:
        task = ArchiveTask(case_id="case-a", status=TaskStatus.awaiting_review, fields={"委托人": "虚构旧值"}, catalog_status=[], revision=3)
        session.add(task)
        await session.commit()
        task_id = task.id
    work = task_work_dir("org-a", "case-a", task_id)
    save_snapshot(work, fixture_analysis("fictional-not-read.pdf", {"委托人": "虚构旧值"}), base_name="fictional")
    saved = await ctx.client.patch(f"/api/tasks/{task_id}/fields", json={"fields": {"委托人": "人工改值"}})
    assert saved.status_code == 200
    assert saved.json()["revision"] == 4
    unchanged = await ctx.client.patch(f"/api/tasks/{task_id}/fields", json={"fields": {"委托人": "人工改值"}})
    assert unchanged.json()["revision"] == 4
    stale = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json={"skipped": [], "confirmation": True, "confirmed_revision": 3})
    assert stale.status_code == 409
    current = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json={"skipped": [], "confirmation": True, "confirmed_revision": 4})
    assert current.status_code == 200


@pytest.mark.asyncio
async def test_editing_closure_does_not_overwrite_independent_outcome(upload_context, monkeypatch):
    ctx=upload_context
    wire_storage(ctx,monkeypatch)
    isolate_assembly(monkeypatch)
    original={'委托人':'虚构甲','结案小结':'原办理过程','审（办）结果':'独立审办结果'}
    async with ctx.sessions() as session:
        task=ArchiveTask(case_id='case-a',status=TaskStatus.awaiting_review,
                         fields=original,catalog_status=[],revision=1)
        session.add(task);await session.commit();task_id=task.id
    work=task_work_dir('org-a','case-a',task_id)
    save_snapshot(work,fixture_analysis('fictional-not-read.pdf',original),base_name='fictional')
    response=await ctx.client.patch(f'/api/tasks/{task_id}/fields',json={'fields':{'结案小结':'人工修改办理过程'}})
    assert response.status_code==200, response.text
    fields=response.json()['fields']
    assert fields['结案小结']=='人工修改办理过程'
    assert fields['审（办）结果']=='独立审办结果'


@pytest.mark.asyncio
async def test_field_edit_resolves_matching_conflict_and_preserves_metadata(upload_context, monkeypatch):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    conflict = issue("field_conflict", "虚构案号存在冲突", detail={"field": "法院收案号", "values": ["A", "B"]})
    provenance = {"法院收案号": [{"page": 1, "quote": "A", "file_id": "fictional"}]}
    async with ctx.sessions() as session:
        task = ArchiveTask(case_id="case-a", status=TaskStatus.awaiting_review,
                           source_manifest=[], source_version=source_version([], "civil"),
                           fields={"法院收案号": "A", "_provenance": provenance}, issues=[conflict])
        session.add(task)
        await session.commit()
        save_snapshot(task_work_dir("org-a", "case-a", task.id), fixture_analysis("fixture", task.fields), base_name="fictional")
        task_id = task.id
    response = await ctx.client.patch(f"/api/tasks/{task_id}/fields", json={"fields": {"法院收案号": "人工核对 B"}})
    assert response.status_code == 200
    evidence = response.json()["fields"]["_provenance"]["法院收案号"]
    assert evidence[0] == provenance["法院收案号"][0]
    assert evidence[-1]["method"] == "human"
    assert evidence[-1]["value"] == "人工核对 B"
    assert "quote" not in evidence[-1]
    assert response.json()["fields"]["_issue_decisions"][conflict["id"]]["action"] == "acknowledged"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["_provenance", "_agent_events", "_agent_summary", "_analysis_metrics", "_rule_readiness", "formal_ready", "status", "revision", "source_manifest", "_preview_styles"])
async def test_client_cannot_forge_evidence_or_task_metadata(upload_context, field):
    response = await upload_context.client.patch("/api/tasks/999/fields", json={"fields": {field: "forged"}})
    assert response.status_code == 400


@pytest.mark.parametrize("case_type", ["civil", "consultation"])
def test_supplement_reuses_only_safe_materials_and_keeps_manual_value(tmp_path, case_type):
    import archive_pipeline as ap
    old_path, new_path = str(tmp_path / "old.pdf"), str(tmp_path / "new.pdf")
    old = {"file_id": "old", "path": old_path, "sha256": "old-hash", "doc_type": "default", "pages": 1, "filename": "old.pdf"}
    new = {"file_id": "new", "path": new_path, "sha256": "new-hash", "doc_type": "default", "pages": 1, "filename": "new.pdf"}
    parent = SimpleNamespace(id=1, case_id="fixture", source_manifest=[old], manual_fields={"承办律师": "人工律师"})
    task = SimpleNamespace(source_manifest=[old, new])
    analysis = fixture_analysis(old_path, {"承办律师": "原提取律师"})
    analysis.case_type = case_type
    analysis.fields.update(_agent_summary={"pages_checked": 1, "tools": ["read_pages"], "local": True},
                           _agent_events=[{"event": "old fixture"}],
                           _ocr_review=[{"source_path": old_path, "page": 1, "reason": "虚构旧页低置信度", "confidence": 0.3}])
    from unittest.mock import patch
    calls = []
    def analyze(case_type, *, sources, config, log):
        calls.append([source.path for source in sources])
        result = fixture_analysis(new_path, {"承办律师": "新材料律师", "案由": "虚构补件案由"})
        result.case_type = case_type
        result.fields.update(_agent_summary={"pages_checked": len(sources), "tools": ["search"], "local": True},
                             _agent_events=[{"event": "new fixture"}],
                             _ocr_review=[{"source_path": new_path, "page": 1, "reason": "虚构新页低置信度", "confidence": 0.4}])
        result.low_confidence_items = [{"doc_id": 0, "catalog_seq": 7, "pages": [0, 0]}]
        if case_type == "consultation":
            from pdf_doc_locator import DocumentUnit
            result.doc_spans.append(DocumentUnit(1, "evidence", 0, 0, catalog_seq=2, source_path=old_path))
        return result
    engine = SimpleNamespace(analyze_archive=analyze, compute_found_seqs=ap.compute_found_seqs, compute_missing_items=ap.compute_missing_items)
    files = [SimpleNamespace(id=row["file_id"], abs_path=row["path"], doc_type="default") for row in [old, new]]
    with patch("app.services.task_workflow.snapshot_exists", return_value=True), patch("app.services.task_workflow.load_analysis", return_value=(analysis, {})):
        output, manual, conflicts = analyze_with_parent(engine, task, parent, files, {"workflow_case_type": case_type}, "fictional-org", lambda _: None)
    assert calls == ([[old_path, new_path]] if case_type == "consultation" else [[new_path]])
    assert output.fields["承办律师"] == "人工律师"
    assert output.fields["案由"] == "虚构补件案由"
    assert {unit.source_path for unit in output.doc_spans} == {old_path, new_path}
    assert len({unit.doc_id for unit in output.doc_spans}) == 2
    assert conflicts
    if case_type == "civil":
        assert output.fields["_agent_summary"] == {"pages_checked": 2, "total_pages_checked": 2,
                                                   "this_run_pages": 1, "reused_pages": 1,
                                                   "tools": ["read_pages", "search"], "local": True}
        assert len(output.fields["_agent_events"]) == 2
        assert len(output.fields["_ocr_review"]) == 2
        classification = next(item for item in analysis_issues(output, [old, new]) if item["kind"] == "classification")
        assert classification["detail"]["doc_id"] == 1
        assert classification["detail"]["file_id"] == "new"
        assert classification["detail"]["filename"] == "new.pdf"
        assert classification["detail"]["page"] == 1
        ocr = [item for item in analysis_issues(output, [old, new]) if item["kind"] == "ocr"]
        assert {item["detail"]["file_id"] for item in ocr} == {"old", "new"}
        assert all(item["detail"]["page"] == item["detail"]["page_start"] == item["detail"]["page_end"] == 1 for item in ocr)
        assert unresolved_issues(ocr, output.fields) == ocr
        decisions = {item["id"]: {"action": "acknowledged", "reason": "仅虚构测试：已对照原件核对识别疑问"} for item in ocr}
        assert unresolved_issues(ocr, {"_issue_decisions": decisions}) == []


@pytest.mark.asyncio
async def test_existing_classification_issue_is_enriched_from_its_snapshot(upload_context, monkeypatch):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await upload(ctx)
    async with ctx.sessions() as session:
        files = (await session.scalars(select(CaseFile))).all()
        manifest = build_source_manifest(files)
        problem = issue("classification", "虚构分类待核对", detail={"doc_id": 0, "pages": [0, 0]})
        task = ArchiveTask(case_id="case-a", status=TaskStatus.awaiting_review, source_manifest=manifest,
                           source_version=source_version(manifest, "civil"), issues=[problem])
        session.add(task)
        await session.commit()
        task_id = task.id
    save_snapshot(task_work_dir("org-a", "case-a", task_id), fixture_analysis(files[0].abs_path), base_name="虚构定位")
    response = await ctx.client.get(f"/api/tasks/{task_id}")
    assert response.status_code == 200
    actual = response.json()["issues"][0]
    assert actual["id"] == problem["id"]
    assert actual["detail"]["file_id"] == files[0].id
    assert actual["detail"]["filename"] == files[0].filename
    assert actual["detail"]["page"] == actual["detail"]["page_start"] == actual["detail"]["page_end"] == 1


@pytest.mark.asyncio
async def test_recovery_requeues_versioned_task_without_discarding_checkpoint(upload_context, monkeypatch, capture_start):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    async with ctx.sessions() as session:
        session.add(User(id="actor", org_id="org-a", username="synthetic-actor", hashed_password="not-used", role=Role.admin))
        versioned = ArchiveTask(case_id="case-a", status=TaskStatus.running, created_by="actor", source_manifest=[{"file_id": "fixture"}], checkpoint="analyzed", requested_operation="assemble", confirmation={"revision": 1})
        legacy = ArchiveTask(case_id="case-a", status=TaskStatus.running)
        session.add_all([versioned, legacy])
        await session.commit()
        versioned_id, legacy_id = versioned.id, legacy.id
    await recovery.recover_interrupted_tasks()
    async with ctx.sessions() as session:
        restored = await session.get(ArchiveTask, versioned_id)
        assert restored.status == TaskStatus.pending
        assert restored.checkpoint == "analyzed"
        assert (await session.get(ArchiveTask, legacy_id)).status == TaskStatus.failed
    assert capture_start == [versioned_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["valid", "changed_word", "missing_package", "missing_word", "snapshot_mismatch", "verified_required", "missing_pagination", "cover_growth", "count_growth", "renderer_upgrade"])
async def test_completion_requires_actual_nine_artifacts_and_exports_only_after_verification(upload_context, monkeypatch, mode):
    """Use a fabricated snapshot and PDF renderer to test production orchestration;
    actual DOCX generation, merger, report, ZIP and manifest checker execute.
    This deliberately does not claim browser rendering or model accuracy.
    """
    import fitz
    import archive_pipeline as ap
    from app.services import system_docx_service, output_export, browser_pdf_service
    from app.services.analysis_snapshot import SYSTEM_TEMPLATE_NAMES
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await upload(ctx)
    async with ctx.sessions() as session:
        files = (await session.scalars(select(CaseFile))).all()
        manifest = build_source_manifest(files)
        version = source_version(manifest, "civil")
        task = ArchiveTask(case_id="case-a", created_by="test-user", status=TaskStatus.running, revision=1, source_manifest=manifest,
                           source_version=version, confirmation={"revision": 1, "source_version": version, "fields_digest": fields_digest({"委托人": "虚构甲"}, "catalog"), "order_mode": "catalog", "skipped": []},
                           requested_operation="assemble", issues=[])
        if mode == "verified_required":
            task.catalog_status = [{"seq": 5, "found": False, "requirement": "required", "legal_requirement_verified": True}]
        session.add(task)
        await session.commit()
        task_id = task.id
    analysis = fixture_analysis(files[0].abs_path)
    if mode == "snapshot_mismatch":
        analysis.fields["委托人"] = "确认之后发生改变的虚构值"
    save_snapshot(task_work_dir("org-a", "case-a", task_id), analysis, base_name="虚构测试",
                  metadata={"source_version": version})
    async def context(*args):
        return SimpleNamespace(case_type="civil"), files, {"output": {"preview_only": True}}
    async def org_name(*args):
        return "完全虚构测试律所"
    def render(fields, organization, work, log):
        directory = Path(work) / "browser_pdf"
        directory.mkdir(parents=True, exist_ok=True)
        rendered = {}
        for name in SYSTEM_TEMPLATE_NAMES:
            path = directory / (name + ".pdf")
            with fitz.open() as pdf:
                pdf.new_page(width=595.28, height=841.89).insert_text((72, 72), "Synthetic renderer fixture")
                pdf.save(path)
            rendered[name] = str(path)
        return rendered
    exported = []
    def export(work, *args):
        exported.append(work)
        return str(work)
    monkeypatch.setattr(archive_service, "_load_case_context", context)
    monkeypatch.setattr(archive_service, "_load_org_name", org_name)
    monkeypatch.setattr(archive_service, "archive_pipeline", lambda: ap)
    monkeypatch.setattr(archive_service, "render_system_form_pdfs", render)
    monkeypatch.setattr(archive_service, "get_settings", lambda: SimpleNamespace(preview_only=True))
    def render_single(name, fields, organization, path, log=print, *, derived_output=None):
        with fitz.open() as pdf:
            page = pdf.new_page(width=595.28, height=841.89)
            page.insert_text((72, 72), str(derived_output["volume_page_count"]) + " 页", fontname="china-s")
            if mode == "cover_growth":
                pdf.new_page()
            pdf.save(path)
        return str(path)
    monkeypatch.setattr(browser_pdf_service, "render_form_pdf", render_single)
    monkeypatch.setattr(output_export, "export_archive", export)
    if mode == "missing_word":
        original = system_docx_service.generate_system_docx
        def incomplete(*args, **kwargs):
            outputs = original(*args, **kwargs)
            outputs.pop("结案报告表")
            return outputs
        monkeypatch.setattr(system_docx_service, "generate_system_docx", incomplete)
    if mode == "missing_pagination":
        original_assemble = ap.assemble_archive
        def missing_labels(*args, **kwargs):
            result = original_assemble(*args, **kwargs)
            with fitz.open(result.output_pdf) as pdf:
                pdf.set_page_labels([])
                pdf.saveIncr()
            return result
        monkeypatch.setattr(ap, "assemble_archive", missing_labels)
    if mode == "count_growth":
        original_assemble = ap.assemble_archive
        calls = []
        def changing_count(*args, **kwargs):
            result = original_assemble(*args, **kwargs)
            calls.append(result)
            if len(calls) == 2:
                result.page_count += 1
            return result
        monkeypatch.setattr(ap, "assemble_archive", changing_count)
    await archive_service.run_assemble(task_id, "case-a", "org-a", "test-user")
    async with ctx.sessions() as session:
        final = await session.get(ArchiveTask, task_id)
        if mode == "verified_required":
            assert final.status == TaskStatus.awaiting_review
            assert final.rule_readiness["formal_ready"] is False
            assert exported == []
        elif mode not in ("valid", "changed_word", "missing_package", "renderer_upgrade"):
            assert final.status == TaskStatus.failed
            expected_error = {"missing_word": "Word", "snapshot_mismatch": "快照", "missing_pagination": "页码", "cover_growth":"封面分页", "count_growth":"未收敛"}[mode]
            assert expected_error in final.error
            assert not final.output_pdf
            assert exported == []
        else:
            assert final.status == TaskStatus.done, final.error
            assert final.artifacts["valid"] is True
            assert final.confirmation["fields_digest"] == fields_digest(final.fields, "catalog")
            assert final.artifacts["derived_output"]["assembly_passes"] == 2
            assert len(final.artifacts["artifacts"]) == 9
            assert final.rule_readiness["formal_ready"] is False
            assert final.fields["_saved_to"] == exported[0]
            assert len(list(Path(final.output_docx_dir).glob("*.docx"))) == 5
            assert Path(final.artifacts["result_dir"], "归档包.zip").is_file()
            artifact_paths = [Path(item["path"]) for item in final.artifacts["artifacts"]]
            original_mtimes = {str(path): path.stat().st_mtime_ns for path in artifact_paths}
            original_finished = final.finished_at.isoformat()
            restarted = []
            def capture_restart(task_id, coroutine):
                restarted.append(task_id)
                coroutine.close()
            monkeypatch.setattr(tasks.task_manager, "start", capture_restart)
            request = {"confirmation": True, "confirmed_revision": 1, "order_mode": "catalog", "skipped": []}
            for _ in range(2):
                repeated = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json=request)
                assert repeated.status_code == 200, repeated.text
                assert repeated.json()["status"] == "done"
                assert repeated.json()["finished_at"] == original_finished
            assert restarted == []
            assert {str(path): path.stat().st_mtime_ns for path in artifact_paths} == original_mtimes
            if mode == "renderer_upgrade":
                previous_path = final.output_pdf
                previous_bytes = {str(path):path.read_bytes() for path in artifact_paths}
                old = dict(final.artifacts)
                old.pop("renderer_version")
                final.artifacts = old
                await session.commit()
                read_old = (await ctx.client.get(f"/api/tasks/{task_id}")).json()
                assert read_old["status"] == "done" and read_old["output_pdf"] == previous_path
                upgraded = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json=request)
                assert upgraded.json()["status"] == "running" and restarted == [task_id]
                await archive_service.run_assemble(task_id, "case-a", "org-a", "test-user")
                rebuilt = (await ctx.client.get(f"/api/tasks/{task_id}")).json()
                assert rebuilt["status"] == "done" and rebuilt["revision"] == 1
                assert rebuilt["output_pdf"] != previous_path
                assert all(Path(path).read_bytes() == content for path,content in previous_bytes.items())
                preview = (await ctx.client.get(f"/api/tasks/{task_id}/preview-fields/档案卷宗")).json()
                assert preview["derived_output"]["volume_page_count"] > 0
                assert not any(item["key"] == "卷内页数" for item in preview["fields"])
                return
            # Reads and all downloads must reject a broken result, including
            # same-length tampering, while preserving the analyzed revision.
            if mode == "changed_word":
                word = next(path for path in artifact_paths if path.suffix == ".docx")
                content = bytearray(word.read_bytes())
                content[-1] ^= 1
                word.write_bytes(content)
            elif mode == "missing_package":
                next(path for path in artifact_paths if path.suffix == ".zip").unlink()
            else:
                next(path for path in artifact_paths if path.suffix == ".docx").unlink()
            damaged_read = (await ctx.client.get(f"/api/tasks/{task_id}")).json()
            assert damaged_read["status"] == "failed"
            assert damaged_read["phase"] == "artifacts_invalid"
            assert damaged_read["can_resume"] is True
            assert damaged_read["artifacts"] == []
            assert not damaged_read["has_docx"] and not damaged_read["has_archive"]
            assert damaged_read["revision"] == 1
            for suffix in ("download/archive", "download/zip", "download/docx", "docx/档案卷宗"):
                unavailable = await ctx.client.get(f"/api/tasks/{task_id}/{suffix}")
                assert unavailable.status_code == 409
            # Generate also returns the repairable task instead of creating a
            # duplicate task; either resume or repeat confirmation may rebuild.
            generated = await ctx.client.post("/api/cases/case-a/generate", json={})
            assert generated.json()["id"] == task_id
            assert generated.json()["status"] == "failed"
            if mode == "changed_word":
                damaged = await ctx.client.post(f"/api/tasks/{task_id}/resume")
                assert damaged.json()["status"] == "pending"
            else:
                damaged = await ctx.client.post(f"/api/tasks/{task_id}/assemble", json=request)
                assert damaged.json()["status"] == "running"
            assert damaged.status_code == 200, damaged.text
            assert restarted == [task_id]
            await archive_service.run_assemble(task_id, "case-a", "org-a", "test-user")
            restored = (await ctx.client.get(f"/api/tasks/{task_id}")).json()
            assert restored["status"] == "done", restored
            assert restored["revision"] == 1 and len(restored["artifacts"]) == 9
            assert restored["has_docx"] and restored["has_archive"]
            assert (await ctx.client.get(f"/api/tasks/{task_id}/download/zip")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("original_mode", ["local", "cloud", "unknown"])
async def test_analysis_checkpoint_resume_does_not_call_model_again(upload_context, monkeypatch, original_mode):
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    await upload(ctx)
    async with ctx.sessions() as session:
        files = (await session.scalars(select(CaseFile))).all()
        manifest = build_source_manifest(files)
        version = source_version(manifest, "civil")
        task = ArchiveTask(case_id="case-a", status=TaskStatus.pending, source_version=version, source_manifest=manifest)
        session.add(task)
        await session.commit()
        task_id = task.id
    analysis = fixture_analysis(files[0].abs_path, {"委托人": "虚构甲", "合同号": "人工核对-恢复-001"})
    from case_outcome import STRICT_EVIDENCE_VERSION
    analysis.fields["_field_normalization_version"] = STRICT_EVIDENCE_VERSION
    analysis.fields["_analysis_metrics"] = {"scope": "this_analysis_call", "analysis_seconds": 1200}
    analysis.fields["_agent_summary"] = {"pages_checked": 1, "accepted_fact_count": 2,
        "this_run_metrics": {"model_requests": 50, "model_seconds": 1000}}
    original_business_fields = {key: value for key, value in analysis.fields.items() if not key.startswith("_")}
    save_snapshot(task_work_dir("org-a", "case-a", task_id), analysis,
                  base_name="虚构恢复", processing_mode=original_mode, metadata={"source_version": version})
    async def context(*args):
        return SimpleNamespace(case_type="civil"), files, {"output": {"preview_only": True}}
    async def forbidden(*args):
        raise AssertionError("An analyzed checkpoint must not rerun OCR/model")
    monkeypatch.setattr(archive_service, "_load_case_context", context)
    monkeypatch.setattr(archive_service, "check_readiness", forbidden)
    monkeypatch.setattr(archive_service, "run_word", forbidden)
    await archive_service.run_archive(task_id, "case-a", "org-a", "test-user")
    async with ctx.sessions() as session:
        recovered = await session.get(ArchiveTask, task_id)
        assert recovered.status == TaskStatus.awaiting_review, recovered.error
        assert recovered.fields["委托人"] == "虚构甲"
        assert recovered.fields["合同号"] == "人工核对-恢复-001"
        assert recovered.fields["_analysis_metrics"] == {"scope": "this_analysis_call", "analysis_status": "snapshot_reused"}
        assert recovered.fields["_agent_summary"] == {"pages_checked": 1, "accepted_fact_count": 2}
        assert {key: value for key, value in recovered.fields.items() if not key.startswith("_")} == original_business_fields
        assert recovered.checkpoint == "analyzed"
    from app.services.analysis_snapshot import load_snapshot_data
    saved = load_snapshot_data(task_work_dir("org-a", "case-a", task_id))
    assert saved["processing_mode"] == original_mode
    assert saved["fields"]["_analysis_metrics"] == {"scope": "this_analysis_call", "analysis_status": "snapshot_reused"}
    assert "this_run_metrics" not in saved["fields"]["_agent_summary"]
    assert {key: value for key, value in saved["fields"].items() if not key.startswith("_")} == original_business_fields


@pytest.mark.asyncio
async def test_progress_log_survives_new_manager_instance(upload_context, monkeypatch):
    import asyncio
    from app import database
    from app.services.task_manager import TaskManager
    ctx = upload_context
    monkeypatch.setattr(database, "AsyncSessionLocal", ctx.sessions)
    async with ctx.sessions() as session:
        task = ArchiveTask(case_id="case-a", status=TaskStatus.pending, log_text="从已保存分析检查点恢复，无需重复识别材料")
        session.add(task)
        await session.commit()
        task_id = task.id
    manager = TaskManager()
    async def work():
        manager.get_tracker(task_id).log("归档助理：正在阅读 1 个页面片段")
        await asyncio.sleep(0.01)
    manager.start(task_id, work())
    await manager._tasks[task_id]
    async with ctx.sessions() as session:
        task = await session.get(ArchiveTask, task_id)
        assert "从已保存分析检查点恢复，无需重复识别材料" in task.log_text
        assert "归档助理：正在阅读 1 个页面片段" in task.log_text
        assert task.heartbeat_at
