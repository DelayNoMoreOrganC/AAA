"""Synthetic completeness queries: no model, real case, or source file reads."""
import copy
import json
import os
from types import SimpleNamespace

import pytest

from app.models import ArchiveTask
from app.services import case_assistant as service
from app.services.archive_rules import catalog_material_status
from tests.test_case_assistant import context
from tests.test_file_import_api import upload_context


COMMAND = {"tool": "check_missing", "query": "", "field": ""}
PATH = os.path.abspath("synthetic-missing-only.pdf")
SOURCE = {"file_id": "synthetic-file", "filename": "虚构来源.pdf", "path": PATH, "pages": 8}
SOURCES = {os.path.normcase(PATH): SOURCE}


def check(identity="contract", **changes):
    value = {"id": "material:" + identity, "seq": 3, "name": "委托合同",
             "check_kind": "source_material", "status": "missing", "applicable": None,
             "requirement": "unknown", "legal_requirement_verified": False,
             "message": "本次材料中尚未识别到该类文书", "sources": [], "related_sources": []}
    value.update(changes)
    return value


def catalog(*checks, additional=None, **changes):
    row = {"seq": 3, "name": "合同目录槽", "found": True,
           "material_status_version": "synthetic-material-v1", "material_checks": list(checks)}
    if additional is not None:
        row["additional_material_checks"] = additional
    row.update(changes)
    return [row]


def query(rows, sources=SOURCES):
    task = SimpleNamespace(catalog_status=rows, fields={"委托人": "虚构人工值",
                           "_review_decisions": {"3": {"action": "skip", "reason": "仅目录处理"}}},
                           rule_readiness={"formal_ready": False, "version": "synthetic-rule-v1"})
    snapshot = {"fields": copy.deepcopy(task.fields)}
    before = copy.deepcopy((task.__dict__, snapshot, sources))
    result = service.execute_tool(COMMAND, task, snapshot, sources)
    assert (task.__dict__, snapshot, sources) == before
    return result


def test_real_material_builder_agency_notice_in_contract_slot_still_reports_missing_contract():
    # Actual rule builder, but only a fabricated DocumentUnit and manifest.
    unit = SimpleNamespace(doc_id=0, doc_type="agency_notice", catalog_seq=3,
                           source_path=PATH, start_page=1, end_page=2, confidence=.95,
                           manual_catalog_seq=None)
    analysis = SimpleNamespace(case_type="civil", doc_spans=[unit], found_seqs={3},
                               missing_items=[], low_confidence_items=[])
    rows = catalog_material_status(analysis, source_manifest=[{**SOURCE}])
    assert rows[0]["found"] is True
    result = query(rows)
    contract = next(item for item in result["items"] if item["title"] == "3 · 委托合同")
    assert contract["text"].startswith("适用性待核验；尚未识别")
    assert "通知书不能证明委托合同已提供或签署" in contract["text"]
    assert (contract["file_id"], contract["page"]) == (SOURCE["file_id"], 2)
    assert "系统填写表格不能证明已审批、签署或送达" in result["message"]
    assert "source_path" not in json.dumps(result)


def test_additional_checks_and_execution_review_are_consolidated_and_deduplicated():
    primary = check()
    extra = check("evidence", seq=7, name="证据材料", status="unverified")
    executions = [check("form-" + str(n), check_kind="execution_review") for n in range(4)]
    result = query(catalog(primary, additional=[copy.deepcopy(primary), extra, *executions]))
    assert [item["title"] for item in result["items"]] == ["3 · 委托合同", "7 · 证据材料"]
    assert "2 项缺失或待核" in result["message"]
    assert result["message"].count("系统填写表格不能证明") == 1


@pytest.mark.parametrize("requirement,verified,label", [
    ("optional", False, "适用性待核验"), ("required", False, "适用性待核验"),
    ("unknown", True, "适用性待核验"), ("optional", True, "可选材料"),
    ("conditional", True, "条件必要"), ("required", True, "必要材料"),
])
def test_unverified_optionality_does_not_hide_material_or_assert_a_legal_obligation(requirement, verified, label):
    result = query(catalog(check(requirement=requirement, legal_requirement_verified=verified)))
    assert len(result["items"]) == 1
    assert result["items"][0]["text"].startswith(label + "；")
    assert "必须" not in result["items"][0]["text"]


@pytest.mark.parametrize("applicable,count", [(False, 0), (True, 1), (None, 1), (0, 1)])
def test_only_explicit_not_applicable_excludes_the_check(applicable, count):
    result = query(catalog(check(applicable=applicable)))
    assert len(result["items"]) == count


