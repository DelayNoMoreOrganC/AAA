"""Invalidate machine party/court values whose case identity is no longer current."""
from __future__ import annotations

import copy
import hashlib
import json
import os

FIELD = "对方当事人"
REVIEW_KEY = "_party_binding_review"
KIND = "party_binding"
METHODS = {"visual_agent_local_evidence", "local_agent"}
_FIELDS = {
    '立案审批日期': {
        'binding': 'intake_contract_date_default', 'reason': 'intake_contract_date_stale',
        'identity': ('委托人', '对方当事人', '案由', '_intake_contract_date_source'),
        'message': '委托合同日期依据或案件信息已变化，审批表默认日期已留空，请核对本案合同日期',
    },
    '案件或项目名称': {
        'binding': 'pleading_parties', 'reason': 'pleading_roster_binding_stale',
        'identity': ('案件或项目名称',),
        'message': '诉状主体或案由依据已变更，原自动案件名称已留空；请核对当前材料',
    },
    '收费标准': {
        'binding': 'selected_notice_fee', 'reason': 'fee_notice_binding_stale',
        'identity': ('委托人', '委托人名称', '委托方', '对方当事人', '案由'),
        'message': '收费通知书依据或对应案件已变更，原自动收费说明已留空；请核对当前条款',
    },
    "当事人": {
        "binding": "client_court_party", "reason": "client_court_party_binding_stale",
        "identity": ("委托人", "委托人名称", "委托方", "案号", "法院收案号"),
        "message": "委托人、案号或法院文书依据已变更或不再适用，原自动当事人信息已留空；请核对关联原页后填写，或确认保留空白",
    },
    FIELD: {
        "binding": "same_page_opponent", "reason": "client_binding_stale",
        "identity": ("委托人", "委托人名称", "委托方", "当事人", "案号", "法院收案号"),
        "message": "委托人身份已变更或依据不再适用，原自动对方信息已留空；请核对原件后填写，或确认保留空白",
    },
    "审理法院": {
        "binding": "court_case_number", "reason": "court_binding_stale",
        "identity": ("案号", "法院收案号"),
        "message": "当前案号或法院文书依据已变更或不再适用，原自动法院信息已留空；请核对原件后填写，或确认保留空白",
    },
    "地址": {
        "binding": "client_contact", "reason": "client_contact_binding_stale",
        "identity": ("委托人", "委托人名称", "委托方"),
        "message": "委托人身份或联系依据已变更，原自动地址已留空；请核对两处原页后填写，或确认保留空白",
    },
    "委托人电话": {
        "binding": "client_contact", "reason": "client_contact_binding_stale",
        "identity": ("委托人", "委托人名称", "委托方"),
        "message": "委托人身份或联系依据已变更，原自动电话已留空；请核对两处原页后填写，或确认保留空白",
    },
    '结案小结': {
        'binding': 'court_report_summary', 'reason': 'court_report_sources_stale',
        'identity': ('委托人', '委托人名称', '委托方', '对方当事人', '案由', '案号', '执行案号'),
        'message': '判决或执行通知书依据、案件信息已变更，原自动结案摘要已留空；请核对当前材料',
    },
}
for _fee_field in ('应收业务费', '已收业务费', '尚欠业务费', '应退业务费'):
    _FIELDS[_fee_field] = {
        'binding': 'case_fee_settlement', 'reason': 'fee_settlement_binding_stale',
        'identity': ('委托人', '案号', '合同号'),
        'message': '费用结算依据或案件身份已变化，原自动金额已留空，请核对本案费用记录',
    }


def _refs(fields, field=FIELD):
    refs = (fields.get("_provenance") or {}).get(field) or []
    return [refs] if isinstance(refs, dict) else refs if isinstance(refs, list) else []


def _scope(manifest):
    return {os.path.normcase(os.path.abspath(row["path"])): row for row in manifest or []
            if isinstance(row, dict) and isinstance(row.get("path"), str)
            and row["path"] and type(row.get("pages")) is int and row["pages"] > 0}


def _anchor(ref, scope):
    path, page = ref.get("source_path"), ref.get("page")
    row = scope.get(os.path.normcase(os.path.abspath(path))) if isinstance(path, str) and path else None
    if (not row or type(page) is not int or not 1 <= page <= row["pages"]
            or (ref.get("file_id") and ref["file_id"] != row.get("file_id"))):
        return None
    return {"source_path": row["path"], "page": page}


