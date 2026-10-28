"""Expand identity links only inside the current task's source scope."""
from __future__ import annotations

import os
import re

from ..core.v4_bridge import load


def _path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ""


def supporting_refs(ref, fields, source_manifest):
    """Return [] for ordinary evidence, None for a stale/broken identity link.

    The core verifies the current client and its accepted provenance. This
    boundary additionally requires both sides to belong to the task manifest;
    callers still apply their existing account/case access checks.
    """
    if not isinstance(ref, dict):
        return None
    if ref.get('binding') == 'model_form_synthesis':
        module = load('form_synthesis')
        if not module.scope_supported(fields, source_manifest):
            return None
        supports = module.current_support(ref, fields)
    elif ref.get('binding') == 'batch_engagement_intake':
        supports=load('engagement_intake').current_support(ref,fields)
        if supports is None or not load('engagement_intake').scope_supported(fields,source_manifest):return None
        # Continue through the common per-source scope validation below.
    elif ref.get('binding') == 'complaint_intake_excerpt':
        supports = load('complaint_brief').current_support(ref, fields)
    elif ref.get('binding') == 'business_intake_excerpt':
        supports = load('business_intake').current_support(ref, fields)
    elif ref.get('binding') == 'intake_contract_date_default':
        supports = load('intake_contract_date').current_support(ref, fields)
        # New materials may contain another engagement or an amendment. The
        # previous default cannot silently remain authoritative after a scope
        # change; the workflow preserves manual values and requests review.
        if not load('intake_contract_date').scope_supported(fields, source_manifest):return None
    elif ref.get('binding') == 'case_timeline_summary':
        supports = load('case_timeline').current_support(ref, fields)
    elif ref.get('binding') == 'pleading_parties':
        supports = load('pleading_parties').current_support(ref, fields)
    elif ref.get('binding') == 'case_fee_settlement':
        supports = load('fee_settlement_evidence').current_support(ref, fields)
    elif ref.get('binding')=='court_party_details':
        supports=load('court_roster_details').current_detail_support(ref,fields)
    elif ref.get('binding')=='selected_notice_fee':
        supports=load('source_fee_notice').current_support(ref,fields)
    elif ref.get('binding')=='court_report_summary':
        supports=load('court_report_summary').current_support(ref,fields)
    elif ref.get('derivation') == 'labelled_poa_roster':
        field = ref.get('input_field') if ref.get('method') == 'derived_form_draft' else ref.get('field')
        if not field:
            # Raw provenance is keyed by field, and does not repeat that key.
            matches = []
            for key in load('source_engagement_evidence').FIELDS:
                candidates = (fields.get('_provenance') or {}).get(key) or []
                candidates = [candidates] if isinstance(candidates,dict) else candidates
                if isinstance(candidates,list) and ref in candidates:
                    matches.append(key)
            if len(matches) != 1:
                return None
            field = matches[0]
        original = ref
        if ref.get('method') == 'derived_form_draft':
            candidates = (fields.get('_provenance') or {}).get(field) or []
            candidates = [candidates] if isinstance(candidates,dict) else candidates
            original = next((item for item in candidates if isinstance(item,dict)
                and item.get('method') == ref.get('input_method')
                and item.get('value') == ref.get('input_value') == fields.get(field)
                and all(item.get(key) == ref.get(key) for key in
                        ('source_path','page','quote','subject','derivation'))),None)
        if (not original or original.get('value') != fields.get(field)
                or not load('source_engagement_evidence').poa_reference_supported(field,fields.get(field),original,fields)):
            return None
        supports = []
    elif ref.get("binding") in ("same_page_opponent", "court_case_number"):
        field = "对方当事人" if ref["binding"] == "same_page_opponent" else "审理法院"
        identity_key = "subject" if field == "对方当事人" else "case_number"
        original = ref
        if ref.get("method") == "derived_form_draft":
            if (ref.get("input_field") != field
                    or ref.get("input_method") not in ("local_agent", "visual_agent_local_evidence")
                    or not isinstance(ref.get("input_value"), str) or not ref["input_value"]
                    or ref["input_value"] != fields.get(field)):
                return None
            candidates = (fields.get("_provenance") or {}).get(field) or []
            candidates = [candidates] if isinstance(candidates, dict) else candidates
            if not isinstance(candidates, list):
                return None
            original = next((item for item in candidates if isinstance(item, dict)
                and item.get("value") == ref["input_value"] and item.get("method") == ref["input_method"]
                and item.get("binding") == ref["binding"] and item.get(identity_key) == ref.get(identity_key)
                and _path(item.get("source_path")) == _path(ref.get("source_path"))
                and item.get("page") == ref.get("page") and item.get("quote") == ref.get("quote")), None)
            if original is None:
                return None
        elif ref.get("value") != fields.get(field):
            # _form_draft_sources contains the original raw input refs too.
            # A still-matching client cannot certify an old opponent value.
            return None
        guard = (load("linked_party_evidence").current_party_binding_supported if field == "对方当事人"
                 else load("source_court_evidence").current_court_binding_supported)
        if not guard(original, fields):
            return None
        supports = []
    elif "supporting_sources" not in ref and ref.get("binding") not in ("client_contact", "client_court_party"):
        return []
    else:
        supports = load("linked_fact_evidence").current_contact_support(ref, fields)
    if supports is None:
        return None
    scope = {_path(row.get("path")): row for row in source_manifest or []
             if isinstance(row, dict) and type(row.get("pages")) is int and row["pages"] > 0}
    if ref.get("binding") in ("client_contact", "client_court_party") and ref.get("method") == "derived_form_draft":
        # Old form derivation deliberately selects a small set of ref keys and
        # does not copy source hashes. Verify the *current original* too, so a
        # new-file hash cannot be hidden by turning that fact into display text.
        field = ref.get("input_field")
        originals = (fields.get("_provenance") or {}).get(field) or []
        originals = [originals] if isinstance(originals, dict) else originals
        if not isinstance(originals, list):
            return None
        current_value = re.sub(r"\s+", "", str(fields.get(field) or ""))
        matching = [item for item in originals if isinstance(item, dict)
                    and item.get("method") == ref.get("input_method")
                    and re.sub(r"\s+", "", str(item.get("value") or "")) == current_value
                    and all(item.get(key) == ref.get(key) for key in
                            ("source_path", "page", "quote", "binding", "supporting_sources"))
                    and (ref.get("binding") != "client_court_party" or all(
                        item.get(key) == ref.get(key) for key in ("subject", "case_number", "role")))]
        if not any(supporting_refs(item, fields, source_manifest) is not None for item in matching):
            return None
    for item in [ref, *supports]:
        source = scope.get(_path(item.get("source_path")))
        page = item.get("page")
        if not source or type(page) is not int or not 1 <= page <= source["pages"]:
            return None
        if item.get("file_id") and item["file_id"] != source.get("file_id"):
            return None
        if "source_sha256" in item and item["source_sha256"] != source.get("sha256"):
            return None
    return supports