@pytest.mark.parametrize("status", ["recognized", "verified"])
def test_recognized_is_not_reported_missing_or_treated_as_signature_or_delivery(status):
    result = query(catalog(check(status=status)))
    assert result["items"] == []
    assert "0 项缺失或待核" in result["message"]
    assert "已识别文书不等于已签署、生效或送达" in result["message"]


@pytest.mark.parametrize("ref", [
    {"file_id": "foreign-file", "page": 1, "filename": "FOREIGN_SECRET"},
    {"file_id": SOURCE["file_id"], "page": 1, "source_path": "FOREIGN_SECRET.pdf"},
    {"file_id": SOURCE["file_id"], "page": 1, "path": "FOREIGN_SECRET.pdf"},
    {"file_id": SOURCE["file_id"], "page": 0},
    {"file_id": SOURCE["file_id"], "page": 9},
    {"file_id": SOURCE["file_id"], "page": True},
])
def test_cross_case_or_invalid_anchor_is_not_returned(ref):
    result = query(catalog(check(related_sources=[ref])))
    assert "file_id" not in result["items"][0] and "page" not in result["items"][0]
    assert "FOREIGN_SECRET" not in json.dumps(result)


def test_invalid_first_reference_cannot_hide_a_later_in_scope_anchor_or_supply_its_name():
    result = query(catalog(check(related_sources=[
        {"file_id": "foreign-file", "page": 2},
        {"file_id": SOURCE["file_id"], "page": 3, "filename": "FOREIGN_SECRET"},
    ])))
    assert result["items"][0]["file_id"] == SOURCE["file_id"]
    assert result["items"][0]["page"] == 3
    assert "FOREIGN_SECRET" not in json.dumps(result)


def test_legacy_keeps_catalog_labels_and_explicitly_limits_completeness_claim():
    rows = [{"seq": 1, "name": "目录缺项", "found": False, "requirement": "required"},
            {"seq": 3, "name": "目录已有", "found": True}]
    result = query(rows)
    assert len(result["items"]) == 1
    assert result["items"][0]["text"].startswith("参考必要；")
    assert "历史任务仅记录目录空位" in result["message"]
    assert "不能据此判断本案材料是否齐备" in result["message"]


def test_empty_modern_checks_do_not_fall_back_to_catalog_occupancy():
    result = query(catalog(found=False))
    assert result["items"] == []
    assert "历史任务" not in result["message"]


def test_result_limit_preserves_true_total_without_claiming_all_items_are_shown():
    result = query(catalog(*[check(str(n), seq=n, name="虚构材料") for n in range(31)]))
    assert len(result["items"]) == 30
    assert "31 项" in result["message"] and "最多30项" in result["message"]


@pytest.mark.asyncio
async def test_http_query_and_history_keep_modern_missing_result_without_modifying_task(context, monkeypatch):
    ctx = context
    monkeypatch.setattr(service, "select_tool", lambda *_: dict(COMMAND))
    monkeypatch.setattr(service, "_source_pages", lambda *_: pytest.fail("Missing query must not read source contents"))
    before_snapshot = (ctx.work / "analysis_snapshot.json").read_bytes()
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        task.catalog_status = catalog(check(message="通知书不证明委托合同已提供或签署",
            related_sources=[{"file_id": "foreign-file", "page": 1, "filename": "FOREIGN_SECRET"},
                             {"file_id": ctx.file_id, "page": 1}]))
        expected_catalog = copy.deepcopy(task.catalog_status)
        await db.commit()
    url = f"/api/tasks/{ctx.task_id}/assistant"
    response = await ctx.client.post(url, json={"message": "还缺什么材料", "request_id": "synthetic-material-query"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"][0]["file_id"] == ctx.file_id and body["items"][0]["page"] == 1
    assert "通知书不证明委托合同" in body["items"][0]["text"]
    assert "FOREIGN_SECRET" not in response.text
    history = await ctx.client.get(url + "/history")
    assert history.status_code == 200, history.text
    assert history.json()["messages"][-1]["items"] == body["items"]
    async with ctx.sessions() as db:
        task = await db.get(ArchiveTask, ctx.task_id)
        assert task.fields == ctx.original_fields and task.catalog_status == expected_catalog
        assert task.revision == 3
    assert (ctx.work / "analysis_snapshot.json").read_bytes() == before_snapshot
