"""Fictional runner safety/false-pass regressions; no server or model calls."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("five_type_runner_test", scripts / "acceptance_five_types_current.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_fixture(runner, root, *, name="sample.pdf", relative="case/sample.pdf"):
    (root / "case").mkdir(parents=True)
    source = root / "case/sample.pdf"
    source.write_bytes(b"fictional-source-only")
    case = {"synthetic": True, "kind": "civil", "title": "虚构合成验收", "stage": "first_instance",
            "inputs": [{"relative_path": relative, "name": name, "pages": 1, "sha256": runner.base.digest(source)}]}
    metadata = root / "case/run.json"
    metadata.write_text(json.dumps(case), encoding="utf-8")
    manifest = {"synthetic": True, "cases": [{"kind": "civil", "run_json": "case/run.json", "run_sha256": runner.base.digest(metadata)}]}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return metadata


def test_fixture_requires_manifest_metadata_hash(runner, monkeypatch, tmp_path):
    metadata = make_fixture(runner, tmp_path)
    monkeypatch.setattr(runner, "FIXTURES", tmp_path)
    assert runner.fixture("civil")[0]["synthetic"]
    metadata.write_text(metadata.read_text()+" ", encoding="utf-8")
    with pytest.raises(runner.base.CheckFailed, match="FIXTURE_METADATA_HASH_CHANGED"):
        runner.fixture("civil")


@pytest.mark.parametrize("name,relative,code", [
    ("../customer.pdf", "case/sample.pdf", "FIXTURE_INPUT_INVALID"),
    ("sample.pdf", "../other.pdf", "FIXTURE_INPUT_OUTSIDE_ROOT"),
])
def test_fixture_rejects_traversal_before_source_read(runner, monkeypatch, tmp_path, name, relative, code):
    make_fixture(runner, tmp_path, name=name, relative=relative)
    monkeypatch.setattr(runner, "FIXTURES", tmp_path)
    with pytest.raises(runner.base.CheckFailed, match=code):
        runner.fixture("civil")


def identity_task():
    state = {"task_id": 5, "case_id": "synthetic-case", "code_identity": {"normalization_version": "strict-fields-test"}}
    task = {"id": 5, "case_id": "synthetic-case", "revision": 1, "source_version": "source-v1", "source_changed": False,
            "fields": {"_field_normalization_version": "strict-fields-test"}, "execution_profile": {
                "processing_mode": "deepseek_cloud", "provider": "deepseek", "model": "deepseek-flash",
                "workflow": "document_two_stage", "cloud_consent": True, "authorized_source_version": "source-v1"}}
    return task, state, {"revision": 1, "source_changed": False}


@pytest.mark.parametrize("change,code", [
    (lambda t,d: d.update(revision=2), "DOCUMENT_REVISION_OR_SOURCE_MISMATCH"),
    (lambda t,d: d.update(source_changed=True), "DOCUMENT_REVISION_OR_SOURCE_MISMATCH"),
    (lambda t,d: t["fields"].update(_field_normalization_version="old"), "TASK_NORMALIZATION_VERSION_MISMATCH"),
    (lambda t,d: t["execution_profile"].update(authorized_source_version="old"), "FROZEN_PROFILE_OR_SOURCE_AUTHORIZATION_MISMATCH"),
    (lambda t,d: t["fields"].update(_provenance={"field": [{"method": "human"}]}), "HUMAN_FIELD_PROVENANCE_PRESENT"),
])
def test_stale_or_manual_result_cannot_pass_current_run(runner, change, code):
    task, state, docs = identity_task()
    runner.verify_task_identity(task, state, docs)
    change(task, docs)
    with pytest.raises(runner.base.CheckFailed, match=code):
        runner.verify_task_identity(task, state, docs)


def test_correct_alias_cannot_hide_wrong_primary_value(runner):
    wanted = {"field": "委托人名称", "value": "虚构甲", "aliases": ["委托人"], "source": {"file": "a", "page": 1}}
    assert not runner.field_check(wanted, {"委托人名称": "虚构乙", "委托人": "虚构甲"})["passed"]
    assert runner.field_check(wanted, {"委托人": "虚构甲"})["passed"]
    assert runner.field_check(wanted, {"委托人": "虚构甲"})["provenance_check"] == "recorded_not_independently_verified"


def test_technical_and_subset_pass_do_not_claim_full_semantic_acceptance(runner):
    report = {"technical_delivery_passed": True, "known_subset_passed": True, "status": "awaiting_review"}
    runner.mark_assessment(report)
    assert report["automated_checks_passed"] is True
    assert report["overall_passed"] is False and report["independent_semantic_review"] == "pending"
    assert report["server_failed"] is False


def test_classification_match_cannot_hide_swallowed_adjacent_page(runner):
    wanted = {"file": "synthetic.pdf", "page_start": 2, "page_end": 2, "doc_type": "judgment", "catalog_seq": 14}
    unit = {"file_id": "synthetic-file", "page_start": 1, "page_end": 2, "doc_type": "judgment", "catalog_seq": 14}
    assert not runner.document_check(wanted, [unit], "synthetic-file")["passed"]
    unit["page_start"] = 2
    assert runner.document_check(wanted, [unit], "synthetic-file")["passed"]


def test_reported_server_duration_not_runner_wait_or_model_duration(runner):
    result = runner.server_timing({"created_at": "2026-10-24T00:00:00+00:00", "finished_at": "2026-10-24T00:01:02+00:00"})
    assert result["server_elapsed_seconds"] == 62
    assert result["server_duration_scope"] == "reported_task_lifecycle_not_model_only"
    assert runner.server_timing({"created_at": "invalid", "finished_at": None})["server_elapsed_seconds"] is None


def prepare_run(runner, monkeypatch, tmp_path, *, existing_task=False):
    directory = tmp_path / "runs/civil"
    directory.mkdir(parents=True)
    identity = {"normalization_version": "strict-fields-test", "recognition_signature": "test"}
    state = {"fixture_hash": "test-hash", "kind": "civil", "source_alias": "civil", "title": "虚构验收",
             "case_id": "synthetic-case", "user_id": "synthetic-user", "org_id": "synthetic-org",
             "uploaded": [{"relative_path": "fixture.pdf", "file_id": "synthetic-file", "sha256": "hash"}],
             "code_identity": identity, "idempotency_key": "synthetic-only"}
    if existing_task:
        state.update(task_id=5, started=100, terminal_observed_at=120)
    runner.write(directory / "state.json", state)
    specification = {"title": "虚构验收", "kind": "civil", "stage": "first_instance",
                     "inputs": [{"relative_path": "fixture.pdf"}]}
    monkeypatch.setattr(runner, "OUT", tmp_path)
    monkeypatch.setattr(runner, "fixture", lambda kind: (specification, "test-hash"))
    monkeypatch.setattr(runner, "health", lambda *a, **k: identity)
    monkeypatch.setattr(runner.base, "worker_memory", lambda pid: {"status": "synthetic_not_sampled", "scope": "worker_since_service_start_not_case_peak"})
    calls = []
    class Client:
        session = SimpleNamespace(close=lambda: None)
        def login(self):
            pass
        def request(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            if path == "/api/auth/me":
                return {"username": "gd_acceptance", "id": "synthetic-user", "org_id": "synthetic-org"}
            if path == "/api/settings":
                return {"processing_mode": "deepseek_cloud", "deepseek_key_configured": True, "external_ai_allowed": True}
            if path == "/api/cases/synthetic-case":
                return {"title": "虚构验收", "case_type": "civil", "stage": "first_instance", "files": [{"id": "synthetic-file"}]}
            assert method == "POST" and path.endswith("/generate") and kwargs["renew"] is False
            raise runner.base.CheckFailed("HTTP_OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY")
    monkeypatch.setattr(runner.base, "Client", Client)
    args = SimpleNamespace(kind="civil", expected_pid=999, timeout_seconds=2)
    return args, directory, calls


def test_unknown_generation_post_stays_blocked_on_reinvoke(runner, monkeypatch, tmp_path):
    args, directory, calls = prepare_run(runner, monkeypatch, tmp_path)
    with pytest.raises(runner.base.CheckFailed, match="HTTP_OUTCOME_UNKNOWN"):
        runner.run(args)
    assert json.loads((directory/"state.json").read_text())["generate_pending"] is True
    with pytest.raises(runner.base.CheckFailed, match="GENERATE_OUTCOME_UNKNOWN_NO_SECOND_POST"):
        runner.run(args)
    assert len([c for c in calls if c[0] == "POST"]) == 1
    before = list(directory.glob("report-before-*.json"))
    assert len(before) == 1 and json.loads(before[0].read_text())["failure_code"] == "HTTP_OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY"


def test_semantic_failure_retains_technical_success_and_original_duration(runner, monkeypatch, tmp_path):
    args, directory, calls = prepare_run(runner, monkeypatch, tmp_path, existing_task=True)
    task = {"id": 5, "status": "awaiting_review", "phase": "draft_ready", "fields": {}, "error": ""}
    monkeypatch.setattr(runner.base, "wait_for_automatic_draft", lambda *a: task)
    def verify(*args):
        args[-1].update(technical_delivery_passed=True, known_subset_passed=False, document_checks=[{"passed": False}])
    monkeypatch.setattr(runner, "verify", verify)
    with pytest.raises(runner.base.CheckFailed, match="RECOGNITION_EXPECTATION_MISMATCH_SERVER_DRAFT_RETAINED"):
        runner.run(args)
    report = json.loads((directory/"report.json").read_text())
    assert report["technical_delivery_passed"] is True and report["known_subset_passed"] is False
    assert report["server_failed"] is False and report["overall_passed"] is False
    assert report["elapsed_since_generate_seconds"] == 20 and not [c for c in calls if c[0] == "POST"]


def test_late_verification_failure_preserves_obtained_recognition_evidence(runner, monkeypatch, tmp_path):
    args, directory, _ = prepare_run(runner, monkeypatch, tmp_path, existing_task=True)
    monkeypatch.setattr(runner.base, "wait_for_automatic_draft", lambda *a: {"id": 5, "status": "awaiting_review", "phase": "draft_ready", "fields": {}})
    def verify(*args):
        args[-1].update(known_subset_passed=True, document_checks=[{"passed": True}])
        raise runner.base.CheckFailed("SOURCE_PIXELS_NOT_EXACTLY_ONCE")
    monkeypatch.setattr(runner, "verify", verify)
    with pytest.raises(runner.base.CheckFailed, match="SOURCE_PIXELS"):
        runner.run(args)
    report = json.loads((directory/"report.json").read_text())
    assert report["known_subset_passed"] is True and report["document_checks"] == [{"passed": True}]
    assert report["technical_delivery_passed"] is False and report["failure_code"] == "SOURCE_PIXELS_NOT_EXACTLY_ONCE"


def test_preflight_failure_is_reported_without_any_http(runner, monkeypatch, tmp_path):
    args, directory, calls = prepare_run(runner, monkeypatch, tmp_path)
    def fail(kind):
        raise runner.base.CheckFailed("FIXTURE_HASH_CHANGED")
    monkeypatch.setattr(runner, "fixture", fail)
    with pytest.raises(runner.base.CheckFailed, match="FIXTURE_HASH_CHANGED"):
        runner.run(args)
    assert not calls
    assert json.loads((directory/"report.json").read_text())["failure_code"] == "FIXTURE_HASH_CHANGED"


def test_concurrent_runner_is_blocked_and_os_lock_reusable(runner, tmp_path):
    with runner.run_lock(tmp_path):
        with pytest.raises(runner.base.CheckFailed, match="RUNNER_ALREADY_ACTIVE"):
            with runner.run_lock(tmp_path):
                pytest.fail("second runner entered")
    with runner.run_lock(tmp_path):
        pass


def test_output_path_requires_exact_authenticated_task_revision(runner, tmp_path):
    state = {"org_id": "synthetic-org", "case_id": "synthetic-case", "task_id": 5}
    saved = tmp_path / "synthetic-org/synthetic-case/5/r1/render-test"
    saved.mkdir(parents=True)
    task = {"revision": 1, "fields": {"_saved_to": str(saved)}}
    assert runner.saved_directory(task, state) == saved
    task["revision"] = 2
    with pytest.raises(runner.base.CheckFailed, match="OUTPUT_DIRECTORY_WRONG_TASK_OR_REVISION"):
        runner.saved_directory(task, state)
