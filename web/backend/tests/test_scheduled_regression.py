"""Synthetic ledger/transport only: no customer sources, credentials or model."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts import acceptance_scheduled_regression as gate


@pytest.fixture
def setup_gate(tmp_path, monkeypatch):
    data = tmp_path / "private"
    monkeypatch.setattr(gate, "DATA", data)
    identity = {"recognition_signature": "a" * 64, "normalization_version": gate.REQUIRED_VERSION}
    clock = {"day": "2026-10-24"}
    monkeypatch.setattr(gate, "expected_signature", lambda: dict(identity))
    monkeypatch.setattr(gate, "beijing_day", lambda: clock["day"])
    baseline = tmp_path / "public-baseline.json"
    baseline.write_text(json.dumps({"status": "automatic_draft_delivered", "technical_checks_passed": True,
        "source_alias": "case48", "source_sha256": gate.SOURCE_IDENTITIES["case48"][1],
        "field_normalization_version": "strict-fields-v3", "real_model_requested": True,
        "metrics": {"model_requests": 29}, "ended_at": "2026-10-22T18:48:15Z"}), encoding="utf-8")
    monkeypatch.setattr(gate, "LEGACY_BASELINE", baseline)
    health = {"status": "ok", "application": "gd-workstation", "pid": 4242,
        **identity, "active_archive_tasks": 0, "processing_busy": False}
    events, attempted, preflight = [], [], []
    class Client:
        def __init__(self):
            events.append("client")
            self.session = SimpleNamespace(close=lambda: events.append("close"))
        def login(self):
            pytest.fail("Gate preflight must not read credentials")
        def request(self, method, path, **kwargs):
            assert (method, path, kwargs) == ("GET", "/api/health", {"renew": False})
            events.append("health")
            return deepcopy(health)
    helper = SimpleNamespace(DATA=data, EXPECTED_NORMALIZATION_VERSION=gate.REQUIRED_VERSION, Client=Client,
        SOURCES={name: (tmp_path / (name + ".pdf"), gate.SOURCE_IDENTITIES[name][0]) for name in gate.ALIASES})
    def successful(args):
        assert args.adopt_created_case is False
        assert args.expected_source_sha256 == gate.SOURCE_IDENTITIES[args.source][1]
        assert args.expected_pid == 4242 and 4 <= len(args.run_id) <= 64
        attempted.append(args.source)
        # Fake helper may print data, but none may escape gate stdout.
        print("PRIVATE_HELPER_PATH PRIVATE_ERROR_BODY")
        report = {"source_alias": args.source, "source_pages": gate.SOURCE_IDENTITIES[args.source][0],
            "source_sha256": gate.SOURCE_IDENTITIES[args.source][1], "status": "automatic_draft_delivered",
            "technical_checks_passed": True, "field_normalization_version": gate.REQUIRED_VERSION,
            "metrics": {"model_requests": 3, "model_seconds": 1.25, "PRIVATE_VALUE": "PRIVATE_BODY"},
            "cost": {"amount": 0.1, "currency": "CNY"}, "private_report": "PRIVATE_PATH"}
        directory = data / "auto-regression" / args.run_id / args.source
        directory.mkdir(parents=True)
        (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")
    helper.run = successful
    monkeypatch.setattr(gate, "_helper", lambda: helper)
    real_preflight = gate._preflight_source
    monkeypatch.setattr(gate, "_preflight_source", lambda helper, alias: preflight.append(alias))
    return SimpleNamespace(data=data, identity=identity, health=health, clock=clock, events=events,
        attempted=attempted, preflight=preflight, helper=helper, real_preflight=real_preflight)


def test_default_status_never_constructs_client_reads_source_or_creates_ledger(setup_gate, monkeypatch, capsys):
    s = setup_gate
    monkeypatch.setattr(gate, "_helper", lambda: pytest.fail("Default status must not load helper/client/credentials"))
    assert gate.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "status_only" and result["http_requests"] == 0
    assert result["credentials_read"] is False and result["sources_read"] is False
    assert result["eligibility"] == "ELIGIBLE_RECOGNITION_CHANGED"
    assert not s.data.exists() and not s.events and not s.preflight


def test_success_reserves_before_each_source_and_runs_serially_once(setup_gate, capsys):
    s = setup_gate
    original = s.helper.run
    def checked(args):
        rows = gate._read_rows(s.data / gate.LEDGER_NAME)
        assert len(rows) == 2 and rows[-1]["status"] == "running"
        with sqlite3.connect(s.data / gate.LEDGER_NAME) as db:
            assert db.execute("SELECT status FROM regression_sources WHERE source_alias=?", (args.source,)).fetchone()[0] == "started"
        if args.source == "case85":
            assert s.attempted == ["case48"]
        original(args)
    s.helper.run = checked
    result = gate.run(4242)
    assert result["status"] == "succeeded" and s.attempted == ["case48", "case85"]
    assert s.preflight == ["case48", "case85", "case48", "case85"]
    assert [r["metrics"]["model_requests"] for r in result["sources"]] == [3, 3]
    assert result["sources"][0]["cost"] == {"available": True, "amount": .1, "currency": "CNY"}
    assert "PRIVATE" not in json.dumps(result) and capsys.readouterr().out == ""


def test_daily_quota_blocks_even_new_signature_before_health_or_source_read(setup_gate):
    s = setup_gate
    gate.reserve(s.clock["day"], s.identity)
    s.identity["recognition_signature"] = "b" * 64
    with pytest.raises(gate.GateStopped, match="DAILY_QUOTA_CONSUMED"):
        gate.run(4242)
    assert not s.events and not s.preflight and not s.attempted


def test_same_signature_is_blocked_next_day_even_if_previous_outcome_unknown(setup_gate):
    s = setup_gate
    gate.reserve(s.clock["day"], s.identity)  # Simulate process death immediately after reservation.
    s.clock["day"] = "2026-10-25"
    with pytest.raises(gate.GateStopped, match="SIGNATURE_ALREADY_CONSUMED"):
        gate.run(4242)
    assert not s.events and not s.attempted


def test_successful_baseline_requires_changed_signature_on_next_day(setup_gate):
    s = setup_gate
    gate.run(4242)
    s.clock["day"] = "2026-10-25"
    with pytest.raises(gate.GateStopped, match="SIGNATURE_ALREADY_CONSUMED"):
        gate.run(4242)
    s.identity["recognition_signature"] = s.health["recognition_signature"] = "b" * 64
    gate.run(4242)
    assert s.attempted == ["case48", "case85", "case48", "case85"]


def test_atomic_daily_reservation_blocks_concurrent_process_equivalent_connections(setup_gate):
    s = setup_gate
    def reserve(letter):
        try:
            return gate.reserve(s.clock["day"], {**s.identity, "recognition_signature": letter * 64})
        except gate.GateStopped as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ("a", "b")))
    assert sum(value.startswith("scheduled-") for value in results) == 1
    assert results.count("DAILY_QUOTA_CONSUMED") == 1
    assert len(gate._read_rows(s.data / gate.LEDGER_NAME)) == 2


@pytest.mark.parametrize("outcome", ["exception", "unknown", "wrong_version", "wrong_hash", "interrupt"])
def test_failed_unknown_or_interrupted_attempt_consumes_quota_and_never_starts_second_source(setup_gate, outcome, capsys):
    s = setup_gate
    original = s.helper.run
    def failed(args):
        if outcome == "unknown":
            s.attempted.append(args.source)
            return  # Missing report is not successful.
        if outcome == "interrupt":
            s.attempted.append(args.source)
            raise KeyboardInterrupt("PRIVATE_INTERRUPTION")
        original(args)
        if outcome == "exception": raise RuntimeError("PRIVATE_EXCEPTION_RESPONSE")
        path = s.data / "auto-regression" / args.run_id / args.source / "report.json"
        report = json.loads(path.read_text())
        report["field_normalization_version" if outcome == "wrong_version" else "source_sha256"] = "PRIVATE_WRONG"
        path.write_text(json.dumps(report))
    s.helper.run = failed
    assert gate.main(["--run", "--expected-pid", "4242"]) == 1
    output = capsys.readouterr().out
    assert "PRIVATE" not in output and "ROUND_INCOMPLETE_QUOTA_CONSUMED" in output
    assert s.attempted == ["case48"]
    assert gate._read_rows(s.data / gate.LEDGER_NAME)[-1]["status"] == "failed_or_unknown"
    s.clock["day"] = "2026-10-25"
    with pytest.raises(gate.GateStopped, match="SIGNATURE_ALREADY_CONSUMED"):
        gate.run(4242)
    assert s.attempted == ["case48"]


@pytest.mark.parametrize("key,value", [
    ("pid", 1), ("pid", None), ("recognition_signature", "b" * 64),
    ("normalization_version", "strict-fields-v3"), ("active_archive_tasks", 1),
    ("active_archive_tasks", None), ("active_archive_tasks", False),
    ("processing_busy", True), ("processing_busy", None), ("application", "other"),
])
def test_stale_busy_or_incomplete_health_stops_before_source_read_and_reservation(setup_gate, key, value):
    s = setup_gate
    s.health[key] = value
    with pytest.raises(gate.GateStopped):
        gate.run(4242)
    assert not s.attempted and not s.preflight and not (s.data / gate.LEDGER_NAME).exists()


def test_source_change_after_reservation_consumes_round_without_model_request(setup_gate, monkeypatch):
    s = setup_gate
    def check(_helper, alias):
        s.preflight.append(alias)
        if len(s.preflight) == 3: raise gate.GateStopped("AUTHORIZED_SOURCE_HASH_MISMATCH")
    monkeypatch.setattr(gate, "_preflight_source", check)
    with pytest.raises(gate.GateStopped, match="QUOTA_CONSUMED"):
        gate.run(4242)
    assert not s.attempted and gate._read_rows(s.data / gate.LEDGER_NAME)[-1]["status"] == "failed_or_unknown"


def test_actual_preflight_hash_and_page_checks_use_only_synthetic_pdf(setup_gate, monkeypatch):
    import fitz
    s = setup_gate
    path = s.helper.SOURCES["case48"][0]
    with fitz.open() as document:
        document.new_page()
        document.save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setitem(gate.SOURCE_IDENTITIES, "case48", (1, digest))
    s.helper.SOURCES["case48"] = (path, 1)
    s.real_preflight(s.helper, "case48")
    monkeypatch.setitem(gate.SOURCE_IDENTITIES, "case48", (2, digest))
    s.helper.SOURCES["case48"] = (path, 2)
    with pytest.raises(gate.GateStopped, match="PAGE_COUNT_MISMATCH"):
        s.real_preflight(s.helper, "case48")
    monkeypatch.setitem(gate.SOURCE_IDENTITIES, "case48", (2, "0" * 64))
    with pytest.raises(gate.GateStopped, match="HASH_MISMATCH"):
        s.real_preflight(s.helper, "case48")


def test_unknown_cost_not_estimated_and_malformed_metrics_not_published(setup_gate):
    result = gate._safe_result("case48", {"metrics": {"model_requests": "PRIVATE", "model_seconds": float("nan")},
        "cost": {"amount": -1, "currency": "PRIVATE"}}, .5)
    assert result["cost"] == {"available": False} and result["metrics"] == {}
    assert result["model_request_count_available"] is False and "PRIVATE" not in json.dumps(result)


def test_cli_has_no_override_or_resume_escape(setup_gate):
    for option in ("--override", "--resume", "--source", "--date"):
        with pytest.raises(SystemExit):
            gate.main([option])


def test_missing_or_failed_legacy_evidence_fails_closed_before_helper(setup_gate):
    gate.LEGACY_BASELINE.write_text('{"status":"failed_or_incomplete"}')
    with pytest.raises(gate.GateStopped, match="LEGACY_BASELINE_UNVERIFIED"):
        gate.run(4242)
    assert not setup_gate.events and not setup_gate.attempted


def test_legacy_today_consumes_quota_before_client_or_private_source_reads(setup_gate, monkeypatch, capsys):
    s = setup_gate
    record = json.loads(gate.LEGACY_BASELINE.read_text())
    # UTC date is still the 23rd; the charged run ended on Beijing's 24th.
    record["ended_at"] = "2026-10-23T18:48:15Z"
    gate.LEGACY_BASELINE.write_text(json.dumps(record))
    monkeypatch.setattr(gate, "_helper", lambda: pytest.fail("Historical paid day blocks before Client"))
    assert gate.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["today_consumed_by_prior_run"] is True
    assert result["eligibility"] == "TODAY_CONSUMED_BY_PRIOR_RUN"
    assert not s.data.exists()
    with pytest.raises(gate.GateStopped, match="TODAY_CONSUMED_BY_PRIOR_RUN"):
        gate.run(4242)
    s.clock["day"] = "2026-10-25"
    assert gate.status()["eligibility"] == "ELIGIBLE_RECOGNITION_CHANGED"
    assert not s.events and not s.preflight


def test_reservation_persists_legacy_date_without_assigning_new_signature(setup_gate):
    s = setup_gate
    gate.reserve(s.clock["day"], s.identity)
    rows = gate._read_rows(s.data / gate.LEDGER_NAME)
    assert rows[0]["status"] == "legacy_succeeded"
    assert rows[0]["beijing_day"] == "2026-10-23"
    assert rows[0]["recognition_signature"] == "legacy-date:2026-10-23"
    assert rows[1]["recognition_signature"] == s.identity["recognition_signature"]


def test_atomic_signature_quota_cannot_be_reserved_on_two_dates(setup_gate):
    s = setup_gate
    def reserve(day):
        try:
            return gate.reserve(day, s.identity)
        except gate.GateStopped as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ("2026-10-24", "2026-10-25")))
    assert sum(value.startswith("scheduled-") for value in results) == 1
    assert results.count("SIGNATURE_ALREADY_CONSUMED") == 1
