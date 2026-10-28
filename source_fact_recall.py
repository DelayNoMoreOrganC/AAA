"""Bounded missing-field recall from already-read, case-scoped page text.

No page reads, OCR, model calls, or source-text rewriting. Local candidates are
independently validated and their origin is separate from model suggestions.
"""
from __future__ import annotations

from copy import deepcopy
import re
import unicodedata

from fact_evidence import validated_fact_field
from linked_party_evidence import (extract_same_page_opponent_candidates,
    same_page_opponent_binding, current_party_binding_supported)
from source_court_evidence import extract_court_header_candidate, current_court_binding_supported

MAX_PAGE_CHARS = 18000
FIELDS = ("对方当事人", "审理法院", "地址", "委托人电话", "当事人")


def _compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


def cached_visual_sources(pages, evidence_seen, units):
    """Project the existing read cache through viewed pages and assembled units."""
    scope = {(unit.source_path, number + 1) for unit in units
             for number in range(unit.start_page, unit.end_page + 1)}
    cache = {}
    for key in set(evidence_seen) & pages.read_pages & pages.pages.keys():
        path, number = pages.pages[key]
        if (path, number + 1) in scope:
            cache[(path, number + 1)] = pages.texts[path][number]
    return cache, scope


def recall_cached_source_facts(fields, provenance, conflicts, *, page_cache,
                              allowed_sources, fact_review,
                              method="visual_agent_local_evidence", manual_fields=(),
                              local_recall_context=None, document_units=()):
    """Fill absent automatic fields; preserve humans, conflicts and audit rows.

    All eligible candidates are gathered before commit. Multiple supported
    values stay as a conflict, never first-page-wins. A later call is idempotent.
    """
    if method not in ("visual_agent_local_evidence", "local_agent"):
        raise ValueError("unsupported_local_evidence_method")
    if local_recall_context is not None:
        from intake_date_supplement import collect as collect_date_supplement
        collect_date_supplement(fields, page_cache, allowed_sources, document_units, local_recall_context)
    if local_recall_context is None:
        from complaint_brief import collect
        collect(fields, page_cache=page_cache, allowed_sources=allowed_sources, document_units=document_units)
        from business_intake import collect as collect_business_intake
        collect_business_intake(fields, page_cache=page_cache, allowed_sources=allowed_sources, document_units=document_units)
    metrics = {"pages_checked": 0, "accepted_count": 0, "rejected_count": 0,
               "additional_page_reads": 0, "additional_model_requests": 0,
               "conflict_fields": [], "skipped_oversized_pages": 0}
    # Initial whole-case extraction only. Supplemental parent-context handling
    # retains its stricter dependency path until roster inheritance is verified.
    if local_recall_context is None:
        from source_contract_roster import recall as recall_contract_header
        metrics['accepted_count'] += recall_contract_header(fields,provenance,conflicts,
            page_cache=page_cache,allowed_sources=allowed_sources,document_units=document_units,
            manual_fields=manual_fields,method=method)
        from source_contract_roster import recall_contacts
        metrics['accepted_count'] += recall_contacts(fields,provenance,conflicts,
            page_cache=page_cache,allowed_sources=allowed_sources,document_units=document_units,
            manual_fields=manual_fields,method=method)
        from source_engagement_evidence import recall_poa_facts
        metrics['accepted_count'] += recall_poa_facts(fields,provenance,conflicts,
            page_cache=page_cache,allowed_sources=allowed_sources,manual_fields=manual_fields,
            method=method,fact_review=fact_review)
        from pleading_parties import recall as recall_pleading_parties
        metrics['accepted_count'] += recall_pleading_parties(fields, provenance, conflicts,
            page_cache=page_cache, allowed_sources=allowed_sources, document_units=document_units,
            manual_fields=manual_fields, method=method, fact_review=fact_review)
        from source_contract_roster import recall_court_number
        metrics['accepted_count'] += recall_court_number(fields,provenance,conflicts,
            page_cache=page_cache,allowed_sources=allowed_sources,document_units=document_units,
            manual_fields=manual_fields,method=method)
    from fee_settlement_evidence import recall as recall_settlement
    metrics['accepted_count'] += recall_settlement(fields, provenance, conflicts,
        page_cache=page_cache, allowed_sources=allowed_sources, manual_fields=manual_fields,
        method=method, fact_review=fact_review, supplied=local_recall_context)
    from local_recall_context import local_recall_validation_context
    context, context_blocked = local_recall_validation_context(
        fields, provenance, conflicts, local_recall_context)
    eligible = set()
    for field in FIELDS:
        if field in ("地址", "委托人电话") and local_recall_context is None:
            continue  # Preserve the existing full-batch contact validation path.
        refs = provenance.get(field) or []
        refs = [refs] if isinstance(refs, dict) else refs
        if (field not in manual_fields and field not in context_blocked and not _compact(fields.get(field))
                and not any(isinstance(ref, dict) and ref.get("method") == "human" for ref in refs)
                and not any(row.get("field") == field and row.get("resolved") is not True for row in conflicts)):
            eligible.add(field)
    def recall_court_details():
        if local_recall_context is None:
            # A party obtained from a pleading must not prevent adding the
            # same party's independently linked court roster. Contacts need
            # that roster; a nonempty field alone is not a reason to skip it.
            if (fields.get('当事人') and '当事人' not in manual_fields
                    and not any(c.get('field') in ('当事人','委托人','案号') and not c.get('resolved') for c in conflicts)):
                from source_party_evidence import link_client_court_party
                linking={**fields,'_provenance':provenance,'_field_conflicts':conflicts}
                old=provenance.get('当事人') or [];old=[old] if isinstance(old,dict) else old
                for source in sorted(set(page_cache)&set(allowed_sources)):
                    ref=link_client_court_party(page_cache[source],source,linking,
                        page_cache=page_cache,allowed_sources=allowed_sources)
                    if ref and _compact(ref['value'])==_compact(fields['当事人']):
                        ref['method']=method
                        if not any(r.get('binding')==ref.get('binding') and r.get('source_path')==source[0]
                                   and r.get('page')==source[1] and r.get('value')==ref['value'] for r in old):old.append(ref)
                provenance['当事人']=old
            from court_roster_details import recall_details
            metrics['accepted_count'] += recall_details(fields,provenance,conflicts,
                page_cache=page_cache,allowed_sources=allowed_sources,manual_fields=manual_fields,
                fact_review=fact_review,method=method)
            from source_fee_notice import recall_fee
            metrics['accepted_count'] += recall_fee(fields,provenance,conflicts,
                page_cache=page_cache,allowed_sources=allowed_sources,manual_fields=manual_fields,
                fact_review=fact_review,method=method)
            from court_report_summary import recall_report
            metrics['accepted_count'] += recall_report(fields,provenance,conflicts,
                page_cache=page_cache,allowed_sources=allowed_sources,document_units=document_units,
                manual_fields=manual_fields,fact_review=fact_review,method=method)
            from fee_display import collect as collect_fee_display
            collect_fee_display(fields, provenance, conflicts, page_cache=page_cache,
                allowed_sources=allowed_sources, document_units=document_units, manual_fields=manual_fields)
            from intake_contract_date import recall as recall_intake_date
            metrics['accepted_count'] += recall_intake_date(fields, provenance, conflicts,
                page_cache=page_cache, allowed_sources=allowed_sources, document_units=document_units,
                manual_fields=manual_fields, method=method)
            from engagement_intake import recall as recall_batch_intake
            metrics['accepted_count'] += recall_batch_intake(fields, provenance, conflicts,
                page_cache=page_cache, allowed_sources=allowed_sources, document_units=document_units,
                manual_fields=manual_fields, method=method)
            from case_timeline import collect as collect_timeline
            metrics['accepted_count'] += collect_timeline(fields,provenance,conflicts,
                page_cache=page_cache,allowed_sources=allowed_sources,document_units=document_units,
                manual_fields=manual_fields)
    if not eligible:
        recall_court_details()
        return metrics
    pending = {field: [] for field in eligible}
    for source in sorted(set(page_cache) & set(allowed_sources)):
        path, number = source
        if not isinstance(path, str) or not path or type(number) is not int or number < 1:
            continue
        text = page_cache[source]
        if not isinstance(text, str) or not text.strip():
            continue
        if len(text) > MAX_PAGE_CHARS:
            metrics["skipped_oversized_pages"] += 1
            continue
        metrics["pages_checked"] += 1
        if "当事人" in eligible:
            from source_party_evidence import link_client_court_party
            party = link_client_court_party(text, source, context, page_cache=page_cache,
                allowed_sources=allowed_sources, supplied=local_recall_context)
            if party:
                party["method"] = method
                pending["当事人"].append(party)
        if eligible.intersection(("地址", "委托人电话")):
            from source_contact_evidence import parent_contact_candidates
            contact_refs, contact_review = parent_contact_candidates(
                text, source, context, local_recall_context, eligible)
            for field, ref in contact_refs:
                ref["method"] = method
                pending[field].append(ref)
            fact_review.extend(contact_review)
            metrics["rejected_count"] += len(contact_review)
        candidates = []
        if "对方当事人" in eligible:
            candidates.extend(extract_same_page_opponent_candidates(text))
        if "审理法院" in eligible:
            court = extract_court_header_candidate(text, context.get("案号", ""))
            if court:
                candidates.append(court)
        for candidate in candidates:
            field, value, quote = (candidate[key] for key in ("field", "value", "quote"))
            ref = {"value": value, "quote": quote, "source_path": path, "page": number,
                   "method": method, "candidate_origin": "local_cached_candidate"}
            if field == "对方当事人":
                binding = same_page_opponent_binding(value, quote, text)
                if not binding or validated_fact_field(field, value, quote, text) != field:
                    metrics["rejected_count"] += 1
                    continue
                ref.update(binding="same_page_opponent", subject=binding["client"])
                valid = current_party_binding_supported(ref, context)
            else:
                ref.update(binding="court_case_number", case_number=candidate["case_number"])
                valid = current_court_binding_supported(ref, context)
            if not valid:
                metrics["rejected_count"] += 1
                continue
            pending[field].append(ref)
    for field, refs in pending.items():
        if field == "当事人" and len({ref.get("role") for ref in refs}) > 1:
            # Equal names do not resolve contradictory current procedural
            # roles. Preserve both original spans/support chains in the normal
            # conflict audit, without promoting either to an accepted fact.
            conflicts.append({"field": field, "values": list(dict.fromkeys(ref["value"] for ref in refs)),
                "roles": sorted({ref["role"] for ref in refs}), "source": deepcopy(refs[-1]),
                "sources": deepcopy(refs), "reason_code": "client_court_party_role_conflict",
                "reason": "同一当事人在本案文书中出现不同诉讼身份，请集中核对来源"})
            fact_review.extend({"field": field, "source_path": ref["source_path"], "page": ref["page"],
                "reason_code": "local_evidence_rejected", "verification_code": "client_court_party_role_conflict",
                "reason": "本案当事人身份存在不同来源表述，请核对"} for ref in refs)
            metrics["rejected_count"] += len(refs)
            metrics["conflict_fields"].append(field)
            continue
        # The reader accepts a legacy single-reference dict. Normalize it only
        # when a new validated fact will commit, preserving that audit as-is.
        if refs and isinstance(provenance.get(field), dict):
            provenance[field] = [provenance[field]]
        identities = set()
        for ref in refs:
            value = ref["value"]
            identity = _compact(value)
            if not identities:
                fields[field] = value
            elif identity not in identities:
                conflicts.append({"field": field, "values": [fields[field], value], "source": ref})
            identities.add(identity)
            provenance.setdefault(field, []).append(ref)
            metrics["accepted_count"] += 1
        if len(identities) > 1:
            metrics["conflict_fields"].append(field)
        elif refs:
            for entry in fact_review:
                if (entry.get("field") == field and any(
                        entry.get("source_path") == ref["source_path"] and entry.get("page") == ref["page"]
                        for ref in refs)):
                    # The original rejected candidate is still rejected. A
                    # different complete local quote now supports this field.
                    entry["resolution"] = "field_supported_by_cached_source"
    recall_court_details()
    return metrics
