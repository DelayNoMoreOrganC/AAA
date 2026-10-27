"""Synthetic two-source contact provenance survives derivation or fails closed."""
from copy import deepcopy

import pytest

from form_drafts import derive_form_drafts


CLIENT = "虚构星岚科技有限公司"
ADDRESS = "虚构市样例区演示路88号"
IDENTITY = {"source_path": "synthetic/identity.pdf", "page": 1,
            "quote": "聘方暨委托人：" + CLIENT + "。", "value": CLIENT,
            "method": "visual_agent_local_evidence"}
MANIFEST = [{"path": "synthetic/identity.pdf", "pages": 1},
            {"path": "synthetic/intro.pdf", "pages": 1}]


def fields():
    return {"委托人": CLIENT, "地址": ADDRESS, "_provenance": {
        "委托人": [deepcopy(IDENTITY)],
        "地址": [{"source_path": "synthetic/intro.pdf", "page": 1,
                  "quote": "联系地址：" + ADDRESS + "。", "value": ADDRESS,
                  "method": "visual_agent_local_evidence", "binding": "client_contact",
                  "supporting_sources": [{**deepcopy(IDENTITY), "field": "委托人"}]}]}}


def test_derived_contact_keeps_primary_and_identity_reference_without_faking_quote():
    original = fields()
    out = derive_form_drafts(original, [], source_manifest=MANIFEST)
    assert ADDRESS in out["委托人联系地址及电话"]
    ref = next(ref for ref in out["_form_draft_sources"]["委托人联系地址及电话"] if ref["field"] == "地址")
    assert ref["source_path"] == "synthetic/intro.pdf" and ref["quote"] == "联系地址：" + ADDRESS + "。"
    assert ref["binding"] == "client_contact"
    assert ref["supporting_sources"] == [{**IDENTITY, "field": "委托人"}]
    derived = next(ref for ref in out["_provenance"]["委托人联系地址及电话"] if ref.get("input_field") == "地址")
    assert derived["supporting_sources"] == ref["supporting_sources"]
    assert original == fields()
    assert derive_form_drafts(out, [], source_manifest=MANIFEST) == out


@pytest.mark.parametrize("bad", ["other_client", "manual_client_change", "conflict", "identity_removed", "source_removed",
                                  "support_page_outside", "support_other_case", "support_quote_changed", "binding_forged"])
def test_identity_change_conflict_or_missing_source_invalidates_address_prefill(bad):
    original = fields(); manifest = deepcopy(MANIFEST); manual = {}
    if bad == "other_client": original["委托人"] = "虚构星蓝科技有限公司"
    elif bad == "manual_client_change": manual["委托人"] = "人工改为另一主体"
    elif bad == "conflict": original["_field_conflicts"] = [{"field": "委托人", "values": [CLIENT, "另一个主体"]}]
    elif bad == "identity_removed": original["_provenance"].pop("委托人")
    elif bad == "source_removed": manifest = [item for item in manifest if item["path"] != "synthetic/identity.pdf"]
    elif bad == "support_page_outside":
        original["_provenance"]["委托人"][0]["page"] = 2
        original["_provenance"]["地址"][0]["supporting_sources"][0]["page"] = 2
    elif bad == "support_other_case": original["_provenance"]["地址"][0]["supporting_sources"][0]["source_path"] = "other-case/client.pdf"
    elif bad == "support_quote_changed": original["_provenance"]["地址"][0]["supporting_sources"][0]["quote"] = "无此身份"
    else: original["_provenance"]["地址"][0]["binding"] = "model_asserted"
    out = derive_form_drafts(original, [], source_manifest=manifest, manual_fields=manual)
    assert ADDRESS not in out.get("委托人联系地址及电话", "")
    assert out["地址"] == ADDRESS  # old accepted facts stay auditable; only unsafe prefill is removed


def test_manual_contact_empty_remains_empty_after_linked_source_revalidation():
    out = derive_form_drafts(fields(), [], source_manifest=MANIFEST,
                             manual_fields={"委托人联系地址及电话": ""})
    assert out["委托人联系地址及电话"] == ""
    assert out["_form_drafts"]["fields"]["委托人联系地址及电话"]["status"] == "human_modified"


def test_old_derived_contact_is_cleared_when_new_client_makes_binding_stale():
    generated = derive_form_drafts(fields(), [], source_manifest=MANIFEST)
    assert ADDRESS in generated["委托人联系地址及电话"]
    out = derive_form_drafts(generated, [], source_manifest=MANIFEST,
                             manual_fields={"委托人": "另一个人工核对主体"})
    assert not out.get("委托人联系地址及电话")
    assert out["地址"] == ADDRESS
