"""Fictional identity links stay scoped, current and visible on both pages."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.services.evidence_links import supporting_refs
from app.services.field_assurance import field_assurance
from app.services.review_queue import build_review_queue


def fixture():
    client = {"field": "委托人", "method": "visual_agent_local_evidence", "value": "虚构澄谷公司",
              "quote": "委托人：虚构澄谷公司", "source_path": "contract.pdf", "page": 1}
    address = {"method": "visual_agent_local_evidence", "value": "虚构路8号", "quote": "联系地址：虚构路8号",
               "source_path": "intro.pdf", "page": 1, "binding": "client_contact", "supporting_sources": [client]}
    data = {"委托人": client["value"], "地址": address["value"],
            "_provenance": {"委托人": [client], "地址": [address]}}
    manifest = [{"file_id": "contract", "path": "contract.pdf", "filename": "虚构合同.pdf", "pages": 1},
                {"file_id": "intro", "path": "intro.pdf", "filename": "虚构介绍.pdf", "pages": 1}]
    return data, address, manifest


def test_two_source_badge_and_review_links_keep_both_pages_without_private_paths():
    data, address, manifest = fixture()
    before = deepcopy(data)
    result = field_assurance("地址", data["地址"], data, source_manifest=manifest)
    assert result["status"] == "source_supported"
    assert result["source_count"] == 2
    assert {r["file_id"] for r in result["anchors"]} == {"contract", "intro"}
    task = SimpleNamespace(fields=data, source_manifest=manifest, catalog_status=[], issues=[{
        "id": "address-review", "kind": "field_conflict", "blocking": True,
        "message": "地址待核", "detail": {"field": "地址"}}])
    queue = build_review_queue(task)
    assert {r["file_id"] for r in queue[0]["sources"]} == {"contract", "intro"}
    assert "source_path" not in json.dumps([result, queue])
    assert data == before


@pytest.mark.parametrize("change", ["client_changed", "client_conflict", "foreign_source", "bad_page", "quote_changed", "removed_source", "forged_id"])
def test_identity_link_cannot_keep_current_badge_after_binding_changes(change):
    data, address, manifest = fixture()
    support = address["supporting_sources"][0]
    if change == "client_changed": data["委托人"] = "另一家虚构公司"
    elif change == "client_conflict": data["_field_conflicts"] = [{"field": "委托人", "new": "另一家虚构公司"}]
    elif change == "foreign_source": support["source_path"] = "another-case.pdf"
    elif change == "bad_page": support["page"] = 2
    elif change == "quote_changed": address["supporting_sources"] = [dict(support, quote="伪造引文")]
    elif change == "removed_source": manifest[:] = [manifest[1]]
    elif change == "forged_id": support["file_id"] = "another-case"
    assert supporting_refs(address, data, manifest) is None
    assert field_assurance("地址", data["地址"], data, source_manifest=manifest)["status"] == "unverified"


def test_current_human_address_remains_a_human_decision():
    data, address, manifest = fixture()
    data["地址"] = ""
    data["_provenance"]["地址"].append({"method": "human", "value": ""})
    assert field_assurance("地址", "", data, source_manifest=manifest)["status"] == "human_confirmed"


def test_assistant_explains_current_binding_and_labels_stale_binding_as_history():
    import os
    from app.services.case_assistant import execute_tool
    data, address, manifest = fixture()
    sources = {os.path.normcase(os.path.abspath(row["path"])): row for row in manifest}
    task = SimpleNamespace(fields=data, source_manifest=manifest)
    command = {"tool": "explain_field", "field": "地址", "query": ""}
    result = execute_tool(command, task, {}, sources)
    assert any("身份关联依据" in row["title"] and row.get("file_id") == "contract" for row in result["items"])
    data["委托人"] = "另一家虚构公司"
    stale = execute_tool(command, task, {}, sources)
    assert any("身份关联已失效" in row["title"] for row in stale["items"])
    assert not any(row.get("file_id") == "contract" for row in stale["items"])


def test_resolved_link_keeps_audit_but_does_not_claim_current_fact_is_unaccepted():
    from app.services.task_workflow import analysis_issues
    data, address, manifest = fixture()
    rejected = {"field": "地址", "source_path": address["source_path"], "page": 1,
                "reason_code": "local_evidence_rejected", "resolution": "accepted_after_linked_evidence"}
    data["_fact_review"] = [rejected]
    analysis = SimpleNamespace(fields=data, doc_spans=[], low_confidence_items=[])
    assert not any(row["kind"] == "fact_review" for row in analysis_issues(analysis, manifest))
    assert data["_fact_review"] == [rejected]
    data["委托人"] = "另一家虚构公司"
    assert any(row["kind"] == "fact_review" for row in analysis_issues(analysis, manifest))
    assert data["_fact_review"] == [rejected]


@pytest.mark.asyncio
async def test_authorized_endpoint_exposes_both_sources_and_keeps_tenant_boundary(upload_context, monkeypatch):
    from tests.test_file_import_api import upload
    from tests.test_task_workflow import wire_storage
    from app.models import ArchiveTask, CaseFile, TaskStatus
    ctx = upload_context
    wire_storage(ctx, monkeypatch)
    ids = [(await upload(ctx)).json()["id"], (await upload(ctx)).json()["id"]]
    async with ctx.sessions() as db:
        files = [await db.get(CaseFile, file_id) for file_id in ids]
        data, address, manifest = fixture()
        client = address["supporting_sources"][0]
        client["source_path"], address["source_path"] = files[0].abs_path, files[1].abs_path
        for row, file in zip(manifest, files):
            row.update(file_id=file.id, path=file.abs_path, filename=file.filename)
        task = ArchiveTask(case_id="case-a", status=TaskStatus.done, fields=data, source_manifest=manifest)
        db.add(task)
        await db.commit()
        task_id = task.id
    response = await ctx.client.get(f"/api/tasks/{task_id}/evidence")
    assert response.status_code == 200
    rows = response.json()["fields"]["地址"]
    assert {r["file_id"] for r in rows} == set(ids)
    assert any(r["source_role"] == "client_identity" for r in rows)
    assert "source_path" not in response.text
    assert (await ctx.client.get(f"/api/tasks/{task_id}/evidence", headers={"X-Test-Org": "org-b"})).status_code == 404


from tests.test_file_import_api import upload_context  # isolated DB + synthetic PDFs
