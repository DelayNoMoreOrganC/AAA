"""Diagnostics use fabricated markers; source evidence is intentionally retained."""
import json
from dataclasses import asdict

import archive_catalog
import debug_matcher
import pdf_doc_locator


SECRET = "FICTIONAL_PRIVATE_TEXT_AND_FILENAME_9e7a"


def test_disabled_matcher_never_records_prints_or_creates_directory(tmp_path, capsys):
    output = tmp_path / SECRET / "diagnostic.json"
    matcher = debug_matcher.DebugMatcher(str(output))
    matcher.log_page_classification(0, SECRET, {"anchor": SECRET})
    matcher.log_document_segment(1, SECRET, 0, 0, 1.0, 3)
    matcher.log_missing_analysis(3, SECRET, [SECRET], [SECRET])
    assert matcher.save_debug_log() is False
    matcher.print_summary()
    assert matcher.debug_log == []
    assert not output.parent.exists()
    assert capsys.readouterr().out == ""


def test_enabled_diagnostics_drop_all_free_text_and_clear_batch(tmp_path, capsys):
    output = tmp_path / f"{SECRET}.json"
    matcher = debug_matcher.DebugMatcher(str(output), enabled=True)
    matcher.log_page_classification(0, SECRET, {
        "method": SECRET, "doc_type": SECRET, "confidence": .8,
        "catalog_seq": 7, "anchor": SECRET,
    })
    matcher.log_document_segment(1, SECRET, 0, 2, .7, 7)
    matcher.log_missing_analysis(3, SECRET, [SECRET], [SECRET])
    assert SECRET not in repr(matcher.debug_log)
    assert matcher.save_debug_log() is True
    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data) == 3
    assert data[0]["confidence"] == .8
    assert data[0]["anchor_found"] is True
    assert data[0]["match_method"] == "unknown"
    assert SECRET not in output.read_text(encoding="utf-8")
    assert SECRET not in capsys.readouterr().out
    assert matcher.debug_log == []
    assert matcher.save_debug_log() is False


def test_numeric_fields_cannot_smuggle_source_strings(tmp_path):
    matcher = debug_matcher.DebugMatcher(str(tmp_path / "safe.json"), enabled=True)
    matcher.log_document_segment(SECRET, "contract", SECRET, SECRET, SECRET, SECRET)
    assert SECRET not in repr(matcher.debug_log)
    assert asdict(matcher.debug_log[0])["doc_id"] is None


def test_write_error_does_not_print_path_or_original_exception(tmp_path, monkeypatch, capsys):
    matcher = debug_matcher.DebugMatcher(str(tmp_path / "safe.json"), enabled=True)
    matcher.log_page_classification(0, SECRET, {})
    def fail(*args, **kwargs):
        raise OSError(SECRET)
    monkeypatch.setattr(debug_matcher.Path, "write_text", fail)
    assert matcher.save_debug_log() is False
    printed = capsys.readouterr().out
    assert "DIAGNOSTIC_WRITE_FAILED" in printed
    assert SECRET not in printed
    assert not matcher.debug_log


def test_each_operation_owns_a_fresh_debug_batch():
    config = {"debug": {"match_details": True}}
    first = debug_matcher.get_debug_matcher(config)
    first.log_page_classification(0, SECRET, {})
    second = debug_matcher.get_debug_matcher(config)
    assert first is not second
    assert first.output_file != second.output_file
    assert len(first.debug_log) == 1
    assert second.debug_log == []


def test_disabled_segmentation_has_no_diagnostic_io_and_preserves_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    text = "委托代理合同\n委托人：虚构甲公司\n" + SECRET
    disabled = pdf_doc_locator.segment_by_catalog([text], "civil", config={"debug": {"match_details": False}}, log=lambda _: None)
    assert not (tmp_path / "outputs").exists()
    enabled = pdf_doc_locator.segment_by_catalog([text], "civil", config={"debug": {"match_details": True}}, log=lambda _: None)
    assert [asdict(unit) for unit in disabled] == [asdict(unit) for unit in enabled]
    files = list((tmp_path / "outputs").glob("*.json"))
    assert len(files) == 1
    assert SECRET not in files[0].read_text(encoding="utf-8")
    pdf_doc_locator.segment_by_catalog([text], "civil", config={"debug": {"match_details": True}}, log=lambda _: None)
    files = list((tmp_path / "outputs").glob("*.json"))
    assert len(files) == 2
    assert [len(json.loads(path.read_text(encoding="utf-8"))) for path in files] == [1, 1]


def test_locator_logs_omit_filename_but_units_preserve_source_evidence(tmp_path, monkeypatch):
    path = tmp_path / f"{SECRET}.pdf"
    path.write_bytes(b"fictional fixture; page count is mocked")
    monkeypatch.setattr(pdf_doc_locator, "_pdf_page_count", lambda _: 1)
    logs = []
    units = pdf_doc_locator.build_units_from_sources(
        [{"path": str(path), "doc_type": "contract"}], "civil", {}, log=logs.append)
    assert SECRET not in "\n".join(logs)
    assert units[0].source_path == str(path)
    assert units[0].title == path.name
    units[0].doc_type = SECRET
    pdf_doc_locator.assign_catalog_seq(units, archive_catalog.get_catalog("civil"), log=logs.append)
    assert SECRET not in "\n".join(logs)
