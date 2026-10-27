"""Cross-business placement checks with invented pages and offline transport."""
from collections import Counter
from copy import deepcopy

import pytest

import archive_catalog as catalog
import visual_archive_agent as agent
from page_classifier import collect_low_confidence_units
from pdf_archive_merger import _catalog_item_matches_unit
from tests.test_visual_document_workflow import (
    CONFIG, classified, coverage, extracted, mock_client, offline_only, pdf,
)


FALLBACKS = [
    ("civil", "indictment", 7), ("admin", "meeting_record", 7),
    ("criminal", "legal_work", 9), ("nonlit", "work_record", 5),
    ("nonlit", "judgment", 5), ("counsel", "evidence", 5),
]


@pytest.mark.parametrize("case_type,kind,seq", FALLBACKS)
def test_unmapped_type_preserved_once_but_placement_requires_review(tmp_path, monkeypatch, case_type, kind, seq):
    source = pdf(tmp_path, 5)
    client = mock_client(monkeypatch, lambda ctx, *_:
        classified(ctx, kind=kind, stage="other") if ctx["phase"] == "classification" else extracted(ctx))
    units, fields, metadata, _ = agent.analyze_visual_sources([source], case_type, deepcopy(CONFIG), log=lambda _: None)
    assert len(units) == 1
    unit = units[0]
    assert (unit.doc_type, unit.catalog_seq) == (kind, seq)
    assert unit.confidence <= .5
    assert len(collect_low_confidence_units(units)) == 1
    assert coverage(units) == Counter((source.path, page) for page in range(5))
    assert [item.seq for item in catalog.get_catalog(case_type)
            if _catalog_item_matches_unit(item, unit, catalog.MANUAL_KEY_DOC_TYPES)] == [seq]
    assert metadata["_visual_classification_review"] == [{
        "source_path": source.path, "page": 1, "doc_id": 0,
        "reason_code": "catalog_mapping_uncertain", "doc_type": kind,
        "catalog_seq": seq, "mapping_method": "fallback",
    }]
    assert fields == {} and metadata["_provenance"] == {}
    assert metadata["_agent_summary"]["analysis_version"] == agent.VISUAL_ANALYSIS_VERSION
    assert client.metrics["model_requests"] == 3  # No new paid classification retry.


@pytest.mark.parametrize("case_type,kind,seq", [
    ("civil", "evidence", 7), ("civil", "agency_notice", 3),
    ("admin", "preservation", 8), ("criminal", "meeting_record", 7),
    ("nonlit", "legal_work", 7), ("counsel", "work_record", 5),
])
def test_existing_pdf_and_manual_mappings_stay_confident(tmp_path, monkeypatch, case_type, kind, seq):
    source = pdf(tmp_path)
    mock_client(monkeypatch, lambda ctx, *_:
        classified(ctx, kind=kind, stage="other") if ctx["phase"] == "classification" else extracted(ctx))
    units, _, metadata, _ = agent.analyze_visual_sources([source], case_type, deepcopy(CONFIG), log=lambda _: None)
    assert (units[0].doc_type, units[0].catalog_seq) == (kind, seq)
    assert units[0].confidence == .95
    assert not metadata["_visual_classification_review"]


def test_two_sources_with_same_unmapped_type_keep_separate_review_targets(tmp_path, monkeypatch):
    sources = [pdf(tmp_path, name="first.pdf"), pdf(tmp_path, name="second.pdf")]
    mock_client(monkeypatch, lambda ctx, *_:
        classified(ctx, kind="work_record", stage="other") if ctx["phase"] == "classification" else extracted(ctx))
    units, _, metadata, _ = agent.analyze_visual_sources(sources, "nonlit", deepcopy(CONFIG), log=lambda _: None)
    assert [(item["doc_id"], item["source_path"], item["page"])
            for item in metadata["_visual_classification_review"]] == [
        (0, sources[0].path, 1), (1, sources[1].path, 1)]
    assert coverage(units) == Counter((source.path, 0) for source in sources)


def test_legacy_visual_mode_uses_same_conservative_placement(tmp_path, monkeypatch):
    from tests.test_visual_archive_agent import CFG, batch_context, record, scripted_client
    source = pdf(tmp_path, 2)
    config = deepcopy(CFG)
    config["vision"].update(provider="deepseek", model="deepseek-flash")
    client = scripted_client(monkeypatch, lambda messages, _:
        record(batch_context(messages), kind="work_record"), provider="deepseek")
    units, _, metadata, _ = agent.analyze_visual_sources([source], "nonlit", config, log=lambda _: None)
    assert units[0].doc_type == "work_record" and units[0].catalog_seq == 5
    assert units[0].confidence <= .5
    assert metadata["_visual_classification_review"][0]["mapping_method"] == "fallback"
    assert metadata["_agent_summary"]["analysis_version"] == agent.VISUAL_ANALYSIS_VERSION
    assert coverage(units) == Counter((source.path, page) for page in range(2))
    assert client.metrics["model_requests"] == 1
