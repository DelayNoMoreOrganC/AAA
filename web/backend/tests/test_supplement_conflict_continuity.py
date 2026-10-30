"""Unresolved conflicts persist across additions, without rewriting history."""
import copy
from types import SimpleNamespace

import pytest

from app.core.v4_bridge import init_v4_path
init_v4_path()
import archive_pipeline as ap
from app.services import task_workflow as workflow
from app.services.task_workflow import analysis_issues, unresolved_issues
from tests.test_task_workflow import fixture_analysis


def source(tmp_path, number):
    return dict(file_id=str(number), path=str(tmp_path / f"fictional-{number}.pdf"),
                filename=f"fictional-{number}.pdf", sha256=str(number), pages=1, doc_type="default")


def extend(previous, rows, new, parent_issues, monkeypatch, value=None, *, changed=False):
    old = copy.deepcopy(previous)
    current = rows + [new]
    if changed:
        current = [dict(row, sha256="replacement") for row in rows] + [new]
    parent = SimpleNamespace(id=1, case_id="fictional", source_manifest=rows, manual_fields={}, issues=parent_issues)
    task = SimpleNamespace(source_manifest=current, case_id='fictional')
    files = [SimpleNamespace(id=row["file_id"], abs_path=row["path"], doc_type="default") for row in current]
    calls = []
    def analyze(case_type, *, sources, **kwargs):
        calls.append([s.path for s in sources])
        result = fixture_analysis(new["path"])
        result.fields = {"承办律师": value} if value else {}
        return result
    monkeypatch.setattr(workflow, "snapshot_exists", lambda *_: True)
    monkeypatch.setattr(workflow, "load_analysis", lambda *_: (copy.deepcopy(previous), {}))
    engine = SimpleNamespace(analyze_archive=analyze, compute_found_seqs=ap.compute_found_seqs,
                             compute_missing_items=ap.compute_missing_items)
    result, _, conflicts = workflow.analyze_with_parent(engine, task, parent, files,
        {"workflow_case_type": "civil"}, "fictional-org", lambda _: None)
    assert previous == old
    return result, conflicts + analysis_issues(result, current), calls


@pytest.mark.parametrize("acknowledged", [False, True])
def test_second_unrelated_supplement_retains_conflict_id_and_decision(tmp_path, monkeypatch, acknowledged):
    first, second, third = [source(tmp_path, n) for n in range(1, 4)]
    original = fixture_analysis(first["path"], {"承办律师": "虚构甲"})
    intermediate, issues, calls = extend(original, [first], second, [], monkeypatch, "虚构乙")
    pending = [x for x in issues if x["kind"] == "field_conflict"]
    assert len(pending) == 1
    if acknowledged:
        intermediate.fields["_issue_decisions"] = {pending[0]["id"]: {"action": "acknowledged", "reason": "人工核对保留虚构甲"}}
    before = copy.deepcopy(issues)
    result, final, later_calls = extend(intermediate, [first, second], third, issues, monkeypatch)
    retained = [x for x in final if x["kind"] == "field_conflict"]
    assert retained == pending and issues == before
    assert result.fields["承办律师"] == "虚构甲"
    assert [x for x in unresolved_issues(final, result.fields) if x["kind"] == "field_conflict"] == pending
    if acknowledged:
        assert result.fields['_issue_decisions']==intermediate.fields['_issue_decisions']
    assert len(result.doc_spans) == len(result.source_paths) == 3
    assert calls + later_calls == [[second["path"]], [third["path"]]]


def test_changed_source_does_not_inherit_obsolete_conflict(tmp_path, monkeypatch):
    first, second = [source(tmp_path, n) for n in (1, 2)]
    previous = fixture_analysis(first["path"], {"承办律师": "虚构甲"})
    obsolete = workflow.issue("field_conflict", "旧材料矛盾", detail={"field": "承办律师", "saved": "虚构甲", "new": "虚构乙"})
    result, issues, calls = extend(previous, [first], second, [obsolete], monkeypatch, "虚构丙", changed=True)
    assert result.fields["承办律师"] == "虚构丙"
    assert calls == [[first["path"], second["path"]]]
    assert not any(x["id"] == obsolete["id"] for x in issues)


def test_new_supplement_with_same_conflicting_value_needs_its_own_review(tmp_path, monkeypatch):
    first, second, third = [source(tmp_path, n) for n in range(1, 4)]
    original = fixture_analysis(first["path"], {"承办律师": "虚构甲"})
    intermediate, issues, _ = extend(original, [first], second, [], monkeypatch, "虚构乙")
    old = [x for x in issues if x["kind"] == "field_conflict"][0]
    intermediate.fields["_issue_decisions"] = {old["id"]: {
        "action": "acknowledged", "reason": "仅核对过第一份补件"}}
    result, final, calls = extend(intermediate, [first, second], third, issues, monkeypatch, "虚构乙")
    conflicts = [x for x in final if x["kind"] == "field_conflict"]
    unresolved = [x for x in unresolved_issues(final, result.fields) if x["kind"] == "field_conflict"]
    assert len(conflicts) == len(unresolved) == 2
    new=next(row for row in unresolved if row['id']!=old['id'])
    assert new['detail']['evidence_version']!=old['detail']['evidence_version']
    assert result.fields["承办律师"] == "虚构甲"
    assert calls == [[third["path"]]]
