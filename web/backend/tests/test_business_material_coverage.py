"""In-memory source scope and human options for existing business catalog slots."""
from types import SimpleNamespace

import pytest

from app.services.archive_rules import catalog_material_status
from app.services.document_classification import classification_options


BUSINESS_TYPES = [
    ("criminal", "meeting_record", 7), ("nonlit", "legal_work", 7),
    ("counsel", "client_intro", 3), ("counsel", "work_record", 5),
    ("counsel", "agreement_status", 6),
]
MANIFEST = [{"file_id": "synthetic-business-file", "filename": "虚构业务材料.pdf",
             "path": "synthetic-business.pdf", "pages": 3}]


def analysis(case_type, kind, seq, confidence=.95, **unit_changes):
    values = dict(doc_id=0, doc_type=kind, catalog_seq=seq, source_path=MANIFEST[0]["path"],
                  start_page=0, end_page=2, confidence=confidence, manual_catalog_seq=None)
    values.update(unit_changes)
    return SimpleNamespace(case_type=case_type, doc_spans=[SimpleNamespace(**values)],
                           found_seqs={seq}, missing_items=[], low_confidence_items=[], fields={})


@pytest.mark.parametrize("case_type,kind,seq", BUSINESS_TYPES)
def test_business_kind_has_human_option_and_recognized_source_material_without_execution_claim(case_type, kind, seq):
    options = classification_options(case_type)
    assert (kind, seq) in {(row["doc_type"], row["catalog_seq"]) for row in options}
    rows = catalog_material_status(analysis(case_type, kind, seq), source_manifest=MANIFEST)
    check = next(check for row in rows for check in row["material_checks"] if check["id"] == "material:" + kind)
    assert check["status"] == "recognized" and check["material_found"] is True
    assert check["sources"][0]["file_id"] == MANIFEST[0]["file_id"]
    assert (check["sources"][0]["page_start"], check["sources"][0]["page_end"]) == (1, 3)
    assert "未核验签署、生效、送达" in check["message"]
    assert not check["legal_requirement_verified"] and check["status"] != "verified"


@pytest.mark.parametrize("case_type,kind,seq", BUSINESS_TYPES)
@pytest.mark.parametrize("changes", [{"confidence": .3}, {"source_path": "not-this-case.pdf"}, {"end_page": 3}])
def test_business_type_does_not_override_uncertainty_or_source_scope(case_type, kind, seq, changes):
    rows = catalog_material_status(analysis(case_type, kind, seq, **changes), source_manifest=MANIFEST)
    check = rows[0]["material_checks"][0]
    assert check["status"] == "unverified" and not check["sources"]


def test_legacy_counsel_unknown_manual_destination_stays_available_but_not_recognized_as_work_record():
    assert ("unknown", 5) in {(row["doc_type"], row["catalog_seq"]) for row in classification_options("counsel")}
    rows = catalog_material_status(analysis("counsel", "unknown", 5, manual_catalog_seq=5), source_manifest=MANIFEST)
    assert rows[0]["material_checks"][0]["status"] == "missing"


def test_business_specific_manual_destinations_cannot_be_requested_for_a_different_case_type():
    options = {(row["doc_type"], row["catalog_seq"]) for row in classification_options("civil")}
    assert not any((kind, seq) in options for _, kind, seq in BUSINESS_TYPES)
