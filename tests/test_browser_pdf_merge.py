from __future__ import annotations

import fitz

import catalog_toc
from pdf_archive_merger import build_full_archive
from pdf_doc_locator import DocumentUnit


def _make_pdf(path, pages: int, label: str):
    document = fitz.open()
    for index in range(pages):
        page = document.new_page(width=595.28, height=841.89)
        page.insert_text((72, 72), f"{label} {index + 1}")
    document.save(path)
    document.close()


def test_full_archive_accepts_browser_pdf_system_forms_without_docx_conversion(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    cover = tmp_path / "档案卷宗.pdf"
    approval = tmp_path / "立案审批表.pdf"
    output = tmp_path / "archive.pdf"
    _make_pdf(source, 1, "source")
    _make_pdf(cover, 2, "browser cover")
    _make_pdf(approval, 1, "browser approval")
    monkeypatch.setattr(catalog_toc, "catalog_toc_to_pdf", lambda *_args, **_kwargs: False)

    unit = DocumentUnit(
        doc_id=0,
        doc_type="contract",
        start_page=0,
        end_page=0,
        title="contract",
        catalog_seq=3,
        source_path=str(source),
    )

    def reject_docx(*_args, **_kwargs):
        raise AssertionError("browser PDFs must not enter DOCX conversion")

    result = build_full_archive(
        case_type="civil",
        original_pdf=str(source),
        generated_templates={"档案卷宗": str(cover), "立案审批表": str(approval)},
        doc_spans=[unit],
        supplements={},
        skipped=[],
        output_pdf=str(output),
        docx_to_pdf_func=reject_docx,
        log=lambda _msg: None,
    )

    assert result.success is True
    assert result.original_pages_included == 1
    with fitz.open(output) as document:
        # 2 cover pages + 1 TOC + 1 approval + 1 source page.
        assert document.page_count == 5
