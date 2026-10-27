"""Independent offline edge review of acknowledged-conflict inheritance."""
import copy
from types import SimpleNamespace

import pytest

from tests.test_analysis_reuse_independent_audit import row, run, visual_fields
from tests.test_task_workflow import fixture_analysis
from app.services import task_workflow as workflow
from app.services.task_sources import source_version


@pytest.mark.parametrize("legacy_manifest", [None, []])
def test_no_manifest_legacy_reanalyzes_drops_ack_but_retains_manual_value(monkeypatch, legacy_manifest):
    previous = fixture_analysis(row(1)["path"], visual_fields())
    manual = {"承办律师":"虚构人工甲", "合同号":""}
    conflicts = workflow.merge_manual_fields(previous, manual)
    manual["_issue_decisions"] = {conflicts[0]["id"]:{"action":"acknowledged","reason":"旧卷明确核对"}}
    previous.fields["_issue_decisions"] = copy.deepcopy(manual["_issue_decisions"])
    result, fresh, calls = run(previous, legacy_manifest, [row(1)], manual, conflicts, monkeypatch)
    assert calls == [[row(1)["path"]]]
    assert result.fields["承办律师"] == "虚构人工甲" and result.fields["合同号"] == ""
    assert not result.fields.get("_issue_decisions")
    assert workflow.unresolved_issues(fresh, result.fields) == fresh
    assert fresh[0]["detail"]["evidence_version"] == source_version([row(1)], "civil")


@pytest.mark.parametrize("missing", ["sha256", "pages", "doc_type"])
def test_incomplete_old_manifest_cannot_reuse_old_ack(monkeypatch, missing):
    old_row = row(1)
    old_row.pop(missing)
    previous = fixture_analysis(row(1)["path"], visual_fields())
    manual = {"承办律师":"虚构人工甲"}
    conflicts = workflow.merge_manual_fields(previous, manual)
    manual["_issue_decisions"] = {conflicts[0]["id"]:{"action":"acknowledged","reason":"旧卷核对"}}
    result, fresh, calls = run(previous, [old_row], [row(1)], manual, conflicts, monkeypatch)
    assert calls == [[row(1)["path"]]]
    assert workflow.unresolved_issues(fresh, result.fields) == fresh


@pytest.mark.parametrize("malformed", [[{}], [None], "invalid-manifest"])
def test_malformed_old_manifest_fails_before_any_analyzer(monkeypatch, malformed):
    previous = fixture_analysis(row(1)["path"], visual_fields())
    parent = SimpleNamespace(id=1,case_id="fictional",source_manifest=malformed,manual_fields={},issues=[])
    task = SimpleNamespace(source_manifest=[row(1)])
    monkeypatch.setattr(workflow,"snapshot_exists",lambda *_:True)
    monkeypatch.setattr(workflow,"load_analysis",lambda *_:(previous,{}))
    def forbidden(*_, **__): pytest.fail("Malformed parent manifest must not call model/analyzer")
    with pytest.raises((KeyError, TypeError)):
        workflow.analyze_with_parent(SimpleNamespace(analyze_archive=forbidden), task, parent,
            [SimpleNamespace(id="1",abs_path=row(1)["path"],doc_type="default")],
            {"workflow_case_type":"civil","extraction":{"mode":"visual_agent"},
             "vision":{"model":"deepseek-flash","workflow":"document_two_stage"}},
            "fictional-org", lambda _:None)


@pytest.mark.parametrize("stage", ["", "first_instance", "execution"])
def test_fresh_manual_conflict_version_includes_exact_stage(stage):
    evidence = source_version([row(1)],"civil",stage)
    analysis = fixture_analysis(row(1)["path"],visual_fields())
    issues = workflow.merge_manual_fields(analysis,{"承办律师":"虚构人工甲"},evidence_version=evidence)
    assert issues[0]["detail"]["evidence_version"] == evidence
    if stage:
        assert evidence != source_version([row(1)],"civil")
