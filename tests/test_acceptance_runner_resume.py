"""Runner authentication/restart safeguards; no backend or model is contacted."""
import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_runner(monkeypatch, name):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("runner_test_" + name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def response(status, data):
    return SimpleNamespace(status_code=status, json=lambda: data, content=b"json", text=json.dumps(data))


def test_expired_runner_auth_retries_once_and_rewinds_upload(monkeypatch, tmp_path):
    api = load_runner(monkeypatch, "acceptance_api")
    (tmp_path / "credentials.json").write_text('{"username":"fictional","password":"test-only"}')
    api.DATA = tmp_path
    stream = io.BytesIO(b"prefix-source-bytes")
    stream.seek(7)
    calls, bodies = [], []
    def request(method, url, **kwargs):
        calls.append(url)
        if url.endswith("/api/auth/login"):
            return response(200, {"access_token": "fictional-token"})
        bodies.append(kwargs["files"]["file"][1].read())
        return response(401, {}) if len(bodies) == 1 else response(200, {"id": "same-upload"})
    api.session = SimpleNamespace(request=request, headers={})
    assert api.call("POST", "/api/cases/example/files", files={"file": ("sample.pdf", stream)}) == {"id": "same-upload"}
    assert bodies == [b"source-bytes", b"source-bytes"]
    assert len(calls) == 3 and len(api.AUTH_RENEWALS) == 1


def test_failed_retry_does_not_loop_login(monkeypatch, tmp_path):
    api = load_runner(monkeypatch, "acceptance_api")
    (tmp_path / "credentials.json").write_text('{"username":"fictional","password":"test-only"}')
    api.DATA = tmp_path
    calls = []
    def request(method, url, **kwargs):
        calls.append(url)
        return response(200, {"access_token": "fictional-token"}) if url.endswith("/api/auth/login") else response(401, {"detail": "disabled"})
    api.session = SimpleNamespace(request=request, headers={})
    with pytest.raises(RuntimeError, match="401"):
        api.call("GET", "/api/tasks/8")
    assert len(calls) == 3
    calls.clear()
    api.session.request = lambda method, url, **kwargs: (calls.append(url) or response(401, {}))
    with pytest.raises(RuntimeError, match="401"):
        api.call("POST", "/api/auth/login", json={})
    assert len(calls) == 1


def test_resume_keeps_original_task_time_peaks_and_error_history(monkeypatch):
    runner = load_runner(monkeypatch, "acceptance_large_volume")
    previous = {"task_id": 8, "case_id": "fictional-case", "started_at": "2026-10-22T19:12:18+00:00",
                "status": "failed", "error": "/api/tasks/8: 401 expired", "finished_at": "2026-10-22T19:42:20+00:00",
                "elapsed_seconds": 1802, "sampled_peak_rss_mib": {"backend": 736.32, "model": 5828.87},
                "memory_sample_count": 900, "memory_sample_offsets_seconds": [0.1, 1800.1]}
    result = runner.resume_report(previous, datetime(2026, 10, 22, 19, 43, tzinfo=timezone.utc))
    assert result["task_id"] == 8 and result["case_id"] == previous["case_id"]
    assert result["started_at"] == previous["started_at"]
    assert result["sampled_peak_rss_mib"] == previous["sampled_peak_rss_mib"]
    assert result["memory_sample_offsets_seconds"] == previous["memory_sample_offsets_seconds"]
    assert result["runner_outcome_history"][0]["error"] == previous["error"]
    assert result["status"] == "running" and "error" not in result
    assert result["memory_sampling_continuous"] is False
    assert previous["status"] == "failed"


def test_resume_reads_existing_task_without_creating_case_or_restarting_job(monkeypatch, tmp_path):
    runner = load_runner(monkeypatch, "acceptance_large_volume")
    out = tmp_path / "out"
    data = tmp_path / "data"
    out.mkdir(); data.mkdir(); (tmp_path / "workstation-data").mkdir()
    source = out / "large-volume-input.pdf"
    source.write_bytes(b"fictional-harness-input")
    (data / "service.pid").write_text("11")
    (tmp_path / "workstation-data/model.pid").write_text("22")
    (data / "credentials.json").write_text('{"username":"fictional","password":"test-only"}')
    prior = {"task_id": 8, "case_id": "fictional-case", "input_sha256": runner.digest(source),
             "started_at": datetime.now(timezone.utc).isoformat(), "status": "failed", "error": "401 expired",
             "backend_pid": 11, "model_pid": 22, "phases_seconds": {"login_create_upload": 0},
             "sampled_peak_rss_mib": {"backend": 1, "model": 2}}
    runner.save_json(out / "large-volume-input.json", {"input_sha256": prior["input_sha256"]})
    runner.save_json(out / "large-volume.json", prior)
    for name, value in {"ROOT": tmp_path, "OUT": out, "INPUT": source, "REPORT": out / "large-volume.json"}.items():
        monkeypatch.setattr(runner, name, value)
    monkeypatch.setattr(runner.api, "DATA", data)
    monkeypatch.setattr(runner.api, "sample_memory", lambda: {"backend", "model"})
    calls = []
    def call(method, path, **kwargs):
        calls.append((method, path))
        if path == "/api/auth/login":
            return {"access_token": "fictional-token"}
        assert (method, path) == ("GET", "/api/tasks/8")
        return {"id": 8, "case_id": "fictional-case", "status": "failed", "error": "backend failure retained"}
    monkeypatch.setattr(runner.api, "call", call)
    with pytest.raises(RuntimeError, match="backend failure retained"):
        runner.run(11, resume=True)
    assert calls == [("POST", "/api/auth/login"), ("GET", "/api/tasks/8")]
    saved = json.loads((out / "large-volume.json").read_text(encoding="utf-8"))
    assert saved["task_id"] == 8 and saved["runner_outcome_history"][0]["error"] == "401 expired"
    assert (out / "large-volume-before-resume-1.json").is_file()


@pytest.mark.parametrize("judgment_end,valid,evidence_correct", [(3, True, 96), (99, False, 0)])
def test_classification_gate_rejects_full_conservation_in_the_wrong_slot(monkeypatch, tmp_path, judgment_end, valid, evidence_correct):
    runner = load_runner(monkeypatch, "acceptance_large_volume")
    monkeypatch.setattr(runner.api, "DATA", tmp_path)
    source = tmp_path / "fictional.pdf"
    source.write_bytes(b"known-synthetic-source")
    units = [{"start_page": 0, "end_page": 2, "catalog_seq": 3, "doc_type": "contract", "source_path": str(source)},
             {"start_page": 3, "end_page": judgment_end, "catalog_seq": 14, "doc_type": "judgment", "source_path": str(source)}]
    if judgment_end == 3:
        units.append({"start_page": 4, "end_page": 99, "catalog_seq": 7, "doc_type": "evidence", "source_path": str(source)})
    snapshot = tmp_path / "orgs/fictional-org/cases/fictional-case/tasks/8/analysis_snapshot.json"
    runner.save_json(snapshot, {"source_paths": [str(source)], "doc_spans": units})
    result = runner.check_source_classification({"id": 8, "case_id": "fictional-case", "fields": {}}, runner.digest(source))
    assert result["valid"] is valid
    assert result["evidence_appendix_pages_correct"] == evidence_correct
    assert not result["missing_source_pages"] and not result["duplicate_source_pages"]
