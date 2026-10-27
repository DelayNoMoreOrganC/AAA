"""Verify final-page navigation with generated PDFs only; no OCR or Office."""
import fitz
import pytest

import catalog_toc
from archive_pipeline import ArchiveAnalysis, assemble_archive
from pdf_doc_locator import DocumentUnit


def make_pdf(path, labels):
    with fitz.open() as document:
        for label in labels:
            page = document.new_page(width=595, height=842)
            page.insert_text((72, 72), label)
        document.save(path)
    return str(path)


@pytest.mark.parametrize("order_mode", ["catalog", "original"])
def test_preview_only_creates_clickable_directory_without_word(tmp_path, monkeypatch, order_mode):
    def word_forbidden(*args, **kwargs):
        raise AssertionError("preview-only must never call Word")

    monkeypatch.setattr(catalog_toc, "catalog_toc_to_pdf", word_forbidden)
    source = make_pdf(tmp_path / "fictional.pdf", ["FIXTURE_JUDGMENT", "FIXTURE_CONTRACT"])
    cover = make_pdf(tmp_path / "cover.pdf", ["FICTIONAL COVER A", "FICTIONAL COVER B"])
    approval = make_pdf(tmp_path / "approval.pdf", ["FICTIONAL APPROVAL"])
    units = [
        DocumentUnit(0, "judgment", 0, 0, catalog_seq=14, source_path=source),
        DocumentUnit(1, "contract", 1, 1, catalog_seq=3, source_path=source),
    ]
    analysis = ArchiveAnalysis("civil", source, {}, {"档案卷宗": cover, "立案审批表": approval}, units, {0, 1, 3, 14}, [], source_paths=[source])
    output = tmp_path / "archive.pdf"
    result = assemble_archive(analysis, str(output), config={"output": {"preview_only": True}, "archive": {"order_mode": order_mode}}, log=lambda _: None)
    assert result.success
    assert result.original_pages_included == 2
    assert result.order_issues == []
    assert len(result.missing) == len({item["seq"] for item in result.missing})
    with fitz.open(output) as document:
        assert document.page_count == 6
        bookmarks = {title: page - 1 for _level, title, page in document.get_toc()}
        assert bookmarks["卷内目录"] == 2
        assert bookmarks["立案审批表"] == 3
        assert bookmarks["委托代理合同"] == (4 if order_mode == "catalog" else 5)
        assert bookmarks["裁定书、判决书、调解书"] == (5 if order_mode == "catalog" else 4)
        assert "FIXTURE_CONTRACT" in document[bookmarks["委托代理合同"]].get_text()
        assert "FIXTURE_JUDGMENT" in document[bookmarks["裁定书、判决书、调解书"]].get_text()
        links = document[bookmarks["卷内目录"]].get_links()
        assert {link["page"] for link in links} == set(bookmarks.values())
        assert all(link["kind"] == fitz.LINK_GOTO for link in links)


def test_pdf_system_forms_infer_word_free_directory_without_config(tmp_path, monkeypatch):
    from pdf_archive_merger import build_full_archive

    monkeypatch.setattr(catalog_toc, "catalog_toc_to_pdf", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Word invoked")))
    source = make_pdf(tmp_path / "fictional.pdf", ["FICTIONAL SOURCE"])
    cover = make_pdf(tmp_path / "cover.pdf", ["FICTIONAL COVER"])
    result = build_full_archive(
        "civil", source, {"档案卷宗": cover},
        [DocumentUnit(0, "contract", 0, 0, catalog_seq=3, source_path=source)],
        {}, [], str(tmp_path / "archive.pdf"), log=lambda _: None,
    )
    assert result.success
