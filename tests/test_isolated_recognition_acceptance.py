"""Offline guard regressions; no real accounts, PDFs, database or model requests."""
from dataclasses import dataclass
import builtins
import importlib.util
import json
from pathlib import Path
import runpy
import socket
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
import urllib.request

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/acceptance_v6_recognition_isolated.py"
TASK_IMPORTS = {
    "fitz", "requests", "acceptance_five_types_current", "recognition_identity",
    "document_segmenter", "archive_pipeline", "visual_archive_agent", "deepseek_vision_client",
    "sqlalchemy", "app", "aiosqlite",
}
SENSITIVE_MARKER = "FICTIONAL_SECRET_MUST_NOT_BE_RECORDED"


@pytest.fixture(autouse=True)
def no_external_side_effects(monkeypatch):
    """Any accidental real transport or database access fails the offline test."""
    blocked = Mock(side_effect=AssertionError("Unexpected real I/O in offline test"))
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(sqlite3, "connect", blocked)
    return blocked


@pytest.fixture
def runner(monkeypatch, tmp_path):
    # The standalone script adjusts sys.path; restore it when each test finishes.
    monkeypatch.setattr(sys, "path", sys.path.copy())
    spec = importlib.util.spec_from_file_location("isolated_acceptance_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUT", tmp_path / "isolated")
    monkeypatch.setattr(module, "DATA", tmp_path / "unused-private-data")
    return module


def forbid_task_imports(monkeypatch):
    original = builtins.__import__
    attempts = []

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in TASK_IMPORTS:
            attempts.append(name)
            raise AssertionError("Task components must not initialize")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    return attempts


def test_default_cli_is_inert_without_config_database_or_task_imports(
    monkeypatch, capsys, no_external_side_effects,
):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    monkeypatch.setattr(sys, "path", sys.path.copy())
    imports = forbid_task_imports(monkeypatch)
    reads = Mock(side_effect=AssertionError("Default mode must not read local data"))
    monkeypatch.setattr(Path, "read_text", reads)
    monkeypatch.setattr(Path, "read_bytes", reads)
    monkeypatch.setattr(Path, "mkdir", reads)
    runpy.run_path(str(SCRIPT), run_name="__main__")
    assert json.loads(capsys.readouterr().out) == {
        "mode": "inert", "model_requests": 0, "scope": "frozen_fictional_recognition_only",
    }
    assert imports == []
    reads.assert_not_called()
    no_external_side_effects.assert_not_called()


@pytest.mark.parametrize("report_exists", [False, True])
def test_started_run_never_reads_config_or_initializes_task_components(
    runner, monkeypatch, capsys, no_external_side_effects, report_exists,
):
    directory = runner.OUT / "civil"
    directory.mkdir(parents=True)
    (directory / "started.json").write_text("{}", encoding="utf-8")
    if report_exists:
        (directory / "report.json").write_text('{"status":"failed"}', encoding="utf-8")
    reads = Mock(side_effect=AssertionError("Started runs must not inspect configuration"))
    monkeypatch.setattr(runner, "account_config", reads)
    monkeypatch.setattr(runner, "idle_health", reads)
    monkeypatch.setattr(Path, "read_text", reads)
    monkeypatch.setattr(Path, "read_bytes", reads)
    imports = forbid_task_imports(monkeypatch)
    runner.run("civil")
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ALREADY_STARTED_NO_PAID_RETRY"
    assert output["report_available"] is report_exists
    assert imports == []
    reads.assert_not_called()
    no_external_side_effects.assert_not_called()


