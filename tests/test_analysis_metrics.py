"""Synthetic timing tests; no live model, case files or wall-clock benchmarks."""
import pytest

import analysis_metrics
import archive_pipeline as pipeline
import workstation_agent
from document_segmenter import DocumentSource


def test_nested_stage_timer_reports_failure_without_exception_contents(monkeypatch):
    clock = iter([10, 11, 14.5, 15])
    monkeypatch.setattr(analysis_metrics, "perf_counter", lambda: next(clock))
    logs = []
    metrics = analysis_metrics.AnalysisMetrics(logs.append)
    def broken():
        raise RuntimeError("PRIVATE_DOCUMENT_SENTINEL")
    with pytest.raises(RuntimeError, match="PRIVATE_DOCUMENT_SENTINEL"):
        with metrics.measure("analysis"):
            metrics.call("source_ingest", broken)
    assert metrics.values == {"scope": "this_analysis_call", "source_ingest_seconds": 3.5,
                              "source_ingest_status": "failed", "analysis_seconds": 5,
                              "analysis_status": "failed"}
    assert logs == ["[性能] source_ingest: 3.500s; status=failed",
                    "[性能] analysis: 5.000s; status=failed"]


def test_pipeline_records_separate_ingest_agent_and_total_elapsed(monkeypatch):
    clock = iter([10, 11, 14, 16, 21, 23])
    monkeypatch.setattr(analysis_metrics, "perf_counter", lambda: next(clock))
    path = "fictional.pdf"
    calls = []
    def ingest(*args, **kwargs):
        calls.append("ingest")
        return {path: "fictional"}, {path: ["fictional", "second"]}, {}, 0, 0
    def extract(*args, **kwargs):
        calls.append("agent")
        return {}, {"_agent_summary": {"pages_checked": 2}}
    monkeypatch.setattr(pipeline, "ingest_archive_sources", ingest)
    monkeypatch.setattr(pipeline.pdl, "build_units_from_sources", lambda *a, **kw: [])
    monkeypatch.setattr(workstation_agent, "extract_with_agent", extract)
    monkeypatch.setattr(pipeline, "normalize_fields", lambda *a, **kw: {})
    result = pipeline.analyze_archive("civil", sources=[DocumentSource(path, "default")],
        config={"extraction": {"mode": "workstation_agent"}, "output": {"preview_only": True}}, log=lambda _: None)
    assert calls == ["ingest", "agent"]
    assert result.fields["_analysis_metrics"] == {
        "scope": "this_analysis_call", "input_files": 1, "source_pages": 2,
        "source_ingest_seconds": 3, "source_ingest_status": "completed",
        "field_agent_seconds": 5, "field_agent_status": "completed",
        "analysis_seconds": 13, "analysis_status": "completed"}
    assert result.fields["_agent_summary"] == {"pages_checked": 2}


def test_invalid_stage_does_not_log_untrusted_text():
    logs = []
    metrics = analysis_metrics.AnalysisMetrics(logs.append)
    with pytest.raises(ValueError):
        metrics.call("PRIVATE_DOCUMENT_SENTINEL", lambda: None)
    assert logs == []


def test_visual_pipeline_does_not_ocr_every_page_or_call_text_agent(monkeypatch):
    import visual_archive_agent
    from pdf_doc_locator import DocumentUnit
    def forbidden(*args, **kwargs):
        pytest.fail("visual flow must not use legacy full-volume OCR/text agent")
    monkeypatch.setattr(pipeline, "ingest_archive_sources", forbidden)
    monkeypatch.setattr(workstation_agent, "extract_with_agent", forbidden)
    path = "fictional.pdf"
    def visual(*args, **kwargs):
        return [DocumentUnit(0, "evidence", 0, 1, catalog_seq=7, source_path=path)], {}, {
            "_ocr_review": [], "_agent_summary": {"visual": True, "local": False, "source_pages_checked": 2}}, {path: ["", ""]}
    monkeypatch.setattr(visual_archive_agent, "analyze_visual_sources", visual)
    result = pipeline.analyze_archive("civil", sources=[DocumentSource(path, "default")],
        config={"extraction": {"mode": "visual_agent"}, "output": {"preview_only": True}}, log=lambda _: None)
    assert result.fields["_agent_summary"]["visual"] is True
    assert result.fields["_ocr_review"] == []
    assert result.fields["_analysis_metrics"]["source_pages"] == 2
    assert "source_ingest_seconds" not in result.fields["_analysis_metrics"]
    assert [(unit.start_page, unit.end_page) for unit in result.doc_spans] == [(0, 1)]
