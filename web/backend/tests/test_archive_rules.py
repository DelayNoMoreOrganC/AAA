from app.services.archive_rules import get_catalog_rules, get_rule_readiness


def test_budget_unread_pages_are_processing_gaps_not_missing_materials():
    from types import SimpleNamespace as NS
    from app.services.archive_rules import material_completeness
    stopped={'status':'incomplete','unclassified_pages':[{'source_path':'protocol.pdf','page':2}]}
    analysis=NS(case_type='civil',doc_spans=[],fields={'_request_budget_stop':stopped})
    checks=material_completeness(analysis)['checks']
    source_checks=[row for row in checks if row['check_kind']=='source_material']
    assert source_checks and all(row['status']=='processing_incomplete' for row in source_checks)
    assert all(row['material_absence_proven'] is False for row in source_checks)
    analysis.fields={}
    assert any(row['status']=='missing' for row in material_completeness(analysis)['checks'])


def test_existing_templates_do_not_claim_formal_guangdong_compliance():
    for kind in ("civil", "criminal", "admin", "nonlit", "counsel", "arbitration", "consultation"):
        readiness = get_rule_readiness(kind)
        assert readiness["draft_supported"] is (kind not in ("arbitration", "consultation"))
        assert readiness["template_ready"] is readiness["draft_supported"]
        assert readiness["catalog_rules_available"]
        assert readiness["formal_ready"] is False
        assert readiness["sources"] and readiness["version"]
        assert not any(source["current_validity_verified"] for source in readiness["sources"])


def test_unimplemented_business_type_never_silently_uses_civil_catalog():
    for kind in ("unknown", "invented_business"):
        assert get_rule_readiness(kind)["draft_supported"] is False
        assert get_catalog_rules(kind) == []


def test_historical_catalog_does_not_make_every_material_mandatory():
    rules = get_catalog_rules("civil")
    assert all(item["requirement"] == "required" for item in rules if item["scope"] == "product_output")
    assert next(item for item in rules if item["seq"] == 13)["requirement"] == "unknown"
    assert next(item for item in rules if item["seq"] == 15)["applicable"] is None
    assert next(item for item in get_catalog_rules("civil", "execution") if item["seq"] == 15)["applicable"] is True
    assert next(item for item in get_catalog_rules("civil", "first_instance") if item["seq"] == 15)["applicable"] is False


def test_new_business_catalogs_have_sources_without_claiming_guangdong_formal_rules():
    for kind in ("arbitration", "consultation"):
        rules = get_catalog_rules(kind)
        materials = [item for item in rules if item["scope"] == "legal_material"]
        assert materials and all(item["source_id"] == "national-1991-153" and item["source_articles"] for item in materials)
        assert not any(item["legal_requirement_verified"] for item in materials)
    policy = get_rule_readiness("consultation")["volume_policy"]
    assert policy["order"] == "year_then_document_date"
    assert policy["automatic_cross_case_merge"] is False
    assert get_rule_readiness("arbitration", "execution")["formal_ready"] is False
    assert next(item for item in get_catalog_rules("arbitration", "execution") if item["seq"] == 15)["applicable"] is True


def test_catalog_rules_do_not_claim_original_template_is_available():
    for kind in ("arbitration", "consultation"):
        readiness = get_rule_readiness(kind)
        assert readiness["catalog_rules_available"]
        assert not readiness["template_ready"] and not readiness["draft_supported"]
        assert any("原式目录模板" in item for item in readiness["issues"])