@pytest.fixture
def harness(runner, monkeypatch, tmp_path):
    """Only runner control flow is real; every external component is synthetic."""
    def install(name, **attributes):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    identity = {"recognition_signature": runner.SIGNATURE, "normalization_version": "strict-fields-v6"}
    identity_read = Mock(side_effect=lambda: dict(identity))
    install("recognition_identity", recognition_identity=identity_read)
    source = tmp_path / "synthetic-normalized.pdf"
    source.write_bytes(b"fictional fixture bytes; parsed only by a PDF stub")
    fixture_hash = "frozen-fictional-fixture-hash"
    specification = {"inputs": [{"relative_path": "civil/synthetic.pdf", "pages": 1}]}
    state = {"user_id": 123, "org_id": "synthetic-org", "kind": "civil", "fixture_hash": fixture_hash,
             "uploaded": [{"relative_path": "civil/synthetic.pdf", "file_id": "synthetic-file"}]}
    prior_out = tmp_path / "prior"
    state_path = prior_out / "runs/civil/state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    manifest = [{"path": str(source), "sha256": runner.digest(source), "file_id": "synthetic-file"}]
    prior = install("acceptance_five_types_current", OUT=prior_out,
                    fixture=Mock(return_value=(specification, fixture_hash)),
                    own_manifest=Mock(return_value=manifest))

    class PDF:
        needs_pass = False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def __len__(self):
            return 1

    install("fitz", open=Mock(return_value=PDF()))

    @dataclass
    class DocumentSource:
        path: str
        doc_type: str

    install("document_segmenter", DocumentSource=DocumentSource)
    normalize = Mock(side_effect=lambda raw, *args, **kwargs: dict(raw))
    install("archive_pipeline", normalize_fields=normalize)

    class DeepSeekVisionError(RuntimeError):
        def __init__(self, code):
            self.code = code
            super().__init__("Fixed fictional client failure")

    install("deepseek_vision_client", DeepSeekVisionError=DeepSeekVisionError,
            _ERROR_MESSAGES={"CONNECTION_FAILED": "Fixed safe error"})
    transport = Mock(return_value="synthetic transport result")
    session_class = type("OfflineSession", (), {"request": transport})
    install("requests", sessions=SimpleNamespace(Session=session_class))
    config_reads = Mock()
    policy_guard = Mock()
    config = {"privacy": {"request_guard": policy_guard},
              "vision": {"api_key": SENSITIVE_MARKER}}

    async def account_config(_state):
        config_reads(_state)
        return config

    # The account coroutine is immediate; do not create a Windows event-loop socket.
    def immediate(coro):
        try:
            coro.send(None)
        except StopIteration as result:
            return result.value
        finally:
            coro.close()
        raise AssertionError("Unexpected asynchronous I/O in fake account provider")

    monkeypatch.setattr(runner, "account_config", account_config)
    monkeypatch.setattr(runner.asyncio, "run", immediate)
    health = Mock(return_value={"pid": 0, **identity})
    monkeypatch.setattr(runner, "idle_health", health)
    client_factory = Mock(return_value=SimpleNamespace(metrics={"model_requests": 0}))
    model_calls = Mock()

    def analyze(sources, kind, cfg, log):
        cfg["privacy"]["request_guard"]()
        model_calls()
        return [], {}, {}, {sources[0].path: ["fictional text"]}

    analysis = Mock(side_effect=analyze)
    agent = install("visual_archive_agent", DeepSeekVisionClient=client_factory,
                    analyze_visual_sources=analysis)
    return SimpleNamespace(runner=runner, identity=identity, identity_read=identity_read, source=source,
                           manifest=manifest, prior=prior, config_reads=config_reads, config=config,
                           policy_guard=policy_guard, health=health, agent=agent, analysis=analysis,
                           model_calls=model_calls, client_factory=client_factory, normalize=normalize,
                           transport=transport, session_class=session_class,
                           client_error=DeepSeekVisionError, state_path=state_path)


def read_report(harness):
    return json.loads((harness.runner.OUT / "civil/report.json").read_text(encoding="utf-8"))


def test_changed_source_hash_is_rejected_before_any_model_call(harness):
    harness.source.write_bytes(b"changed fictional source")
    with pytest.raises(RuntimeError, match="NORMALIZED_INPUT_HASH_CHANGED"):
        harness.runner.run("civil")
    harness.analysis.assert_not_called()
    harness.model_calls.assert_not_called()
    harness.transport.assert_not_called()
    assert not (harness.runner.OUT / "civil/started.json").exists()


def test_changed_code_identity_is_rejected_before_health_or_account_read(harness):
    harness.identity["recognition_signature"] = "different-code"
    with pytest.raises(RuntimeError, match="SOURCE_IDENTITY_CHANGED"):
        harness.runner.run("civil")
    harness.health.assert_not_called()
    harness.config_reads.assert_not_called()
    harness.analysis.assert_not_called()
    harness.transport.assert_not_called()


