"""Assert privacy configuration at the native-import boundary, without native IO."""
import builtins
import os
from types import SimpleNamespace

import pytest

import local_ocr


@pytest.mark.parametrize("previous", [None, "0", "1"])
def test_telemetry_is_disabled_before_native_import_and_engine_creation(monkeypatch, previous):
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    if previous is None:
        monkeypatch.delenv("ORT_DISABLE_TELEMETRY", raising=False)
    else:
        monkeypatch.setenv("ORT_DISABLE_TELEMETRY", previous)
    events = []
    expected = {name: "synthetic/" + filename for name, filename in local_ocr.MODEL_FILES.items()}
    monkeypatch.setattr(local_ocr, "bundled_model_paths", lambda: expected)
    original_import = builtins.__import__

    def disable():
        events.append("disable-api")

    def engine(**options):
        events.append("engine")
        assert all(options[key] == value for key, value in expected.items())
        assert options["det_use_cuda"] is False and options["rec_use_dml"] is False
        return options

    def controlled_import(name, *args, **kwargs):
        if name in {"onnxruntime", "rapidocr_onnxruntime"}:
            configured = os.getenv("ORT_DISABLE_TELEMETRY")
            assert configured == "1", "native initialization could emit telemetry"
            events.append(name)
            if name == "onnxruntime":
                return SimpleNamespace(disable_telemetry_events=disable)
            assert "disable-api" in events, "keep the API guard before loading the OCR wrapper"
            return SimpleNamespace(RapidOCR=engine)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", controlled_import)
    result = local_ocr.create_local_engine()
    assert result["det_model_path"] == expected["det_model_path"]
    assert events == ["onnxruntime", "disable-api", "rapidocr_onnxruntime", "engine"]


def test_disable_api_failure_stops_before_ocr_wrapper_and_keeps_error_private(monkeypatch):
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    monkeypatch.setattr(local_ocr, "bundled_model_paths", lambda: {})
    original_import = builtins.__import__
    events = []

    def fail_disable():
        raise RuntimeError("fictional-private-error-path")

    def controlled_import(name, *args, **kwargs):
        if name == "onnxruntime":
            events.append(name)
            configured = os.getenv("ORT_DISABLE_TELEMETRY")
            assert configured == "1"
            return SimpleNamespace(disable_telemetry_events=fail_disable)
        if name == "rapidocr_onnxruntime":
            pytest.fail("OCR must not initialize after privacy setup fails")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", controlled_import)
    with pytest.raises(local_ocr.LocalOcrError) as error:
        local_ocr.create_local_engine()
    assert events == ["onnxruntime"]
    assert isinstance(error.value.__cause__, RuntimeError)
    assert "fictional-private-error-path" not in str(error.value)