def reconcile_party_bindings(fields, manual_fields, source_manifest):
    """Return a copy: clear obsolete automatic values, retain all source history.

    Never recover a cleared value merely because an old client/number returns.
    Explicit manual values (including blanks) retain precedence. Independent
    current evidence for the same value also avoids deleting a supported fact.
    """
    result = copy.deepcopy(fields or {})
    manual = manual_fields or {}
    reviews = result.get(REVIEW_KEY) or []
    current_reviews = []
    scope = _scope(source_manifest)
    for field, spec in _FIELDS.items():
        review = next((item for item in reviews if isinstance(item, dict) and item.get("field") == field), None)
        current = result.get(field)
        refs = _refs(result, field)
        if field in manual or any(isinstance(ref, dict) and ref.get("method") == "human"
                                  and ref.get("value") == current for ref in refs):
            if field in manual:
                result[field] = manual[field]
            review = None
        elif isinstance(current, str) and current.strip():
            matching = [ref for ref in refs if isinstance(ref, dict) and ref.get("value") == current]
            linked = [ref for ref in matching if ref.get("binding") == spec["binding"]
                      or (field in ('当事人', '对方当事人', '地址') and ref.get('binding') == 'pleading_parties')
                      or (field in ('对方当事人','地址','委托人电话') and ref.get('binding')=='court_party_details')]
            fee = spec['binding'] == 'case_fee_settlement'
            if fee:
                linked = [ref for ref in matching if ref.get('method') in METHODS]
            if linked:
                from .evidence_links import supporting_refs
                supported = any(ref.get("method") in METHODS and (not fee or ref.get('binding') == spec['binding']) and _anchor(ref, scope)
                                and supporting_refs(ref, result, source_manifest) is not None for ref in matching)
                if supported:
                    review = None
                else:
                    result[field] = ""
                    anchors = []
                    locations = [item for ref in linked for item in
                                 [ref, *(ref.get("supporting_sources") or [])] if isinstance(item, dict)]
                    for ref in locations:
                        anchor = _anchor(ref, scope)
                        if anchor and anchor not in anchors:
                            anchors.append(anchor)
                    review = {"field": field, "reason_code": spec["reason"], "sources": anchors}
            elif matching:
                review = None
        if review:
            # A later identity edit is a new review context. Do not reuse an
            # older acknowledgement or put identity values in the issue text.
            identity = [result.get(key) for key in spec["identity"]]
            if any(ref.get('binding') == 'pleading_parties' for ref in refs if isinstance(ref, dict)):
                identity.append(result.get('_pleading_parties_source'))
            identity.append(result.get("_field_conflicts") or [])
            review["context_signature"] = hashlib.sha256(json.dumps(identity, ensure_ascii=False,
                sort_keys=True, default=str).encode()).hexdigest()[:20]
            current_reviews.append(review)
    if current_reviews or REVIEW_KEY in result:
        result[REVIEW_KEY] = current_reviews
    return result


def party_binding_issues(fields, source_manifest):
    """One advisory per bound field, with current-case anchors and no body text."""
    from .task_workflow import issue
    reviews = (fields or {}).get(REVIEW_KEY) or []
    scope = _scope(source_manifest)
    issues = []
    for field, spec in _FIELDS.items():
        review = next((item for item in reviews if isinstance(item, dict) and item.get("field") == field), None)
        if not review:
            continue
        pages = []
        for ref in review.get("sources") or []:
            anchor = _anchor(ref, scope) if isinstance(ref, dict) else None
            if not anchor:
                continue
            row = scope[os.path.normcase(os.path.abspath(anchor["source_path"]))]
            shown = {"file_id": row.get("file_id"), "filename": row.get("filename", ""), "page": anchor["page"]}
            if shown not in pages:
                pages.append(shown)
        issues.append(issue(KIND, spec["message"],
            detail={"field": field, "reason_code": spec["reason"], "pages": pages,
                    "context_signature": review.get("context_signature", "")}, blocking=False))
    return issues


def sync_party_binding_issues(issues, fields, source_manifest):
    return [entry for entry in issues or [] if entry.get("kind") != KIND] + party_binding_issues(fields, source_manifest)
