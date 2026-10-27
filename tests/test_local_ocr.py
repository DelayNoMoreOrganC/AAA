"""离线路由和失败边界：虚构 PDF、模拟识别器，不访问真实客户资料。"""
from types import SimpleNamespace

import fitz
import pytest

import archive_ocr
import local_ocr
import ocr_pipeline
from settings import get_ocr_engine


def _mixed_pdf(path):
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), "Fictional text layer case document.")
        with fitz.open() as scan:
            scan.new_page().insert_text((72, 72), "Fictional scanned page.")
            image = scan[0].get_pixmap().tobytes("png")
        page = document.new_page()
        page.insert_image(page.rect, stream=image)
        document.save(path)
    return str(path)


def _forbid(*_args, **_kwargs):
    raise AssertionError("local_onnx must never call shared cache, remote OCR, or implicit fallback")


@pytest.fixture
def no_fallback(monkeypatch):
    monkeypatch.setattr(ocr_pipeline, "extract_pdf_text", _forbid)
    monkeypatch.setattr(ocr_pipeline, "_rapidocr_fallback_pages", _forbid)
    monkeypatch.setattr(ocr_pipeline, "_load_ocr_cache", _forbid)
    monkeypatch.setattr(ocr_pipeline, "_save_ocr_cache", _forbid)
    monkeypatch.setattr(archive_ocr, "extract_pdf_text_sampled", _forbid)


def test_local_engine_name_is_preserved():
    assert get_ocr_engine({"ocr": {"engine": "local_onnx"}}) == "local_onnx"


def test_mixed_pdf_preserves_page_alignment_and_ocr_only_scanned_page(tmp_path, monkeypatch, no_fallback):
    source = _mixed_pdf(tmp_path / "mixed.pdf")
    calls = []

    def engine(image):
        assert image.startswith(b"\x89PNG")
        calls.append(image)
        return [[[[0, 0], [10, 0], [10, 10], [0, 10]], "虚构扫描页正文", 0.98]], [0.1]

    monkeypatch.setattr(local_ocr, "create_local_engine", lambda: engine)
    result = ocr_pipeline.ingest_pdf(source, {"ocr": {"engine": "local_onnx"}}, log=lambda *_a: None)
    assert len(calls) == 1
    assert len(result.page_texts) == 2
    assert "Fictional text layer" in result.page_texts[0]
    assert result.page_texts[1] == "虚构扫描页正文"
    assert result.layout_blocks[0]["page_idx"] == 1
    assert result.local_ocr_pages == 1
    assert result.source == "local_onnx"


def test_text_pdf_does_not_load_models(tmp_path, monkeypatch, no_fallback):
    source = tmp_path / "text.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), "Fictional text only.")
        document.save(source)
    monkeypatch.setattr(local_ocr, "create_local_engine", _forbid)
    result = ocr_pipeline.ingest_pdf(str(source), {"ocr": {"engine": "local_onnx"}}, log=lambda *_a: None)
    assert result.source == "text_layer"
    assert result.local_ocr_pages == 0


def test_inference_failure_is_explicit_and_does_not_fallback(tmp_path, monkeypatch, no_fallback):
    source = _mixed_pdf(tmp_path / "mixed.pdf")

    def broken(_image):
        raise RuntimeError("simulated local inference failure")

    monkeypatch.setattr(local_ocr, "create_local_engine", lambda: broken)
    with pytest.raises(local_ocr.LocalOcrError, match="第 2 页本地 OCR 失败"):
        ocr_pipeline.ingest_pdf(source, {"ocr": {"engine": "local_onnx"}}, log=lambda *_a: None)


def test_empty_ocr_page_is_preserved_with_warning(tmp_path, monkeypatch, no_fallback):
    source = _mixed_pdf(tmp_path / "mixed.pdf")
    monkeypatch.setattr(local_ocr, "create_local_engine", lambda: lambda _image: (None, None))
    result = ocr_pipeline.ingest_pdf(source, {"ocr": {"engine": "local_onnx"}}, log=lambda *_a: None)
    assert len(result.page_texts) == 2 and result.page_texts[1] == ""
    assert result.warnings and "第 2 页" in result.warnings[0]


def test_legacy_extraction_entry_also_stays_local(tmp_path, monkeypatch, no_fallback):
    source = _mixed_pdf(tmp_path / "mixed.pdf")
    monkeypatch.setattr(local_ocr, "create_local_engine", lambda: lambda _image: ([[[], "虚构本地结果", 0.9]], []))
    text, error = archive_ocr.extract_pdf_text(source, {"ocr": {"engine": "local_onnx"}}, log=lambda *_a: None)
    assert error is None and "虚构本地结果" in text


def test_missing_bundled_models_fail_before_initialization(tmp_path, monkeypatch):
    monkeypatch.setattr(local_ocr.metadata, "version", lambda _name: "1.4.4")
    monkeypatch.setattr(local_ocr.util, "find_spec", lambda _name: SimpleNamespace(origin=str(tmp_path / "__init__.py")))
    with pytest.raises(local_ocr.LocalOcrError, match="模型缺失"):
        local_ocr.bundled_model_paths()


def test_unverified_package_version_is_rejected(monkeypatch):
    monkeypatch.setattr(local_ocr.metadata, "version", lambda _name: "9.9.9")
    monkeypatch.setattr(local_ocr.util, "find_spec", lambda _name: SimpleNamespace(origin="anything"))
    with pytest.raises(local_ocr.LocalOcrError, match="已验证"):
        local_ocr.bundled_model_paths()


@pytest.mark.skipif(local_ocr.util.find_spec("rapidocr_onnxruntime") is None, reason="offline OCR optional dependency is not installed")
def test_real_bundled_models_read_synthetic_scan_without_python_network(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(socket, "create_connection", _forbid)
    monkeypatch.setattr(socket.socket, "connect", _forbid)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbid)
    source = tmp_path / "fictional-scan.pdf"
    with fitz.open() as text_doc:
        page = text_doc.new_page()
        page.insert_text((72, 100), "FICTIONAL TEST CASE 2026", fontsize=24)
        page.insert_text((72, 150), "虚构测试材料", fontname="china-s", fontsize=24)
        image = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
    with fitz.open() as scan_doc:
        page = scan_doc.new_page()
        page.insert_image(page.rect, stream=image)
        assert not page.get_text().strip()
        scan_doc.save(source)
    result = ocr_pipeline.ingest_pdf(str(source), {"ocr": {"engine": "local_onnx"}}, log=lambda *_a: None)
    assert result.local_ocr_pages == 1
    assert "2026" in result.full_text
    assert "虚构测试材料" in result.full_text
