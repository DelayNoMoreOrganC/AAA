"""Describe the evidence behind a displayed field without certifying its truth.

Only current, in-case anchors are counted. No source path, quotation or private
value is returned here; the existing authorized source viewer handles those.
"""
from __future__ import annotations

import hashlib
import os
import re

from .evidence_links import supporting_refs

LABELS = {
    "human_confirmed": "人工填写或确认",
    "source_supported": "有原文依据，待核对",
    "derived_draft": "依据材料预填，待核对",
    "conflict": "来源存在冲突",
    "unverified": "尚无可核验依据",
    "missing": "材料中尚未取得",
    "configured": "案件设置",
    "convention_default": "按合同日期默认（仅审批表）",
}


def _compact(value):
    return re.sub(r"\s+", "", str(value or ""))


def _refs(fields, key):
    raw = (fields.get("_provenance") or {}).get(key) or []
    return [raw] if isinstance(raw, dict) else raw if isinstance(raw, list) else []


def _path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ""


def field_assurance(key, value, fields, *, source_key=None, source_manifest=(), issues=()):
    actual_key = source_key or key
    refs = [r for r in _refs(fields, actual_key) if isinstance(r, dict)
            and _compact(r.get("value")) == _compact(value)]

    def result(status, anchors=(), reasons=()):
        unique = {(a["file_id"], a["page"]): a for a in anchors}
        return {"status": status, "label": LABELS[status], "source_count": len(unique),
                "anchors": list(unique.values()), "reason_codes": list(reasons)}

    conflicts = [row for row in issues or [] if isinstance(row, dict)
                 and row.get("kind") == "field_conflict"
                 and isinstance(row.get("detail"), dict)
                 and row["detail"].get("field") in (key, actual_key)]

    # A previous human value is retained after supplements, but does not resolve
    # a new conflict. A general acknowledgement records a note, not a factual
    # decision. Keep the badge uncertain until the fact is explicitly resolved.
    raw_conflicts = [row for row in fields.get("_field_conflicts") or []
                     if isinstance(row, dict) and row.get("field") in (key, actual_key)
                     and not row.get("resolved")]
    if any(not row["detail"].get("resolved") for row in conflicts) or raw_conflicts:
        return result("conflict", reasons=("unresolved_field_conflict",))
    if any(r.get("method") == "human" for r in refs):
        return result("human_confirmed", reasons=("human_value_not_machine_verification",))
    if not str(value or "").strip():
        return result("missing")
    if key == "案件类别":
        return result("configured", reasons=("configuration_not_document_evidence",))

    manifest = {_path(row.get("path")): row for row in source_manifest or []
                if isinstance(row, dict) and isinstance(row.get("path"), str)
                and type(row.get("pages")) is int and row["pages"] > 0
                and isinstance(row.get("file_id"), str)}

    def anchor(ref):
        source = manifest.get(_path(ref.get("source_path")))
        page = ref.get("page")
        if source and type(page) is int and 1 <= page <= source["pages"]:
            return {"file_id": source["file_id"], "page": page}
        return None

    evidence = []
    for ref in refs:
        if ref.get('method') == 'model_form_synthesis':
            supports = supporting_refs(ref, fields, source_manifest)
            if supports is not None and anchor(ref):
                evidence.append(anchor(ref))
                evidence.extend(anchor(item) for item in supports if anchor(item))
            continue
        if actual_key in ('应收业务费', '已收业务费', '尚欠业务费', '应退业务费') and ref.get('binding') != 'case_fee_settlement':
            continue  # Raw amount candidates have not passed case identity.
        from ..core.v4_bridge import load
        supported = (_compact(value) in _compact(ref.get('quote','')) if not ref.get('derivation')
                     else load('source_engagement_evidence').poa_reference_supported(actual_key,value,ref,fields))
        if ref.get('derivation')=='court_party_details':
            supported=load('court_roster_details').reference_supported(actual_key,value,ref,fields)
        if ref.get('derivation')=='selected_notice_fee':
            supported=load('source_fee_notice').reference_supported(actual_key,value,ref,fields)
        if ref.get('derivation')=='batch_engagement_intake':
            supported=actual_key==ref.get('field') and load('engagement_intake').current_support(ref,fields) is not None
        if ref.get('derivation')=='court_report_summary':
            supported=load('court_report_summary').reference_supported(actual_key,value,ref,fields)
        if ref.get('derivation')=='pleading_parties':
            supported=load('pleading_parties').reference_supported(actual_key,value,ref,fields)
        if ref.get('derivation')=='case_fee_settlement':
            supported=(actual_key == ref.get('field') and load('fee_settlement_evidence').current_support(ref, fields) is not None)
        if ref.get('derivation')=='intake_contract_date_default':
            supported=(actual_key==ref.get('field') and load('intake_contract_date').current_support(ref,fields) is not None)
        if ref.get('derivation')=='case_timeline_summary':
            supported=(actual_key==ref.get('field') and load('case_timeline').current_support(ref,fields) is not None)
        if (ref.get("method") in ("local_agent", "visual_agent_local_evidence")
                and isinstance(ref.get("quote"), str)
                and supported):
            supports = supporting_refs(ref, fields, source_manifest)
            if supports is None:
                continue
            if located := anchor(ref):
                evidence.append(located)
                evidence.extend(anchor(item) for item in supports if anchor(item))
    if evidence:
        if any(r.get('binding') == 'model_form_synthesis' for r in refs):
            return result('derived_draft', evidence, ('model_summary_with_exact_source_quotes',))
        if any(r.get('binding')=='intake_contract_date_default' or
               (r.get('binding')=='batch_engagement_intake' and actual_key=='立案审批日期') for r in refs):
            return result('convention_default',evidence,('law_office_intake_only_not_approval_or_court_filing',))
        if any(r.get('binding')=='case_timeline_summary' for r in refs):
            return result('derived_draft',evidence,('source_bound_procedural_summary',))
        return result("source_supported", evidence,
                      ("literal_source_not_independent_truth_verification",))

    draft = ((fields.get("_form_drafts") or {}).get("fields") or {}).get(actual_key) or {}
    digest = hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
    if draft.get("status") == "generated" and draft.get("value_digest") == digest:
        source_refs = (fields.get("_form_draft_sources") or {}).get(actual_key) or []
        anchors, valid = [], bool(source_refs)
        for ref in source_refs:
            if not isinstance(ref, dict):
                valid = False
                continue
            if ref.get("method") == "human":
                continue
            supports = supporting_refs(ref, fields, source_manifest)
            if supports is None:
                valid = False
                continue
            located = anchor(ref)
            if not located:
                valid = False
            else:
                anchors.append(located)
                anchors.extend(anchor(item) for item in supports if anchor(item))
        if valid:
            reasons = ["draft_not_signed_or_served_record"]
            reasons.extend(code for code in draft.get("reason_codes") or [] if isinstance(code, str))
            return result("derived_draft", anchors, reasons)
    return result("unverified", reasons=("missing_current_in_case_evidence",))
