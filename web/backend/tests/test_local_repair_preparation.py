"""A maintenance repair is evidence-backed machine work, never a human choice."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("prepare_local_repair", ROOT / "scripts/prepare_local_repair.py")
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


@pytest.fixture
def values(monkeypatch):
    # Production evidence verification is independently exercised with actual
    # source chains. Here the seam isolates publication's preservation gates.
    import app.services.field_assurance as evidence
    monkeypatch.setattr(evidence, "field_assurance", lambda *a, **kw:
        {"status": "source_supported", "anchors": [{"file_id": "fiction", "page": 1}]})
    before = {"审理法院": "人工确认法院", "_provenance": {"审理法院": [{"method": "human", "value": "人工确认法院"}]},
              "_document_classifications": {"unit": {"catalog_seq": 7}}, "_issue_decisions": {"q": {"action": "pending"}}}
    after = deepcopy(before)
    after["委托人"] = "虚构委托人"
    return before, after, {"审理法院": "人工确认法院"}


def test_supported_automatic_fact_keeps_manual_values_and_decisions(values):
    before, after, manual = values
    assert list(repair.validate_changes(before, after, manual, [])) == ["委托人"]


@pytest.mark.parametrize("field,value", [("审理法院", "别的法院"), ("审理法院", "")])
def test_repair_cannot_replace_or_clear_manual_input(values, field, value):
    before, after, manual = values
    after[field] = value
    with pytest.raises(ValueError, match="manual_value_changed"):
        repair.validate_changes(before, after, manual, [])


@pytest.mark.parametrize("field", ["_document_classifications", "_classification_digest", "_issue_decisions", "_field_conflicts", "_field_decisions"])
def test_automatic_repair_cannot_change_decisions(values, field):
    before, after, manual = values
    after[field] = {"invented": True}
    with pytest.raises(ValueError, match="saved_decision_changed"):
        repair.validate_changes(before, after, manual, [])


def test_cannot_label_new_machine_fact_as_human(values):
    before, after, manual = values
    after["_provenance"]["委托人"] = [{"method": "human", "value": after["委托人"]}]
    with pytest.raises(ValueError, match="invent_human_confirmation"):
        repair.validate_changes(before, after, manual, [])


@pytest.mark.parametrize("status,anchors,error", [
    ("unverified", [], "unsupported_repaired_fact"),
    ("human_confirmed", [], "unsupported_repaired_fact"),
    ("source_supported", [], "repair_source_unlocatable"),
])
def test_each_changed_fact_needs_valid_current_sources(values, monkeypatch, status, anchors, error):
    import app.services.field_assurance as evidence
    monkeypatch.setattr(evidence, "field_assurance", lambda *a, **kw: {"status": status, "anchors": anchors})
    with pytest.raises(ValueError, match=error):
        repair.validate_changes(*values, [])


@pytest.fixture
def publication(tmp_path, monkeypatch):
    import json
    import sqlite3
    import sys
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import Base, Case, ArchiveTask, TaskStatus
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import publish_local_repair as publisher
    engine = create_engine("sqlite:///" + str(tmp_path / "archive.db"))
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Case(id="fiction-case", org_id="fiction-org", title="虚构", case_type="civil"))
        session.add(ArchiveTask(id=1, case_id="fiction-case", status=TaskStatus.awaiting_review,
            revision=2, fields={"原值": "保留"}, manual_fields={"原值": "保留"}, artifacts={"path": "old.pdf"}))
        session.commit()
    engine.dispose()
    parent_work = tmp_path / "orgs/fiction-org/cases/fiction-case/tasks/1"
    parent_work.mkdir(parents=True)
    (parent_work / "analysis_snapshot.json").write_text('{"original":true}', encoding="utf-8")
    with sqlite3.connect(tmp_path / "archive.db") as db:
        db.row_factory = sqlite3.Row
        parent = dict(db.execute("SELECT * FROM tasks WHERE id=1").fetchone())
        case = dict(db.execute("SELECT * FROM cases").fetchone())
    plan = {"parent_task_id": 1, "case_id": "fiction-case", "org_id": "fiction-org",
            "parent_digest": repair.value_digest(parent), "case_digest": repair.value_digest(case),
            "report_path": str(tmp_path / "report.json"), "report_sha256": "a" * 64,
            "snapshot": {"fields": {"原值": "保留", "新值": "来源支持"}, "workflow": {"revision": 1}},
            "issues": [], "catalog_status": []}
    monkeypatch.setattr(publisher, "prepare", lambda *a, **kw: deepcopy(plan))
    return publisher, tmp_path, plan, parent


def test_offline_publication_adds_child_and_preserves_parent_history(publication):
    import json
    import sqlite3
    publisher, data, plan, parent = publication
    result = publisher.publish(data, plan, check_stopped=lambda: None)
    with sqlite3.connect(data / "archive.db") as db:
        db.row_factory = sqlite3.Row
        assert dict(db.execute("SELECT * FROM tasks WHERE id=1").fetchone()) == parent
        child = dict(db.execute("SELECT * FROM tasks WHERE id=?", (result["task_id"],)).fetchone())
    assert child["parent_task_id"] == 1
    assert child["revision"] == 1 and child["status"] == "awaiting_review"
    assert child["manual_fields"] == parent["manual_fields"]
    assert json.loads(child["artifacts"]) is None and not child["output_pdf"]
    assert child["requested_operation"] == "draft"
    assert (data / "orgs/fiction-org/cases/fiction-case/tasks/2/analysis_snapshot.json").is_file()


@pytest.mark.parametrize("failure", ["running", "write_error", "source_changed"])
def test_publication_failure_never_changes_parent_or_adds_visible_task(publication, monkeypatch, failure):
    import sqlite3
    publisher, data, plan, parent = publication
    def stopped():
        if failure == "running":
            raise ValueError("running")
    if failure == "write_error":
        import app.services.analysis_snapshot as snapshots
        monkeypatch.setattr(snapshots, "_atomic_write", lambda *a: (_ for _ in ()).throw(OSError("disk error")))
    if failure == "source_changed":
        monkeypatch.setattr(publisher, "prepare", lambda *a: dict(plan, source_version="changed"))
    with pytest.raises((ValueError, OSError)):
        publisher.publish(data, plan, check_stopped=stopped)
    with sqlite3.connect(data / "archive.db") as db:
        db.row_factory = sqlite3.Row
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert dict(db.execute("SELECT * FROM tasks WHERE id=1").fetchone()) == parent
