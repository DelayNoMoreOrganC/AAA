"""Per-invocation metrics must not report a parent task's latency as new work."""
from types import SimpleNamespace

import pytest

from app.core.v4_bridge import archive_pipeline
from app.services import task_workflow as workflow
from app.services.task_manager import safe_log_line
from tests.test_task_workflow import fixture_analysis

pipeline = archive_pipeline()


@pytest.mark.parametrize("supplement", [False, True])
def test_reuse_and_supplement_never_relabel_previous_runtime(monkeypatch, supplement):
    old = {"file_id": "old", "path": "old.pdf", "sha256": "a", "doc_type": "default", "pages": 1}
    new = {"file_id": "new", "path": "new.pdf", "sha256": "b", "doc_type": "default", "pages": 1}
    previous = fixture_analysis("old.pdf")
    previous.fields["_analysis_metrics"] = {"scope": "this_analysis_call", "analysis_seconds": 1200}
    previous.fields["_agent_summary"] = {"pages_checked": 1, "local": True,
        "this_run_metrics": {"model_requests": 50, "model_seconds": 1000}}
    delta = fixture_analysis("new.pdf")
    delta.fields["_analysis_metrics"] = {"scope": "this_analysis_call", "analysis_seconds": 10}
    delta.fields["_agent_summary"] = {"pages_checked": 1, "local": True,
        "this_run_metrics": {"model_requests": 2, "model_seconds": 8}}
    monkeypatch.setattr(workflow, "snapshot_exists", lambda *_: True)
    monkeypatch.setattr(workflow, "load_analysis", lambda *_: (previous, {}))
    calls = []
    def analyze(*args, **kwargs):
        calls.append(kwargs["sources"])
        return delta
    engine = SimpleNamespace(analyze_archive=analyze, compute_found_seqs=pipeline.compute_found_seqs,
                             compute_missing_items=pipeline.compute_missing_items)
    rows = [old, new] if supplement else [old]
    parent = SimpleNamespace(id=1, case_id="fictional", manual_fields={}, source_manifest=[old])
    task = SimpleNamespace(source_manifest=rows)
    files = [SimpleNamespace(id=r["file_id"], abs_path=r["path"], doc_type=r["doc_type"]) for r in rows]
    result, _, _ = workflow.analyze_with_parent(engine, task, parent, files,
        {"workflow_case_type": "civil"}, "fictional-org", lambda _: None)
    if supplement:
        assert len(calls) == 1
        assert result.fields["_analysis_metrics"]["analysis_seconds"] == 10
        assert result.fields["_agent_summary"]["this_run_metrics"] == {"model_requests": 2, "model_seconds": 8}
    else:
        assert calls == []
        assert result.fields["_analysis_metrics"] == {"scope": "this_analysis_call", "analysis_status": "snapshot_reused"}
        assert "this_run_metrics" not in result.fields["_agent_summary"]


@pytest.mark.parametrize("legacy_parent", [False, True])
@pytest.mark.parametrize("fresh_metrics", [False, True])
def test_historical_manual_diagnostics_never_override_reanalysis(monkeypatch, legacy_parent, fresh_metrics):
    old = {"file_id": "old", "path": "fictional.pdf", "sha256": "old", "doc_type": "default", "pages": 1}
    changed = dict(old, sha256="changed")
    previous = fixture_analysis("fictional.pdf", {"委托人": "虚构已核对委托人", "合同号": "人工核对-001"})
    previous.fields["_analysis_metrics"] = {"scope": "this_analysis_call", "analysis_seconds": 1200}
    previous.fields["_agent_summary"] = {"pages_checked": 99,
        "this_run_metrics": {"model_requests": 50, "model_seconds": 1000}}
    fresh = fixture_analysis("fictional.pdf", {"委托人": "虚构新候选值"})
    if fresh_metrics:
        fresh.fields["_analysis_metrics"] = {"scope": "this_analysis_call", "analysis_seconds": 10}
        fresh.fields["_agent_summary"] = {"pages_checked": 1,
            "this_run_metrics": {"model_requests": 2, "model_seconds": 8}}
    monkeypatch.setattr(workflow, "snapshot_exists", lambda *_: True)
    monkeypatch.setattr(workflow, "load_analysis", lambda *_: (previous, {}))
    calls = []

    def analyze(*args, **kwargs):
        calls.append(kwargs["sources"])
        return fresh

    parent = SimpleNamespace(id=1, case_id="fictional",
        source_manifest=None if legacy_parent else [old],
        manual_fields={} if legacy_parent else dict(previous.fields))
    task = SimpleNamespace(source_manifest=[changed])
    files = [SimpleNamespace(id="old", abs_path="fictional.pdf", doc_type="default")]
    result, manual, conflicts = workflow.analyze_with_parent(
        SimpleNamespace(analyze_archive=analyze), task, parent, files,
        {"workflow_case_type": "civil"}, "fictional-org", lambda _: None)
    assert len(calls) == 1
    assert result.fields["委托人"] == manual["委托人"] == "虚构已核对委托人"
    assert result.fields["合同号"] == manual["合同号"] == "人工核对-001"
    assert any(entry["kind"] == "field_conflict" for entry in conflicts)
    assert "_analysis_metrics" not in manual and "_agent_summary" not in manual
    if fresh_metrics:
        assert result.fields["_analysis_metrics"]["analysis_seconds"] == 10
        assert result.fields["_agent_summary"] == {"pages_checked": 1,
            "this_run_metrics": {"model_requests": 2, "model_seconds": 8}}
    else:
        assert "_analysis_metrics" not in result.fields
        assert "_agent_summary" not in result.fields
    assert previous.fields["_analysis_metrics"]["analysis_seconds"] == 1200


@pytest.mark.parametrize("line", [
    "[性能] source_ingest: 120.500s; status=completed",
    "[性能] field_agent: 120.500s; status=failed",
    "[性能] analysis: 125.001s; status=completed",
    "归档助理本次计时：model_requests=52 model_failed_requests=1 model_seconds=1000.000 max_request_seconds=25.500 agent_seconds=1001.500",
])
def test_fixed_numeric_timings_survive_log_filter_but_cannot_carry_content(line):
    assert safe_log_line(line) == line
    assert safe_log_line(line + " PRIVATE_DOCUMENT_SENTINEL") is None
    assert safe_log_line(line + "\nPRIVATE_DOCUMENT_SENTINEL") is None
    assert safe_log_line(line.replace("120.500", "NaN").replace("125.001", "-1.000").replace("52", "secret")) is None
