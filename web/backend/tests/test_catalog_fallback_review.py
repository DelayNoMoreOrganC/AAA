"""Synthetic classification queue checks; no source reads or model calls."""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from archive_pipeline import ArchiveAnalysis
from pdf_doc_locator import DocumentUnit
from app.services import document_classification as classification
from app.services.review_queue import build_review_queue
from app.services.task_workflow import analysis_issues, issue, unresolved_issues


def example(tmp_path):
    path = str(tmp_path / "synthetic-only.pdf")
    manifest = [{"path": path, "file_id": "fictional-source", "filename": "虚构综合材料.pdf",
                 "pages": 5, "sha256": "synthetic-source-identity", "doc_type": "default"}]
    unit = DocumentUnit(0, "poa", 1, 3, catalog_seq=5, source_path=path, confidence=.5)
    low = {"doc_id": 0, "catalog_seq": 5, "pages": [1, 3], "title": "虚构授权文书"}
    audit = {"doc_id": 0, "source_path": path, "page": 2, "doc_type": "poa", "catalog_seq": 5,
             "reason_code": "catalog_mapping_uncertain", "mapping_method": "fallback"}
    analysis = ArchiveAnalysis("counsel", path, {"委托人": "虚构单位", "_visual_classification_review": [audit]},
                               {}, [unit], set(), [], low_confidence_items=[low], source_paths=[path])
    return analysis, manifest


def classifications(analysis, manifest):
    return [row for row in analysis_issues(analysis, manifest) if row["kind"] == "classification"]


def queue(analysis, manifest, issues=None):
    task = SimpleNamespace(source_manifest=manifest, fields=analysis.fields, catalog_status=[],
                           issues=analysis_issues(analysis, manifest) if issues is None else issues)
    return build_review_queue(task)


def test_fallback_is_one_existing_issue_with_all_source_pages_and_local_catalog_label(tmp_path):
    analysis, manifest = example(tmp_path)
    analysis.low_confidence_items.append(copy.deepcopy(analysis.low_confidence_items[0]))
    analysis.fields["_visual_classification_review"].append(copy.deepcopy(analysis.fields["_visual_classification_review"][0]))
    analysis.fields["_visual_classification_review"][0]["catalog_name"] = "UNTRUSTED MODEL LABEL"
    before = copy.deepcopy(analysis)
    problems = classifications(analysis, manifest)
    assert len(problems) == 1 and problems[0]["blocking"]
    assert problems[0]["message"] == "该文书在本业务目录无直接对应项，暂放目录第 5 项「办理各类法律事务的记录和有关材料」，请核对归档位置"
    assert problems[0]["detail"]["mapping_method"] == "fallback"
    assert (problems[0]["detail"]["page_start"], problems[0]["detail"]["page_end"]) == (2, 4)
    grouped = queue(analysis, manifest)
    assert len(grouped) == 1 and grouped[0]["issue_ids"] == [problems[0]["id"]]
    assert [row["page"] for row in grouped[0]["sources"]] == [2, 3, 4]
    assert all(row["file_id"] == "fictional-source" for row in grouped[0]["sources"])
    assert "source_path" not in str(grouped) and "UNTRUSTED MODEL LABEL" not in str(grouped)
    assert analysis == before


def test_better_message_preserves_acknowledged_issue_identity(tmp_path):
    analysis, manifest = example(tmp_path)
    previous = issue("classification", "部分材料分类把握不足，请核对原件与目录", detail=analysis.low_confidence_items[0])
    analysis.fields["_issue_decisions"] = {previous["id"]: {"action": "acknowledged", "reason": "已核对虚构文书归档位置"}}
    current = classifications(analysis, manifest)
    assert len(current) == 1 and current[0]["id"] == previous["id"]
    assert unresolved_issues(current, analysis.fields) == []


@pytest.mark.parametrize("change", [
    {"doc_id": 2}, {"source_path": "other-case.pdf"}, {"page": 5}, {"page": True},
    {"doc_type": "contract"}, {"catalog_seq": 2}, {"mapping_method": "direct"},
    {"reason_code": "other_review"},
])
def test_stale_or_unrelated_audit_never_mislabels_current_classification(tmp_path, change):
    analysis, manifest = example(tmp_path)
    analysis.fields["_visual_classification_review"][0].update(change)
    problems = classifications(analysis, manifest)
    assert len(problems) == 1
    assert problems[0]["message"] == "部分材料分类把握不足，请核对原件与目录"
    assert "mapping_method" not in problems[0]["detail"]


@pytest.mark.parametrize("manual_marker", [None, 5])
def test_audit_metadata_does_not_recreate_resolved_low_confidence_issue(tmp_path, manual_marker):
    analysis, manifest = example(tmp_path)
    analysis.doc_spans[0].manual_catalog_seq = manual_marker
    if manual_marker is None:
        analysis.low_confidence_items = []
    assert classifications(analysis, manifest) == []
    assert analysis.fields["_visual_classification_review"]  # Audit is retained.


def test_real_manual_projection_clears_fallback_only_and_keeps_independent_problems(tmp_path):
    analysis, manifest = example(tmp_path)
    analysis.fields["_ocr_review"] = [{"source_path": manifest[0]["path"], "page": 5}]
    analysis.fields["_field_conflicts"] = [{"field": "承办律师", "values": ["虚构甲", "虚构乙"]}]
    key = next(iter(classification.indexed_units(analysis, manifest)))
    record = {"case_type": "counsel", "stage": "", "source_doc_type": "default",
              "doc_type": "unknown", "catalog_seq": 5, "reason": "人工核对本段归档位置"}
    classification.apply_decisions(analysis, manifest, {key: record})
    assert analysis.doc_spans[0].manual_catalog_seq == 5
    assert analysis.fields["_visual_classification_review"]
    assert classifications(analysis, manifest) == []
    assert {row["kind"] for row in analysis_issues(analysis, manifest)} == {"ocr", "field_conflict"}


def test_distinct_documents_keep_distinct_issues_without_cross_case_anchors(tmp_path):
    analysis, manifest = example(tmp_path)
    analysis.doc_spans.append(DocumentUnit(1, "poa", 4, 4, catalog_seq=5, source_path=manifest[0]["path"], confidence=.4))
    analysis.low_confidence_items.append({"doc_id": 1, "catalog_seq": 5, "pages": [4, 4]})
    second = dict(analysis.fields["_visual_classification_review"][0], doc_id=1, page=5)
    analysis.fields["_visual_classification_review"].append(second)
    grouped = queue(analysis, manifest)
    assert len(grouped) == 2 and [len(row["issue_ids"]) for row in grouped] == [1, 1]
    assert [[ref["page"] for ref in row["sources"]] for row in grouped] == [[2, 3, 4], [5]]
    assert queue(analysis, [dict(manifest[0], path=str(tmp_path / "another-case.pdf"))])[0]["sources"] == []


def test_source_manifest_page_bound_prevents_out_of_range_page_links(tmp_path):
    analysis, manifest = example(tmp_path)
    manifest[0]["pages"] = 2
    problems = classifications(analysis, manifest)
    assert "sources" not in problems[0]["detail"]
    assert all(row["page"] <= 2 for row in queue(analysis, manifest)[0]["sources"])
