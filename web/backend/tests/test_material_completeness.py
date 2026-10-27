"""Synthetic DocumentUnits only: catalog slots are never proof of completeness."""
from types import SimpleNamespace

from app.services.archive_rules import material_completeness, catalog_material_status, unresolved_material_requirements


MANIFEST = [{"file_id": "fixture", "filename": "虚构综合卷.pdf", "path": "synthetic-volume.pdf", "pages": 20}]


def unit(kind, seq, start=0, end=0, **changes):
    data = dict(doc_id=start, doc_type=kind, catalog_seq=seq, source_path="synthetic-volume.pdf",
                start_page=start, end_page=end, confidence=.95, manual_catalog_seq=None)
    data.update(changes)
    return SimpleNamespace(**data)


def analysis(*units, **changes):
    data = dict(case_type="civil", doc_spans=list(units), found_seqs={0, 1, 3, 7, 16, 17, 18},
                missing_items=[], low_confidence_items=[], fields={}, generated_templates={"送达材料清单":"generated.pdf"})
    data.update(changes)
    return SimpleNamespace(**data)


def check(data, key):
    return next(row for row in material_completeness(data, source_manifest=MANIFEST)["checks"] if row["id"] == key)


def test_agency_notice_can_occupy_contract_slot_but_does_not_supply_contract():
    data = analysis(unit("agency_notice", 3, 4, 5))
    row = next(row for row in catalog_material_status(data, source_manifest=MANIFEST) if row["seq"] == 3)
    assert row["found"] is True
    item = row["material_checks"][0]
    assert not item["material_found"] and item["status"] == "missing"
    assert item["expected_doc_types"] == ["contract"]
    assert item["related_sources"][0]["file_id"] == "fixture"
    assert item["related_sources"][0]["page_start"] == 5 and item["related_sources"][0]["page_end"] == 6
    assert "agency_notice_not_contract" in item["reason_codes"]
    assert "通知书不能证明" in item["message"]
    assert not item["legal_requirement_verified"]


def test_material_is_found_by_type_even_when_human_puts_it_in_another_slot():
    data = analysis(unit("contract", 7, 1, 2, manual_catalog_seq=7))
    item = check(data, "material:contract")
    assert item["material_found"] and item["status"] == "recognized"
    assert item["sources"][0]["page_start"] == 2
    assert "未核验签署" in item["message"]
    assert material_completeness(data, source_manifest=MANIFEST)["formal_ready"] is False


def test_unknown_in_evidence_slot_is_not_evidence_found_or_complete():
    data = analysis(unit("unknown", 7, 6, 7))
    row = next(row for row in catalog_material_status(data, source_manifest=MANIFEST) if row["seq"] == 7)
    assert row["found"]
    assert not row["material_checks"][0]["material_found"]
    assert row["unclassified_sources"][0]["page"] == 7
    assert "不表示所有证据原件齐备" in row["material_checks"][0]["message"]


def test_low_confidence_evidence_fallback_remains_unverified():
    data = analysis(unit("evidence", 7, 2, 4, confidence=.2))
    item = check(data, "material:evidence")
    assert item["status"] == "unverified" and not item["material_found"]
    assert item["related_sources"][0]["page"] == 3
    assert "classification_or_source_unverified" in item["reason_codes"]


def test_known_low_confidence_issue_wins_over_number_and_generated_forms_never_prove_execution():
    data = analysis(unit("contract", 3), low_confidence_items=[{"doc_id":0}])
    assert not check(data, "material:contract")["material_found"]
    forms = [item for item in material_completeness(data, source_manifest=MANIFEST)["checks"] if item["check_kind"] == "execution_review"]
    assert len(forms) == 4
    assert all(item["status"] == "unverified" and not item["material_found"] for item in forms)
    assert all("generated_form_not_execution_evidence" in item["reason_codes"] for item in forms)
    assert all(not item["sources"] for item in forms)


def test_out_of_case_or_out_of_range_unit_cannot_be_counted_or_expose_path():
    for changes in ({"source_path":"outside-case.pdf"}, {"end_page":999}, {"start_page":-1}, {"end_page":True}):
        data = analysis(unit("contract", 3, **changes))
        item = check(data, "material:contract")
        assert not item["material_found"] and not item["sources"]
        assert "outside-case.pdf" not in str(item)
        assert "source_path" not in str(item)


def test_conditional_material_requirement_tracks_type_and_procedural_stage():
    data = analysis(unit("execution", 14), case_type="criminal")
    # Criminal seq14 also admits judgments: it is not made "execution required"
    # by its row number, and seq15 refers to appeal rather than execution.
    for stage, expected in (("appeal", True), ("first_instance", False), (None, None)):
        report = material_completeness(data, stage, MANIFEST)
        appeal = next(row for row in report["checks"] if row.get("expected_doc_types") == ["appeal"])
        assert appeal["requirement"] == "conditional" and appeal["applicable"] is expected
        assert not appeal["legal_requirement_verified"]


def test_verified_material_guard_ignores_catalog_occupancy_and_optional_materials():
    checks = [{"id":"contract","requirement":"required","legal_requirement_verified":True,"status":"missing"},
              {"id":"execution","requirement":"conditional","applicable":True,"legal_requirement_verified":True,"status":"recognized"},
              {"id":"optional","requirement":"optional","legal_requirement_verified":True,"status":"missing"},
              {"id":"unused","requirement":"conditional","applicable":False,"legal_requirement_verified":True,"status":"missing"}]
    assert [item["id"] for item in unresolved_material_requirements([{"found":True,"material_checks":checks}])] == ["contract", "execution"]


def test_material_report_has_no_claim_that_unverified_rule_is_current_law():
    for kind in ("civil","criminal","admin","nonlit","counsel","arbitration","consultation"):
        report = material_completeness(analysis(case_type=kind), source_manifest=MANIFEST)
        assert not report["formal_ready"]
        assert report["checks"] and all(not row["legal_requirement_verified"] for row in report["checks"])
        assert "现行要求待核验" in report["notice"]


def test_additional_material_checks_never_create_new_skip_rows_for_old_tasks():
    data = analysis(unit("agency_notice", 3), found_seqs={3}, missing_items=[])
    rows = catalog_material_status(data, source_manifest=MANIFEST)
    assert len(rows) == 1 and rows[0]["seq"] == 3 and rows[0]["found"]
    combined = rows[0]["material_checks"] + rows[0]["additional_material_checks"]
    assert {item["id"] for item in combined} == {item["id"] for item in material_completeness(data, source_manifest=MANIFEST)["checks"]}
