"""Deterministic form drafts from accepted evidence; no I/O or model calls.

These drafts are suggestions for review, not signatures, approvals, payment
records or proof of service. Human values (including deliberate blanks) win.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
import re

from linked_fact_evidence import current_contact_support
from linked_party_evidence import current_party_binding_supported
from source_court_evidence import current_court_binding_supported


VERSION = 14
METHOD = "derived_form_draft"
DRAFT_FIELDS = ("案情简介", "法院文件清单", "委托人联系地址及电话", "案件或项目名称", "结案小结")
STAGE_CASE_TYPES = frozenset(("nonlit", "counsel", "非诉", "非诉讼", "法律顾问"))
OUTCOME_ALIASES = ("审（办）结果", "审(办)结果", "审办结果", "办案小结")
EVIDENCE_METHODS = frozenset(("local_agent", "visual_agent_local_evidence"))
COURT_TYPES = {"judgment": "判决书", "ruling": "裁定书", "mediation": "调解书",
               "summons": "传票或出庭通知书", "court_record": "庭审笔录"}
COURT_INVENTORY_LABELS = {**COURT_TYPES, "preservation": "保全法院文书", "execution": "执行文书"}
EXECUTION_COURT_TITLES = frozenset(("执行裁定书", "执行通知书", "报告财产令", "限制消费令", "限制高消费令", "执行决定书", "结案通知书"))
# These additional catalog types mix court-issued documents with applications.
# A type/title alone is insufficient: use the existing independent review's
# exact current source/page/type/title and its court-context reason below.
_REVIEWED_COURT_TITLES = {
    ("preservation", "执行裁定书"): "preservation_execution_ruling_verified",
    **{("execution", title): "execution_process_notice_verified" for title in
       ("评估结果通知书", "拍卖事项通知", "拍卖事项通知书", "执行情况告知书", "执行情况通知书")},
    **{("unknown", title): "acceptance_notice_no_dedicated_slot" for title in
       ("受理案件通知书", "案件受理通知书", "民事案件受理通知书")},
    **{("preservation", title): "preservation_notice_verified" for title in
       ("财产保全情况告知书", "保全情况告知书", "财产保全告知书")},
    **{("preservation", title): "preservation_order_verified" for title in
       ("民事裁定书", "行政裁定书", "刑事裁定书")},
    **{("execution", title): "execution_closure_notice_verified" for title in
       ("执行结案通知书", "执行案件结案通知书")},
}
NONLIT_MATERIAL_TYPES = frozenset(("contract", "agency_notice", "poa", "invoice", "client_talk",
                                 "legal_work", "client_intro", "work_record", "agreement_status",
                                 "review_record", "group_discussion"))
NO_COURT_MATERIAL_REASON = "no_court_document_in_reviewed_nonlit_materials"


def _compact(value):
    return re.sub(r"\s+", "", str(value or ""))


def _digest(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ""


def _value(fields, key):
    value = fields.get(key)
    return value.strip() if isinstance(value, str) and len(value) <= 2000 else ""


def _human_value(fields, key):
    refs = (fields.get("_provenance") or {}).get(key) or []
    refs = refs if isinstance(refs, list) else [refs]
    return any(isinstance(ref, dict) and ref.get("method") == "human"
               and ref.get("value") == fields.get(key) for ref in refs)


def _scope(manifest):
    return {_path(row["path"]): row for row in manifest or []
            if isinstance(row, dict) and isinstance(row.get("path"), str)
            and type(row.get("pages")) is int and row["pages"] > 0}


def _anchor(ref, scope):
    source = scope.get(_path(ref.get("source_path")))
    page = ref.get("page")
    return source is not None and type(page) is int and 1 <= page <= source["pages"]


def _accepted(fields, key, manual, scope):
    """Require current-value evidence; a historical quote cannot certify edits."""
    if key in fields.get("_form_draft_blocked_fields", ()):
        return "", []
    value = _value(fields, key)
    if not value:
        return "", []
    def human_reference(ref=None):
        item={"field":key,"method":"human","value":value}
        if key in ('阶段工作情况','顾问协议状态') and isinstance(ref,dict) and isinstance(ref.get('subject'),str):
            item['subject']=ref['subject']
        return item
    refs = (fields.get("_provenance") or {}).get(key) or []
    refs = refs if isinstance(refs, list) else [refs]
    matching = [ref for ref in refs if isinstance(ref, dict) and _compact(ref.get("value")) == _compact(value)]
    human = next((ref for ref in reversed(matching) if ref.get("method") == "human"), None)
    if key in manual:
        return value,[human_reference(human)]
    if human:
        return value, [human_reference(human)]
    if any(isinstance(item, dict) and item.get("field") == key for item in fields.get("_field_conflicts") or []):
        return "", []
    accepted = []
    for ref in matching:
        if key in ('应收业务费', '已收业务费', '尚欠业务费', '应退业务费') and ref.get('binding') != 'case_fee_settlement':
            continue
        from source_engagement_evidence import poa_reference_supported
        literal = (_compact(value) in _compact(ref.get('quote','')) if not ref.get('derivation')
                   else poa_reference_supported(key,value,ref,fields))
        if ref.get('derivation')=='court_party_details':
            from court_roster_details import reference_supported
            literal=reference_supported(key,value,ref,fields)
        if ref.get('derivation')=='selected_notice_fee':
            from source_fee_notice import reference_supported
            literal=reference_supported(key,value,ref,fields)
        if ref.get('derivation')=='batch_engagement_intake':
            from engagement_intake import current_support, scope_supported
            literal=key==ref.get('field') and current_support(ref,fields) is not None and scope_supported(fields,list(scope.values()))
        if ref.get('derivation')=='court_report_summary':
            from court_report_summary import reference_supported
            literal=reference_supported(key,value,ref,fields)
        if ref.get('derivation')=='pleading_parties':
            from pleading_parties import reference_supported
            literal=reference_supported(key,value,ref,fields)
        if ref.get('derivation')=='case_fee_settlement':
            from fee_settlement_evidence import current_support
            literal=key == ref.get('field') and current_support(ref, fields) is not None
            # Supplement references carry frozen hashes for both the new page
            # and inherited identities. A layout draft must enforce them too.
            for item in [ref, *(current_support(ref, fields) or [])]:
                source = scope.get(_path(item.get('source_path'))) or {}
                if (item.get('file_id') and item['file_id'] != source.get('file_id')
                        or 'source_sha256' in item and item['source_sha256'] != source.get('sha256')):
                    literal = False
        if ref.get('derivation') == 'intake_contract_date_default':
            from intake_contract_date import current_support as date_support, scope_supported
            literal = key == ref.get('field') and date_support(ref, fields) is not None and scope_supported(fields, list(scope.values()))
        if (ref.get("method") in EVIDENCE_METHODS and _anchor(ref, scope)
                and isinstance(ref.get("quote"), str) and literal):
            if not current_party_binding_supported(ref, fields) or not current_court_binding_supported(ref, fields):
                continue
            supports = [] if ref.get("binding") in ("same_page_opponent", "court_case_number") else current_contact_support(ref, fields)
            if supports is None or any(not _anchor(support, scope) for support in supports):
                continue
            item = {"field": key, "method": ref["method"], "value": value,
                    "source_path": ref["source_path"], "page": ref["page"], "quote": ref["quote"]}
            if ref.get('derivation') in ('selected_notice_fee','court_report_summary','pleading_parties','case_fee_settlement','batch_engagement_intake'):
                item=deepcopy(ref)
            if isinstance(ref.get("subject"), str):
                item["subject"] = ref["subject"]
            if ref.get('derivation') in ('labelled_poa_roster','court_party_details'):
                item['derivation']=ref['derivation']
            if ref.get("binding") in ("same_page_opponent", "court_case_number"):
                item["binding"] = ref["binding"]
            if ref.get("binding") == "court_case_number":
                item["case_number"] = ref["case_number"]
            if ref.get("candidate_origin") == "local_cached_candidate":
                item["candidate_origin"] = ref["candidate_origin"]
            if supports:
                if ref.get('binding') in ('court_report_summary', 'pleading_parties', 'case_fee_settlement'):
                    accepted.append(item)
                    continue
                if ref.get("binding") not in ("client_contact", "client_court_party", "court_party_details"):
                    continue
                item["binding"] = ref["binding"]
                item["supporting_sources"] = deepcopy(ref['supporting_sources'] if ref['binding']=='court_party_details' else supports)
                if ref["binding"] in ("client_court_party", "court_party_details"):
                    item["case_number"] = ref["case_number"]
                    item["role"] = ref["role"]
            accepted.append(item)
    return (value, accepted) if accepted else ("", [])


_STAGE_INPUTS = ("案件类别", "委托人", "委托人名称", "委托方", "阶段工作情况", "顾问协议状态")
_STAGE_CONFLICT_FIELDS = frozenset(_STAGE_INPUTS[1:] + ("结案小结",) + OUTCOME_ALIASES)


def _stage_input_digest(fields, manual):
    value = {"fields": {key: fields.get(key) for key in _STAGE_INPUTS},
             "provenance": {key: (fields.get("_provenance") or {}).get(key) for key in _STAGE_INPUTS},
             "manual": {key: manual[key] for key in _STAGE_INPUTS if key in manual}}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _stage_source_scope(refs, scope):
    # This is a certificate for the currently authorized manifest, not a new
    # read/hash of source bytes. The workflow owns manifest verification.
    return {path: {"pages": scope[path]["pages"], "sha256": scope[path].get("sha256")}
            for path in sorted({_path(ref.get("source_path")) for ref in refs if ref.get("source_path")})
            if path in scope}


def _stage_scope_changed(fields, manual, scope):
    prior = ((fields.get("_form_drafts") or {}).get("fields") or {}).get("结案小结") or {}
    certificate = prior.get("source_scope")
    # A later human identity edit must not re-certify old stage evidence after
    # source bytes changed. Full reanalysis supplies new raw fields without
    # inheriting this machine draft certificate.
    if "source_scope" not in prior:
        return False
    if not isinstance(certificate, dict) or (not certificate and prior.get("status") == "generated"):
        return True
    return any(path not in scope or certificate[path] != {
        "pages": scope[path]["pages"], "sha256": scope[path].get("sha256")}
               for path in certificate)


def _stage_summary(fields, manual, scope):
    """Separate sourced work/status; never turn stage work into final closure."""
    if _value(fields, "案件类别") not in STAGE_CASE_TYPES:
        return "", [], ["stage_summary_not_applicable_to_case_type"]
    if _stage_scope_changed(fields, manual, scope):
        return "", [], ["stage_source_scope_changed"]
    if any(isinstance(item, dict) and item.get("field") in ("委托人", "委托人名称", "委托方")
           for item in fields.get("_field_conflicts") or []):
        return "", [], ["stage_subject_mismatch"]
    if any(isinstance(item, dict) and item.get("field") in ("阶段工作情况", "顾问协议状态")
           for item in fields.get("_field_conflicts") or []):
        return "", [], ["stage_fact_conflict"]
    client, client_refs = _accepted(fields, "委托人", manual, scope)
    if not client:
        return "", [], ["stage_subject_unverified"]
    if any(_value(fields, alias) and _compact(_value(fields, alias)) != _compact(client)
           for alias in ("委托人名称", "委托方")):
        return "", [], ["stage_subject_mismatch"]
    pieces, sources = [], list(client_refs)
    for field, label in (("阶段工作情况", "阶段工作"), ("顾问协议状态", "协议状态")):
        value, refs = _accepted(fields, field, manual, scope)
        if value:
            if any(not isinstance(ref.get("subject"), str) or _compact(ref["subject"]) != _compact(client)
                   for ref in refs):
                return "", [], ["stage_subject_mismatch"]
            pieces.append(f"{label}：{value}")
            sources.extend(refs)
    if not pieces:
        return "", [], ["no_accepted_business_stage_facts"]
    value = "\n".join(pieces)
    # The smallest original outcome cell has a 320-character budget. Leave
    # headroom for labels; do not cut a condition, date or 尚未终止 tail.
    if len(value) > 300:
        return "", sources, ["draft_too_long_for_original_cell"]
    return value, sources, ["stage_summary_not_final_closure"]


def current_stage_summary_supported(fields, manual_fields=None, source_manifest=None, blocked_fields=(), *, case_type=None, resolved_conflicts=()):
    """Validate a stage-only draft against its current inputs, not its label.

    Old snapshots without a source-scope certificate can only be rechecked
    against their caller-verified manifest; this does not invent old hashes.
    This predicate proves a sourced stage summary, never formal case closure.
    """
    manual = manual_fields or {}
    fields = dict(fields, _field_conflicts=[row for row in fields.get("_field_conflicts") or []
                                           if row not in resolved_conflicts])
    if case_type is not None and case_type not in STAGE_CASE_TYPES:
        return False
    if ("结案小结" in manual or _human_value(fields, "结案小结")
            or any(key in manual or _value(fields, key) or _human_value(fields, key) for key in OUTCOME_ALIASES)
            or _STAGE_CONFLICT_FIELDS.intersection(blocked_fields)
            or any(isinstance(row, dict) and row.get("field") in _STAGE_CONFLICT_FIELDS
                   for row in fields.get("_field_conflicts") or [])):
        return False
    status = ((fields.get("_form_drafts") or {}).get("fields") or {}).get("结案小结") or {}
    current = fields.get("结案小结")
    if (status.get("status") != "generated" or not isinstance(current, str) or not current.strip()
            or status.get("value_digest") != _digest(current)
            or "stage_summary_not_final_closure" not in status.get("reason_codes", [])):
        return False
    expected, refs, _ = _stage_summary(fields, manual, _scope(source_manifest))
    if expected != current or not refs:
        return False
    if "source_scope" in status and status["source_scope"] != _stage_source_scope(refs, _scope(source_manifest)):
        return False
    stored = (fields.get("_form_draft_sources") or {}).get("结案小结")
    normalized = lambda values: {json.dumps(ref, ensure_ascii=False, sort_keys=True) for ref in values}
    if not isinstance(stored, list) or normalized(stored) != normalized(refs):
        return False
    history = (fields.get("_provenance") or {}).get("结案小结") or []
    history = history if isinstance(history, list) else [history]
    derived = [ref for ref in history if isinstance(ref, dict) and ref.get("method") == METHOD]
    return len(derived) == len(refs) and all(any(
        item.get("value") == current and item.get("input_field") == ref["field"]
        and item.get("input_method") == ref["method"] and item.get("draft") is True
        and all(item.get(key) == ref.get(key) for key in ("source_path", "page", "quote", "subject"))
        for item in derived) for ref in refs)


def _brief(fields, manual, scope, units=()):
    from complaint_brief import draft
    sourced = draft(fields, units, lambda ref: _anchor(ref, scope))
    independent_common = sourced and 'multiple_pleading_versions' in sourced[2]
    blockers = ("案情简介", "委托人", "当事人") if independent_common else ("案情简介", "委托人", "当事人", "对方当事人")
    if sourced and not any(row.get("field") in blockers
                           for row in fields.get("_field_conflicts") or [] if isinstance(row, dict)):
        return sourced
    values, refs = {}, []
    for key in ("委托人", "当事人", "对方当事人", "案由", "案号", "审理法院"):
        values[key], evidence = _accepted(fields, key, manual, scope)
        refs.extend(evidence)
    identity = values["委托人"] or values["当事人"]
    if not identity or not values["案由"]:
        return "", [], ["insufficient_identity_or_matter"]
    # Never infer plaintiff/defendant, representation, completed litigation or
    # performance from the user-selected case type or a document's title.
    role = "委托人" if values["委托人"] else "当事人"
    parts = [f"{role}：{identity}；事项：{values['案由']}。"]
    if values["对方当事人"]:
        parts.append(f"对方：{values['对方当事人']}。")
    if values["案号"]:
        parts.append(f"案号：{values['案号']}。")
    used = {role, "案由", "对方当事人", "案号"}
    reasons = ["identity_only_brief_no_pleading_narrative"]
    text = "".join(parts)
    if len(text) > 280:
        return "", [], ["draft_too_long_for_original_cell"]
    return text, [ref for ref in refs if ref["field"] in used], reasons


def _contact(fields, manual, scope):
    values, refs = {}, []
    for key, label in (("委托人", "委托人"), ("地址", "联系地址"), ("委托人电话", "联系电话")):
        value, evidence = _accepted(fields, key, manual, scope)
        if value:
            values[key] = value
            refs.extend(evidence)
    if not values.keys() & {"地址", "委托人电话"}:
        return "", [], ["insufficient_contact_evidence"]
    reasons = [] if {"地址", "委托人电话"} <= values.keys() else ["partial_contact"]
    # The retained quality card has a fixed 90-character contact cell. Try
    # formatting-only reductions before omitting the repeated client identity,
    # which remains complete in its own fields and the other system forms.
    # Never shorten an address, telephone number or name to meet this budget.
    layouts = (
        (("委托人", "委托人"), ("地址", "联系地址"), ("委托人电话", "联系电话")),
        (("委托人", "委托人"), ("地址", "地址"), ("委托人电话", "电话")),
        (("地址", "地址"), ("委托人电话", "电话")),
        (("地址", ""), ("委托人电话", "")),
    )
    for layout in layouts:
        used = {key for key, _ in layout if key in values}
        text = "；".join((label + "：" if label else "") + values[key]
                        for key, label in layout if key in values)
        # The original card's contact row is only 22.3 pt high. At the fixed
        # 12 pt fill font, two lines can clip even though all PDF text remains
        # extractable. Keep one readable line; the filing form retains a long
        # complete address when the explicit reference below is necessary.
        width_units = sum(0.5 if ord(char) < 128 else 1 for char in text)
        if len(text) <= 90 and width_units <= 18 and not any(char in text for char in "\r\n\t"):
            return text, [ref for ref in refs if ref["field"] in used], reasons
    # The mandatory filing form uses this same complete canonical address in
    # its original slot. Also apply a conservative two-line width budget, not
    # just the nominal 65-character cap. Refer there explicitly, without altering
    # that field or pretending the whole address is printed in this small cell.
    address = values.get("地址", "")
    if address and len(address) <= 65 and sum(0.5 if ord(char) < 128 else 1 for char in address) <= 40 and not any(char in address for char in "\r\n\t"):
        text = ("电话：" + values["委托人电话"] + "；" if "委托人电话" in values else "") + "地址见立案审批表"
        if len(text) <= 90 and sum(0.5 if ord(char) < 128 else 1 for char in text) <= 18 and not any(char in text for char in "\r\n\t"):
            return text, [ref for ref in refs if ref["field"] in {"地址", "委托人电话"}], reasons + ["contact_address_in_filing_form"]
    # Keep complete accepted values/quotes in the source audit. An empty draft
    # with an explicit reason is preferable to a value guaranteed to overflow.
    return "", refs, reasons + ["draft_too_long_for_original_cell"]


def _project_name(fields, manual, scope):
    explicit, evidence = _accepted(fields, "案件或项目名称", manual, scope)
    if explicit:
        return explicit, evidence, ["explicit_project_name_preserved"]
    client, clients = _accepted(fields, "委托人", manual, scope)
    matter, matters = _accepted(fields, "案由", manual, scope)
    if not client or not matter:
        return "", [], ["insufficient_identity_or_matter"]
    # This names the work; it does not infer who sued whom or whether a case
    # was filed, concluded or paid. Preserve full party names and matter text.
    value = f"{client}：{matter}"
    refs = clients + matters
    if _value(fields, '案件类别') in ('civil', 'admin', '民事', '行政'):
        party, parties = _accepted(fields, '当事人', manual, scope)
        opposite, opposites = _accepted(fields, '对方当事人', manual, scope)
        if _compact(party) == _compact(client) and opposite:
            # “与” names the evidenced dispute without guessing who sued whom.
            value = f'{client}与{opposite}{matter}'
            refs += parties + opposites
    if len(value) > 110:
        return "", [], ["draft_too_long_for_original_cell"]
    return value, refs, []


def _no_court_material_for_current_scope(fields, units, scope):
    """Do not ask for court papers in a fully classified nonlit material set.

    This describes only the supplied pages, never a legal exemption. Unread,
    uncertain or litigation-related material keeps the ordinary review path.
    """
    if _value(fields, "案件类别") not in ("nonlit", "counsel", "非诉", "非诉讼", "法律顾问"):
        return False
    if any(_value(fields, key) for key in ("案号", "执行案号", "法院收案号", "审理法院")):
        return False
    if not scope or not units:
        return False
    covered = {path: [] for path in scope}
    for unit in units:
        path = _path(getattr(unit, "source_path", ""))
        start, end = getattr(unit, "start_page", None), getattr(unit, "end_page", None)
        if (path not in scope or type(start) is not int or type(end) is not int
                or not 0 <= start <= end < scope[path]["pages"]
                or getattr(unit, "doc_type", "") not in NONLIT_MATERIAL_TYPES):
            return False
        confidence = getattr(unit, "confidence", 0)
        manual_classification = type(getattr(unit, "manual_catalog_seq", None)) is int
        if not manual_classification and (type(confidence) not in (int, float)
                or not math.isfinite(confidence) or confidence < 0.75):
            return False
        covered[path].append((start, end))
    for path, intervals in covered.items():
        cursor = 0
        for start, end in sorted(intervals):
            if start != cursor:
                return False
            cursor = end + 1
        if cursor != scope[path]["pages"]:
            return False
    return True


def _court_inventory_draft(fields, units, scope):
    value, refs, reasons = _court_documents(units, scope, fields.get("_visual_classification_review") or [])
    if not value and _no_court_material_for_current_scope(fields, units, scope):
        return "", [], [NO_COURT_MATERIAL_REASON]
    return value, refs, reasons


def _current_court_title_review(unit, title, reviews):
    reason = _REVIEWED_COURT_TITLES.get((unit.doc_type, title))
    if not reason or not isinstance(reviews, list):
        return False
    if unit.doc_type == "unknown":
        # This narrow exception identifies a court document for the inventory,
        # while its catalog placement remains unresolved. It cannot bless an
        # uncertain multi-document span or a contrary current title review.
        if unit.start_page != unit.end_page or any(isinstance(ref, dict)
            and ref.get("method") == "local_title_context_review"
            and _path(ref.get("source_path")) == _path(unit.source_path)
            and ref.get("page") == unit.start_page + 1
            and (ref.get("independent_title_verified") is not True
                 or ref.get("title") != title or ref.get("procedure_stage") != "trial")
            for ref in reviews):
            return False
    return any(isinstance(ref, dict)
               and ref.get("method") == "local_title_context_review"
               and ref.get("independent_title_verified") is True
               and ref.get("reason_code") == reason
               and _path(ref.get("source_path")) == _path(unit.source_path)
               and type(ref.get("page")) is int and ref["page"] == unit.start_page + 1
               and ref.get("effective_doc_type") == unit.doc_type
               and ref.get("title") == title
               and (unit.doc_type != "unknown" or ref.get("procedure_stage") == "trial")
               and ("doc_id" not in ref or type(ref["doc_id"]) is int and ref["doc_id"] == unit.doc_id)
               for ref in reviews)


def _court_documents(units, scope, title_reviews=()):
    entries, refs, seen, uncertain, shortened = [], [], set(), 0, False
    for unit in sorted(units or [], key=lambda item: item.doc_id):
        source = scope.get(_path(getattr(unit, "source_path", "")))
        start, end = getattr(unit, "start_page", None), getattr(unit, "end_page", None)
        if source is None or type(start) is not int or type(end) is not int or not 0 <= start <= end < source["pages"]:
            uncertain += 1
            continue
        kind, title = getattr(unit, "doc_type", ""), getattr(unit, "title", "")
        title = " ".join(title.split()) if isinstance(title, str) and len(title) <= 120 else ""
        independently_reviewed = _current_court_title_review(unit, title, title_reviews)
        court_type = (kind in COURT_TYPES or kind == "execution" and title in EXECUTION_COURT_TITLES
                      or independently_reviewed)
        if not court_type:
            if kind in ("unknown", "execution") or (kind, title) in _REVIEWED_COURT_TITLES:
                uncertain += 1
            continue
        confidence = getattr(unit, "confidence", 0)
        manual_classification = type(getattr(unit, "manual_catalog_seq", None)) is int
        reviewed_unmapped_notice = kind == "unknown" and independently_reviewed
        if not manual_classification and not reviewed_unmapped_notice and (type(confidence) not in (int, float) or not math.isfinite(confidence) or confidence < 0.75):
            uncertain += 1
            continue
        identity = (_path(unit.source_path), start, end)
        if identity in seen:
            continue
        seen.add(identity)
        full_title = title or COURT_INVENTORY_LABELS.get(kind, "法院文书")
        title = full_title
        # This fixed original form asks for short document names. A classifier
        # can include court/case metadata in the title; retain it in provenance
        # and use the already identified document kind, never slice the text.
        if len(title) + 2 > 26:
            title = COURT_INVENTORY_LABELS.get(kind, "法院文书")
            shortened = True
        span = str(start + 1) if start == end else f"{start + 1}—{end + 1}"
        entries.append(f"《{title}》（原材料第{span}页）")
        ref = {"field": "文书分类", "method": "human_classification" if manual_classification else "document_classification",
                     "source_path": unit.source_path, "page": start + 1, "page_end": end + 1,
                     "doc_id": unit.doc_id, "doc_type": kind, "document_title": full_title,
                     "quote": "", "classification_only": True}
        if independently_reviewed:
            ref.update(independent_title_verified=True,
                       title_review_reason=_REVIEWED_COURT_TITLES[(kind, full_title)])
            if reviewed_unmapped_notice:
                ref["catalog_mapping_pending"] = True
        refs.append(ref)
    reasons = ["classification_requires_review"] if uncertain else []
    if shortened:
        reasons.append("document_titles_shortened_with_full_source_retained")
    if not entries:
        return "", [], reasons + ["no_supported_court_document"]
    if len(entries) > 18:
        # Keep every source reference and the full archive directory. The short
        # system form groups by kind with explicit counts instead of losing rows.
        groups = {}
        for ref in refs:
            name = COURT_INVENTORY_LABELS.get(ref["doc_type"], "法院文书")
            groups[name] = groups.get(name, 0) + 1
        entries = [f"《{name}》（{count}份，详见本卷）" for name, count in groups.items()]
        reasons.append("document_inventory_grouped_with_full_source_retained")
    # This is an inventory draft, never an assertion that a document was served.
    return "\n".join(entries), refs, reasons


def court_inventory_page_counts(fields):
    """Measure listed source spans, never infer actual delivery or copy count.

    Only the exact current automatic inventory and its one-to-one source rows
    qualify. A typed page annotation, manual edit or grouped list is not proof.
    """
    value = fields.get("法院文件清单") or ""
    lines = [line.strip() for line in value.splitlines() if line.strip()] if isinstance(value, str) else []
    empty = [None] * len(lines)
    meta = ((fields.get("_form_drafts") or {}).get("fields") or {}).get("法院文件清单") or {}
    refs = (fields.get("_form_draft_sources") or {}).get("法院文件清单") or []
    if (not lines or len(lines) > 18 or meta.get("status") != "generated"
            or meta.get("value_digest") != _digest(value) or _human_value(fields, "法院文件清单")
            or not isinstance(refs, list) or len(refs) != len(lines)):
        return empty
    counts, seen = [], set()
    for line, ref in zip(lines, refs):
        if not isinstance(ref, dict):
            return empty
        start, end, title = ref.get("page"), ref.get("page_end"), ref.get("document_title")
        path = _path(ref.get("source_path"))
        if (ref.get("field") != "文书分类" or ref.get("classification_only") is not True
                or ref.get("method") not in ("document_classification", "human_classification")
                or not path or type(start) is not int or type(end) is not int
                or not 1 <= start <= end <= 2000 or not isinstance(title, str) or not title):
            return empty
        if len(title) + 2 > 26:
            title = COURT_INVENTORY_LABELS.get(ref.get("doc_type"), "法院文书")
        span = str(start) if start == end else f"{start}—{end}"
        identity = (path, start, end)
        if line != f"《{title}》（原材料第{span}页）" or identity in seen:
            return empty
        seen.add(identity)
        counts.append(end - start + 1)
    return counts


def derive_form_drafts(fields, units, *, source_manifest, manual_fields=None, blocked_fields=(), acknowledged_conflicts=(), resolved_conflicts=(), stage_blocked_fields=()):
    """Return a copy with reviewable drafts and stable per-field provenance.

    `acknowledged_conflicts` is supplied only by the workflow after matching an
    exact current issue decision. It affects this calculation, never the saved
    conflict history. A human value alone cannot acknowledge a new conflict.
    `_form_drafts` contains only status/counts/reasons/digests for UI summaries.
    Material references are separate in `_form_draft_sources` and `_provenance`.
    """
    result = deepcopy(fields or {})
    manual = manual_fields or {}
    result.update({key: deepcopy(value) for key, value in manual.items() if not key.startswith("_")})
    old = (result.get("_form_drafts") or {}).get("fields") or {}
    inputs = dict(result)
    inputs["_form_draft_blocked_fields"] = {key for key in blocked_fields if isinstance(key, str)}
    inputs["_field_conflicts"] = [row for row in result.get("_field_conflicts") or []
                                  if row not in acknowledged_conflicts] + [
        {"field": key} for key in blocked_fields if isinstance(key, str)]
    # Knowing about a stage/identity discrepancy does not resolve its facts.
    # Keep those raw conflicts for stage synthesis even when ordinary review
    # acknowledgements permit unrelated form drafts to be prepared.
    stage_inputs = dict(inputs, _field_conflicts=[row for row in result.get("_field_conflicts") or []
                                               if row not in resolved_conflicts] + [
        {"field": key} for key in set(blocked_fields) | set(stage_blocked_fields) if isinstance(key, str)])
    scope = _scope(source_manifest)
    statuses, sources = {}, {}
    provenance = deepcopy(result.get("_provenance") or {})
    builders = {"案情简介": lambda: _brief(inputs, manual, scope, units),
                "法院文件清单": lambda: _court_inventory_draft(inputs, units, scope),
                "委托人联系地址及电话": lambda: _contact(inputs, manual, scope),
                "案件或项目名称": lambda: _project_name(inputs, manual, scope),
                "结案小结": lambda: _stage_summary(stage_inputs, manual, scope)}
    include_stage = (_value(inputs, "案件类别") in STAGE_CASE_TYPES
                     and (any(key in inputs for key in ("阶段工作情况", "顾问协议状态"))
                          or "结案小结" in old))
    for field in DRAFT_FIELDS if include_stage else DRAFT_FIELDS[:-1]:
        current, previous = result.get(field, ""), old.get(field) or {}
        history = provenance.get(field) or []
        history = history if isinstance(history, list) else [history]
        owned = (previous.get("status") in ("generated", "insufficient", "not_applicable")
                 and previous.get("value_digest") == _digest(current))
        human = field in manual or previous.get("status") == "human_modified" or _human_value(inputs, field)
        if field == "结案小结":
            # Existing result aliases and explicit manual blanks govern the
            # outcome. A derived draft may not introduce a competing result.
            aliases = [key for key in OUTCOME_ALIASES if key in manual
                       or isinstance(inputs.get(key), str) and inputs[key].strip()
                       or _human_value(inputs, key)]
            if aliases:
                if owned and not human:
                    result.pop(field, None)
                    current = ""
                statuses[field] = {"status": "human_modified" if any(key in manual for key in aliases) else "preserved",
                                   "reason_codes": ["existing_outcome_alias_preserved"],
                                   "source_count": 0, "value_digest": _digest(current)}
                sources[field] = []
                provenance[field] = [ref for ref in history if not isinstance(ref, dict) or ref.get("method") != METHOD]
                continue
        if human or current and not owned:
            status = "human_modified" if human else "preserved"
            statuses[field] = {"status": status, "reason_codes": ["human_value_preserved" if human else "existing_value_preserved"],
                               "source_count": 0, "value_digest": _digest(current)}
            # Keep prior audit references as history; do not attribute a changed
            # human sentence to a machine-generated quotation.
            sources[field] = []
            provenance[field] = [ref for ref in history if not isinstance(ref, dict) or ref.get("method") != METHOD]
            continue
        value, refs, reasons = builders[field]()
        # Absent facts stay absent; only clear a field when replacing a previous
        # draft (or an already-present empty value). Metadata still explains
        # why no draft could be produced.
        if value or field in result:
            result[field] = value
        unique = {json.dumps(ref, ensure_ascii=False, sort_keys=True): ref for ref in refs}
        sources[field] = list(unique.values())
        status = "generated" if value else "not_applicable" if NO_COURT_MATERIAL_REASON in reasons else "insufficient"
        statuses[field] = {"status": status, "reason_codes": reasons,
                           "source_count": len(unique), "value_digest": _digest(value)}
        if field == "结案小结":
            statuses[field]["input_digest"] = _stage_input_digest(stage_inputs, manual)
            statuses[field]["source_scope"] = (deepcopy(previous["source_scope"])
                if "stage_source_scope_changed" in reasons else _stage_source_scope(refs, scope))
        cleaned = [ref for ref in history if not isinstance(ref, dict) or ref.get("method") != METHOD]
        for ref in unique.values():
            cleaned.append({**ref, "method": METHOD, "input_method": ref["method"],
                            "input_field": ref["field"],
                            **({"input_value": ref["value"]} if "value" in ref else {}),
                            "value": value, "draft": True})
        provenance[field] = cleaned
    if result.get('案件类别') == '民事':
        from intake_contract_date import FIELD as date_field
        keys=(date_field,'收案日期')
        has_value=any(_value(result,key) for key in keys)
        human=any(key in manual or _human_value(result,key) for key in keys)
        if not has_value and not human:
            statuses[date_field]={'status':'insufficient','reason_codes':['contract_date_unavailable_or_conflicting'],
                                  'source_count':0,'value_digest':_digest('')}
    result["_provenance"] = provenance
    result["_form_draft_sources"] = sources
    result["_form_drafts"] = {"version": VERSION, "fields": statuses}
    return result


def draft_review_summary(fields):
    from source_form_policy import draft_field_needs_generated_form
    # Keep extracted facts and provenance intact. Only stop asking the user to
    # fill a replacement form when the actual source form is already retained.
    statuses = {key:value for key,value in ((fields.get("_form_drafts") or {}).get("fields") or {}).items()
                if draft_field_needs_generated_form(fields,key)}
    layout = [field for field in DRAFT_FIELDS if (statuses.get(field) or {}).get("status") == "insufficient"
              and "draft_too_long_for_original_cell" in (statuses.get(field) or {}).get("reason_codes", [])]
    stage_only = ["结案小结"] if ((statuses.get("结案小结") or {}).get("status") == "generated"
                 and "stage_summary_not_final_closure" in (statuses.get("结案小结") or {}).get("reason_codes", [])) else []
    return {"generated_count": sum(item.get("status") == "generated" for item in statuses.values()),
            **({"stage_summary_fields": stage_only} if stage_only else {}),
            "insufficient_fields": [field for field in (*DRAFT_FIELDS,'立案审批日期') if (statuses.get(field) or {}).get("status") == "insufficient" and field not in layout],
            "layout_review_fields": layout,
            # These two codes explain a successful derivation, not missing
            # information. Preserve them in the audit without asking for a
            # redundant field review. Unknown/caution codes remain visible.
            "review_fields": [field for field in DRAFT_FIELDS if any(reason not in (
                                  "attributed_pleading_excerpt", "explicit_project_name_preserved")
                                  for reason in (statuses.get(field) or {}).get("reason_codes", []))
                              and (statuses.get(field) or {}).get("status") == "generated"]}


def draft_review_message(fields):
    """One shared non-blocking form summary for initial analysis and saves."""
    summary = draft_review_summary(fields)
    parts = []
    if summary["generated_count"]:
        parts.append(f"已按材料整理 {summary['generated_count']} 项表格内容")
    if summary["insufficient_fields"]:
        parts.append("材料不足，已留空：" + "、".join(summary["insufficient_fields"]))
    if summary["layout_review_fields"]:
        parts.append("完整依据已保留，原表空间有限，待简要填写：" + "、".join(summary["layout_review_fields"]))
    if summary["review_fields"]:
        parts.append("信息可能不完整：" + "、".join(summary["review_fields"]))
    if summary.get("stage_summary_fields"):
        parts.append("结案小结栏仅整理有据阶段工作或协议状态；阶段记录不证明正式结案，也不证明付款或履行")
    return ("；".join(parts) + "。文书清单不证明已送达，草稿不代替审批或签章" if parts else ""), summary
