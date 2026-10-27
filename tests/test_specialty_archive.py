from collections import Counter

import fitz
import pytest

import archive_catalog as ac
import archive_pipeline as pipeline
from document_segmenter import DocumentSource
from pdf_archive_merger import build_full_archive
from specialty_units import build_specialty_units


def _pdf(path, labels):
    with fitz.open() as document:
        for label in labels:
            document.new_page().insert_text((72, 72), label)
        document.save(path)
    return str(path)


@pytest.mark.parametrize("kind,label", [("arbitration", "仲裁"), ("consultation", "咨询代书")])
def test_new_case_types_have_independent_catalogs_and_safe_prompts(kind, label):
    assert ac.CASE_TYPE_LABELS[kind] == label
    assert pipeline.normalize_fields({"委托人": "虚构客户"}, case_type=kind)["案件类别"] == label
    assert label in pipeline.load_case_prompt(kind)
    templates = [name for item in ac.get_catalog(kind) for name in item.templates]
    assert len(templates) == len(set(templates)) == 5
    assert ac.get_catalog(kind) != ac.get_catalog("civil")


def test_consultation_sorts_whole_documents_by_explicit_year_and_date(tmp_path):
    source = _pdf(tmp_path / "scan.pdf", ["later-1", "later-2", "earlier"])
    texts = ["法律咨询记录\n咨询日期：2026年3月3日", "咨询记录的续页，没有新的文书标题", "法律咨询记录\n咨询日期：2025年12月30日"]
    units, metadata = build_specialty_units([DocumentSource(source, "default")], "consultation", {source: texts}, log=lambda *_: None)
    assert [(unit.start_page, unit.end_page) for unit in units] == [(2, 2), (0, 1)]
    assert [unit.doc_id for unit in units] == [0, 1]
    assert metadata["status"] == "dated"
    assert Counter(page for unit in units for page in range(unit.start_page, unit.end_page + 1)) == Counter(range(3))


def test_consultation_does_not_turn_other_dates_into_service_dates(tmp_path):
    source = _pdf(tmp_path / "scan.pdf", ["one", "two"])
    texts = ["法律咨询记录\n起诉日期：2026年3月3日", "代书定稿\n裁判日期：2025年2月1日"]
    units, metadata = build_specialty_units([DocumentSource(source, "default")], "consultation", {source: texts}, log=lambda *_: None)
    assert metadata["status"] == "needs_review" and metadata["warnings"]
    assert [unit.start_page for unit in units] == [0, 1]
    assert all(item["date"] is None for item in metadata["documents"])


@pytest.mark.parametrize("kind", ["arbitration", "consultation"])
def test_real_pdf_draft_assembly_keeps_all_five_forms_and_every_source_page(kind, tmp_path):
    source = _pdf(tmp_path / "source.pdf", ["source-LATER", "source-EARLIER"])
    texts = (["仲裁申请书\n申请人：虚构客户", "仲裁裁决书\n裁决如下"] if kind == "arbitration"
             else ["咨询记录\n咨询日期：2026年3月3日", "代书定稿\n代书日期：2025年2月1日"])
    units, _ = build_specialty_units([DocumentSource(source, "default")], kind, {source: texts}, log=lambda *_: None)
    forms = {name: _pdf(tmp_path / f"{name}.pdf", [f"system-form-{index}"])
             for index, name in enumerate(("档案卷宗", "立案审批表", "质量监督卡", "送达材料清单", "结案报告表"))}
    result = build_full_archive(kind, source, forms, units, {}, [], str(tmp_path / "archive.pdf"),
                                expected_source_paths=[source], use_word_catalog=False, log=lambda *_: None)
    assert result.success and result.original_pages_included == 2
    with fitz.open(result.output_pdf) as document:
        all_text = "\n".join(page.get_text() for page in document)
        assert all(all_text.count(f"system-form-{index}") == 1 for index in range(5))
        assert all_text.count("source-LATER") == all_text.count("source-EARLIER") == 1
        assert document.get_toc() and sum(len(page.get_links()) for page in document) > 0
        if kind == "consultation":
            assert all_text.index("source-EARLIER") < all_text.index("source-LATER")
