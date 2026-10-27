"""Stage changes must not inherit previous analysis/review authorization."""
import copy
from types import SimpleNamespace

import pytest

from tests.test_analysis_reuse_independent_audit import row, visual_fields
from tests.test_task_workflow import fixture_analysis
from app.models import ArchiveTask
from app.services import task_workflow as workflow
from app.services.task_sources import source_version
import archive_pipeline as ap


def analyze(monkeypatch, *, old_stage="first_instance", stage="first_instance",
            parent_version="valid", extra=True, legacy_test_double=False):
    old = [row(1)]
    current = old + [row(2)] if extra else old
    previous = fixture_analysis(row(1)["path"], visual_fields())
    manual = {"承办律师":"虚构人工甲", "合同号":""}
    previous_conflicts = workflow.merge_manual_fields(previous, manual,
        evidence_version=source_version(old,"civil",old_stage))
    previous_id = previous_conflicts[0]["id"]
    manual["_issue_decisions"] = {previous_id:{"action":"acknowledged","reason":"仅确认过原办理阶段材料"}}
    previous.fields["_issue_decisions"] = copy.deepcopy(manual["_issue_decisions"])
    profile = {"processing_mode":"deepseek_cloud","model":"deepseek-flash","workflow":"document_two_stage"}
    parent_args = dict(id=1,case_id="fictional",source_manifest=old,manual_fields=manual,
                       issues=previous_conflicts,execution_profile=profile)
    if not legacy_test_double:
        parent_args["source_version"] = source_version(old,"civil",old_stage) if parent_version=="valid" else parent_version
    parent = SimpleNamespace(**parent_args) if legacy_test_double else ArchiveTask(**parent_args)
    task = ArchiveTask(id=2,case_id="fictional",source_manifest=current,
        source_version=source_version(current,"civil",stage),execution_profile=profile)
    calls=[]
    def fake_analyze(case_type, *, sources, **kwargs):
        calls.append([x.path for x in sources])
        return fixture_analysis(sources[0].path, visual_fields())
    monkeypatch.setattr(workflow,"snapshot_exists",lambda *_:True)
    monkeypatch.setattr(workflow,"load_analysis",lambda *_:(copy.deepcopy(previous),{}))
    engine = SimpleNamespace(analyze_archive=fake_analyze,compute_found_seqs=ap.compute_found_seqs,
                              compute_missing_items=ap.compute_missing_items)
    result, preserved_manual, conflicts = workflow.analyze_with_parent(engine,task,parent,
        [SimpleNamespace(id=x["file_id"],abs_path=x["path"],doc_type=x["doc_type"]) for x in current],
        {"workflow_case_type":"civil","workflow_stage":stage,"extraction":{"mode":"visual_agent"},
         "vision":{"model":"deepseek-flash","workflow":"document_two_stage"}},"fictional-org",lambda _:None)
    return result, preserved_manual, conflicts, calls, previous_id


@pytest.mark.parametrize("extra",[False,True])
def test_stage_change_reanalyzes_all_clears_ack_and_preserves_human(monkeypatch, extra):
    result, manual, conflicts, calls, old_id = analyze(monkeypatch,stage="execution",extra=extra)
    assert calls == [[row(1)["path"],row(2)["path"]] if extra else [row(1)["path"]]]
    assert result.fields["承办律师"] == "虚构人工甲" and result.fields["合同号"] == ""
    assert not result.fields.get("_issue_decisions") and "_issue_decisions" not in manual
    assert len(workflow.unresolved_issues(conflicts,result.fields))==1
    assert conflicts[0]["id"] != old_id


@pytest.mark.parametrize("version",[None,"","not-a-source-version","0"*64])
def test_explicit_missing_or_invalid_parent_source_version_cannot_reuse(monkeypatch,version):
    result, manual, conflicts, calls, _ = analyze(monkeypatch,parent_version=version)
    assert calls == [[row(1)["path"],row(2)["path"]]]
    assert result.fields["承办律师"] == "虚构人工甲"
    assert "_issue_decisions" not in manual
    assert workflow.unresolved_issues(conflicts,result.fields)==conflicts


@pytest.mark.parametrize("extra",[False,True])
def test_same_stage_keeps_old_decision_and_uses_only_delta(monkeypatch,extra):
    result, manual, conflicts, calls, old_id = analyze(monkeypatch,extra=extra)
    assert calls == ([[row(2)["path"]]] if extra else [])
    assert manual["_issue_decisions"][old_id]["action"]=="acknowledged"
    old = next(x for x in conflicts if x["id"]==old_id)
    assert old in workflow.unresolved_issues(conflicts,result.fields)
    # A preserved UI acknowledgement is not a source-bound factual choice.


def test_attribute_absent_lightweight_legacy_test_double_compatibility(monkeypatch):
    _, _, _, calls, _ = analyze(monkeypatch,legacy_test_double=True)
    assert calls == [[row(2)["path"]]]
