"""只用临时生成的虚构 PDF 验证实际合并，不访问 OCR、Word 或外部 AI。"""

from types import SimpleNamespace

import fitz
import pytest

import pdf_archive_merger as pam


def _pdf(path, pages=3, label="fictional-source"):
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 72), f"{label}-{index}")
        document.save(path)
    return str(path)


def _unit(doc_id, source, start, end, seq=7):
    return SimpleNamespace(
        doc_id=doc_id, source_path=source, start_page=start, end_page=end,
        catalog_seq=seq, doc_type="evidence", title="fictional material",
    )


@pytest.fixture
def merge(tmp_path, monkeypatch):
    def toc(*_args, **_kwargs):
        document = fitz.open()
        document.new_page().insert_text((72, 72), "fictional TOC")
        return document, 1

    monkeypatch.setattr(pam, "_build_toc_doc", toc)

    def run(source, units, **kwargs):
        output = tmp_path / "result.pdf"
        result = pam.build_full_archive(
            case_type="civil", original_pdf=source, generated_templates={},
            doc_spans=units, supplements={}, skipped=[], output_pdf=str(output),
            log=lambda *_args: None, **kwargs,
        )
        return result, output

    return run


@pytest.mark.parametrize("order_mode", ["catalog", "original"])
def test_overlapping_units_cannot_pass_unique_page_count(tmp_path, merge, order_mode):
    source = _pdf(tmp_path / "source.pdf")
    units = [_unit(0, source, 0, 1), _unit(1, source, 1, 2, 14)]
    result, output = merge(source, units, order_mode=order_mode)
    # 旧 set 计数得到 3/3，却实际插入 4 页。现在必须失败且不交付成品。
    assert result.original_pages_included == 3
    assert result.success is False
    assert not output.exists()


@pytest.mark.parametrize("order_mode", ["catalog", "original"])
def test_every_source_page_physically_appears_once(tmp_path, merge, order_mode):
    source = _pdf(tmp_path / "source.pdf")
    units = [_unit(0, source, 0, 1), _unit(1, source, 2, 2, 14)]
    result, output = merge(source, units, order_mode=order_mode)
    assert result.success is True
    assert result.original_pages_included == 3
    with fitz.open(output) as document:
        assert document.page_count == 4  # 一页目录和三页源材料
        text = "\n".join(page.get_text() for page in document)
    for page in range(3):
        assert text.count(f"fictional-source-{page}") == 1


def test_gap_is_rejected(tmp_path, merge):
    source = _pdf(tmp_path / "source.pdf")
    result, output = merge(source, [_unit(0, source, 0, 0), _unit(1, source, 2, 2)])
    assert result.success is False
    assert not output.exists()


@pytest.mark.parametrize("start,end", [(-1, 1), (0, 3), (2, 1), (False, 2), (0, 2.0)])
def test_invalid_page_ranges_are_rejected_before_pdf_insertion(tmp_path, start, end):
    source = _pdf(tmp_path / "source.pdf")
    with fitz.open() as document:
        assert pam.insert_pdf_pages(document, source, start, end) is False
        assert document.page_count == 0


def test_multisource_pages_with_same_indices_remain_distinct(tmp_path, merge):
    first = _pdf(tmp_path / "first.pdf", 2, "first")
    second = _pdf(tmp_path / "second.pdf", 2, "second")
    result, output = merge(first, [_unit(0, first, 0, 1), _unit(1, second, 0, 1)])
    assert result.success is True
    assert result.original_pages_included == 4
    with fitz.open(output) as document:
        assert document.page_count == 5
        text = "\n".join(page.get_text() for page in document)
    assert all(text.count(f"{label}-{page}") == 1 for label in ("first", "second") for page in range(2))


def test_source_manifest_catches_a_file_without_units(tmp_path, merge):
    first = _pdf(tmp_path / "first.pdf", 1)
    missing = _pdf(tmp_path / "missing.pdf", 2)
    result, output = merge(
        first, [_unit(0, first, 0, 0)], expected_source_paths=[first, missing],
    )
    assert result.success is False
    assert not output.exists()


def test_no_units_cannot_succeed_with_only_a_toc(tmp_path, merge):
    source = _pdf(tmp_path / "source.pdf", 1)
    result, output = merge(source, [])
    assert result.success is False
    assert not output.exists()


def test_source_path_alias_does_not_hide_duplicate_pages(tmp_path, merge, monkeypatch):
    source = _pdf(tmp_path / "source.pdf", 1)
    monkeypatch.chdir(tmp_path)
    result, output = merge(source, [_unit(0, source, 0, 0), _unit(1, "source.pdf", 0, 0)])
    assert result.success is False
    assert not output.exists()


def test_unreadable_source_is_not_treated_as_zero_expected_pages(tmp_path, merge):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a PDF")
    result, output = merge(str(broken), [_unit(0, str(broken), 0, 0)])
    assert result.success is False
    assert not output.exists()


def test_content_only_export_also_rejects_duplicate_pages(tmp_path):
    source = _pdf(tmp_path / "source.pdf", 2)
    output = tmp_path / "content.pdf"
    success, _pages, included = pam.build_catalog_content_pdf(
        "civil", source, [_unit(0, source, 0, 1), _unit(1, source, 1, 1)], str(output),
        log=lambda *_args: None,
    )
    assert included == 2
    assert success is False
    assert not output.exists()