@pytest.mark.parametrize("changed", ["source", "code"])
def test_source_and_code_are_rechecked_immediately_before_each_model_action(harness, changed):
    def mutate_before_request(sources, kind, config, log):
        if changed == "source":
            Path(sources[0].path).write_bytes(b"changed after preflight")
        else:
            harness.identity["recognition_signature"] = "changed after start"
        config["privacy"]["request_guard"]()
        harness.model_calls()
        raise AssertionError("Must not reach model action")

    harness.analysis.side_effect = mutate_before_request
    harness.runner.run("civil")
    report = read_report(harness)
    assert report["status"] == "failed"
    assert report["request_guard_authorizations"] == 0
    harness.model_calls.assert_not_called()
    harness.transport.assert_not_called()
    assert (harness.runner.OUT / "civil/started.json").exists()


@pytest.mark.parametrize("error_kind", ["message", "untrusted_code", "client_code"])
def test_failure_records_only_safe_diagnostics_and_never_paid_retries(harness, capsys, error_kind):
    if error_kind == "client_code":
        error = harness.client_error("CONNECTION_FAILED")
    else:
        error = RuntimeError(SENSITIVE_MARKER)
        if error_kind == "untrusted_code":
            error.code = SENSITIVE_MARKER

    def fail(sources, kind, config, log):
        config["privacy"]["request_guard"]()
        harness.agent.DeepSeekVisionClient(SENSITIVE_MARKER)
        harness.model_calls()
        raise error

    harness.analysis.side_effect = fail
    harness.runner.run("civil")
    report_path = harness.runner.OUT / "civil/report.json"
    first_bytes = report_path.read_bytes()
    report = json.loads(first_bytes)
    assert report["status"] == "failed"
    assert report["once_started_no_automatic_rerun"] is True
    assert report["request_guard_authorizations"] == 1
    if error_kind == "client_code":
        assert report["safe_error_code"] == "CONNECTION_FAILED"
    else:
        assert "safe_error_code" not in report
    assert harness.agent.DeepSeekVisionClient is harness.client_factory
    assert harness.session_class.request is harness.transport
    harness.runner.run("civil")
    assert report_path.read_bytes() == first_bytes
    assert harness.analysis.call_count == harness.model_calls.call_count == harness.config_reads.call_count == 1
    assert harness.health.call_count == 2  # One preflight plus one authorization; no retry health call.
    harness.transport.assert_not_called()
    output = capsys.readouterr().out
    assert "ALREADY_STARTED_NO_PAID_RETRY" in output
    assert SENSITIVE_MARKER not in output
    for path in (harness.runner.OUT / "civil").glob("*.json"):
        assert SENSITIVE_MARKER not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("method,url", [
    ("GET", "https://api.deepseek.com/chat/completions"),
    ("POST", "https://example.invalid/not-authorized"),
    ("POST", "https://api.deepseek.com/chat/completions?extra=1"),
])
def test_transport_rejects_other_methods_hosts_and_urls_without_outbound_calls(harness, method, url):
    def attempt(sources, kind, config, log):
        config["privacy"]["request_guard"]()
        harness.session_class.request(None, method, url)
        raise AssertionError("Unexpected transport acceptance")

    harness.analysis.side_effect = attempt
    harness.runner.run("civil")
    assert read_report(harness)["status"] == "failed"
    harness.transport.assert_not_called()
    assert harness.session_class.request is harness.transport


def test_request_budget_stops_the_33rd_action_without_automatic_retry(harness):
    def exhaust(sources, kind, config, log):
        for _ in range(33):
            config["privacy"]["request_guard"]()
            harness.model_calls()
        raise AssertionError("Request budget was not enforced")

    harness.analysis.side_effect = exhaust
    harness.runner.run("civil")
    report = read_report(harness)
    assert report["status"] == "failed"
    assert report["request_guard_authorizations"] == 32
    assert harness.model_calls.call_count == 32
    harness.runner.run("civil")
    assert harness.model_calls.call_count == 32
    assert harness.analysis.call_count == 1
    harness.transport.assert_not_called()
