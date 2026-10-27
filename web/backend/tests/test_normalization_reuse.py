"""Synthetic snapshots: unsafe historical normalization is never reused."""
from types import SimpleNamespace

import pytest

from app.core.v4_bridge import init_v4_path
from app.services.task_workflow import analysis_reuse_compatible
from app.services import task_workflow as workflow

init_v4_path()
from case_outcome import STRICT_EVIDENCE_VERSION
from visual_archive_agent import VISUAL_ANALYSIS_VERSION


@pytest.mark.parametrize("mode", ["workstation_agent", "visual_agent"])
@pytest.mark.parametrize("version", [None, "strict-fields-v1", STRICT_EVIDENCE_VERSION])
def test_current_postprocessing_version_is_required_for_both_workstation_modes(mode, version):
    visual = mode == "visual_agent"
    fields = {"_agent_summary":{"visual":visual, "model":"deepseek-flash", "workflow":"document_two_stage",
                                "analysis_version": VISUAL_ANALYSIS_VERSION}}
    if version is not None:
        fields["_field_normalization_version"] = version
    config = {"extraction":{"mode":mode}, "vision":{"model":"deepseek-flash", "workflow":"document_two_stage"}}
    assert analysis_reuse_compatible(SimpleNamespace(fields=fields), config) is (version == STRICT_EVIDENCE_VERSION)


def test_legacy_non_workstation_mode_does_not_invent_a_version_requirement():
    assert analysis_reuse_compatible(SimpleNamespace(fields={}), {"extraction":{"mode":"legacy"}})


@pytest.mark.parametrize("version", [None, "visual-analysis-v1", VISUAL_ANALYSIS_VERSION])
def test_visual_classification_version_is_required_even_when_field_rules_match(version):
    summary = {"visual": True, "model": "deepseek-flash", "workflow": "document_two_stage"}
    if version is not None:
        summary["analysis_version"] = version
    fields = {"_field_normalization_version": STRICT_EVIDENCE_VERSION, "_agent_summary": summary}
    config = {"extraction": {"mode": "visual_agent"},
              "vision": {"model": "deepseek-flash", "workflow": "document_two_stage"}}
    assert analysis_reuse_compatible(SimpleNamespace(fields=fields), config) is (version == VISUAL_ANALYSIS_VERSION)


@pytest.mark.parametrize("explicit_manual", [False, True])
def test_incompatible_legacy_machine_fields_are_not_relabeled_human(monkeypatch, explicit_manual):
    from tests.test_task_workflow import fixture_analysis
    old = fixture_analysis("fictional.pdf", {"结案小结":"旧自动派生、未经采纳的虚构判决", "_field_normalization_version":"strict-fields-v1"})
    saved = dict(old.fields)
    fresh = fixture_analysis("fictional.pdf", {"委托人":"虚构甲", "_field_normalization_version":STRICT_EVIDENCE_VERSION})
    manual = {"结案小结":"", "合同号":"人工历史值", "_field_normalization_version":"strict-fields-v1"} if explicit_manual else {}
    parent = SimpleNamespace(id=1,case_id="fictional",source_manifest=None,manual_fields=manual)
    task = SimpleNamespace(source_manifest=[{"file_id":"f1","path":"fictional.pdf","sha256":"a","doc_type":"default"}])
    monkeypatch.setattr(workflow,"snapshot_exists",lambda *_:True)
    monkeypatch.setattr(workflow,"load_analysis",lambda *_:(old,{}))
    calls = []
    def analyze(*args, **kwargs):
        calls.append(kwargs["sources"])
        return fresh
    result, actual_manual, _ = workflow.analyze_with_parent(SimpleNamespace(analyze_archive=analyze),task,parent,
        [SimpleNamespace(id="f1",abs_path="fictional.pdf",doc_type="default")],
        {"workflow_case_type":"civil","extraction":{"mode":"workstation_agent"}},"fictional-org",lambda _:None)
    assert len(calls) == 1 and old.fields == saved
    assert result.fields["_field_normalization_version"] == STRICT_EVIDENCE_VERSION
    assert "_field_normalization_version" not in actual_manual
    if explicit_manual:
        assert result.fields["结案小结"] == "" and result.fields["合同号"] == "人工历史值"
    else:
        assert "结案小结" not in result.fields and actual_manual == {}
