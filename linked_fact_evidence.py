"""Conservative contact links between already-read, in-case evidence pages.

This is a reviewable same-name link, not legal-identity verification. The caller
owns the unique accepted client/conflict decision and the current source scope.
No I/O, new page reads, model calls or changes to the supplied facts occur here.
"""
from __future__ import annotations

from copy import deepcopy
import re

from fact_evidence import validate_fact


_METHODS = frozenset(("local_agent", "visual_agent_local_evidence"))
_NAMES = ("聘方名称", "聘方", "委托人名称", "委托方名称", "委托单位名称", "委托人", "委托方", "委托单位")
_IDENTITY_NAMES = ("聘方暨委托人", "聘方即委托人", "委托人暨本案被告人", "委托人即本案被告人",
                   "委托人暨本案原告", "委托人即本案原告", "委托人暨本案被告", "委托人即本案被告")
_ADDRESS = ("聘方住所", "聘方地址", "聘方联系地址", "委托人住所", "委托人地址", "委托人联系地址", "委托方住所", "委托方地址", "联系地址", "住所", "地址")
_PHONE = ("聘方联系电话", "聘方电话", "委托人联系电话", "委托人电话", "委托方联系电话", "委托方电话", "联系电话", "电话")
_OTHERS = ("受聘方", "受托方", "受托人", "律师事务所", "对方", "相对方", "相对人", "第三人", "原告", "被告", "甲方", "乙方", "企业名称", "单位名称", "客户名称", "服务对象", "姓名", "名称")
_IDS = ("统一社会信用代码", "身份证号码", "身份证号", "组织机构代码")
_LABELS = (*_NAMES, *_IDENTITY_NAMES, *_ADDRESS, *_PHONE, *_OTHERS, *_IDS)
_LABEL = re.compile(r"(?:^|[。;；!！?？\r\n])\s*(?P<label>" + "|".join(sorted(map(re.escape, _LABELS), key=len, reverse=True)) + r")\s*[:：]\s*")
_UNSAFE = re.compile(r"对方|相对方|相对人|第三人|另案|其他案件|示例|参考案例|引用|引述|转述|声称|诉称|辩称|拟|计划|预计|假设|假如|临时|暂住|旧址|曾用|更名|已迁|不是|并非|尚未")
_OFFICE_CONTACT = re.compile(r"(?:律师事务所|律所|本所|受聘方|受托方|受托人)[^。;；\r\n]{0,12}(?:地址|住所|电话|办公信息)")
_COMPARE_KEYS = ("source_path", "page", "quote", "value", "method")


def _compact(value):
    # Names are not case-folded, abbreviated or normalized across Unicode glyphs.
    return re.sub(r"\s+", "", value) if isinstance(value, str) else ""


def _ref_key(value):
    if (isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str)
            and value[0].strip() and type(value[1]) is int and value[1] > 0):
        return value
    return None


def _records(text):
    """Keep wrapped values; a newline alone must not truncate a party name."""
    matches = list(_LABEL.finditer(text))
    records = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        stops = [pos for mark in "。;；!！?？" if (pos := text.find(mark, match.end(), end)) >= 0]
        if stops:
            end = min(stops)
        records.append((match["label"], _compact(text[match.end():end]), match.start(), end))
    return records


def _single_name(value):
    return (isinstance(value, str) and 2 <= len(_compact(value)) <= 120
            and not re.search(r"[,，、;；。:：\[\]【】/|&]|及|以及|等人|(?:公司|银行|事务所)(?:和|与)", _compact(value)))


def _client_identifier(records):
    ids = {}
    for label, value, _, _ in records:
        if label in _IDS:
            category = "personal" if label.startswith("身份证") else label
            if not re.fullmatch(r"[A-Za-z0-9-]{5,30}", value) or category in ids:
                return None
            ids[category] = value
    return ids


def _current_client(fields):
    if not isinstance(fields, dict) or not _single_name(fields.get("委托人")):
        return None
    for conflict in fields.get("_field_conflicts") or []:
        if isinstance(conflict, dict) and conflict.get("field") in ("委托人", "委托人名称", "委托方") and not conflict.get("resolved"):
            return None
    client = fields["委托人"]
    for alias in ("委托人名称", "委托方"):
        value = fields.get(alias)
        if isinstance(value, str) and _compact(value) and _compact(value) != _compact(client):
            return None
        refs = (fields.get("_provenance") or {}).get(alias) or []
        refs = [refs] if isinstance(refs, dict) else refs
        if alias in fields and not _compact(value) and any(
                isinstance(ref, dict) and ref.get("method") == "human" for ref in refs):
            return None
    return client


def current_contact_support(ref, fields):
    """Return fresh identity supports, [] for ordinary refs, or None if stale.

    The caller must separately recheck every returned page against its current
    manifest. Matching provenance is not permission to read arbitrary sources.
    """
    if not isinstance(ref, dict):
        return None
    if ref.get('binding') == 'batch_engagement_intake':
        from engagement_intake import current_support
        return current_support(ref, fields)
    if ref.get('binding') == 'pleading_parties':
        from pleading_parties import current_support
        return current_support(ref, fields)
    if ref.get('binding') == 'case_fee_settlement':
        from fee_settlement_evidence import current_support
        return current_support(ref, fields)
    if ref.get('binding') == 'selected_notice_fee':
        from source_fee_notice import current_support
        return current_support(ref, fields)
    if ref.get('binding') == 'court_report_summary':
        from court_report_summary import current_support
        return current_support(ref, fields)
    if ref.get('binding')=='court_party_details':
        from court_roster_details import current_detail_support
        return current_detail_support(ref,fields)
    if ref.get("binding") == "client_court_party":
        from source_party_evidence import current_client_party_support
        return current_client_party_support(ref, fields)
    if "binding" not in ref and "supporting_sources" not in ref:
        return []
    if ref.get("binding") != "client_contact":
        return None
    if ref.get("method") == "derived_form_draft":
        # A combined contact draft must be backed by the *current* input fact,
        # not merely by an inherited identity-support label. Its value is the
        # combined sentence, so validate the original input value separately.
        key = ref.get("input_field")
        if (key not in ("地址", "委托人电话") or ref.get("input_method") not in _METHODS
                or not isinstance(fields, dict) or not _compact(fields.get(key))):
            return None
        if any(isinstance(row, dict) and row.get("field") == key and not row.get("resolved")
               for row in fields.get("_field_conflicts") or []):
            return None
        provenance = fields.get("_provenance")
        if not isinstance(provenance, dict):
            return None
        originals = provenance.get(key) or []
        originals = [originals] if isinstance(originals, dict) else originals
        if not isinstance(originals, list):
            return None
        for original in originals:
            if (isinstance(original, dict) and original.get("method") == ref["input_method"]
                    and _compact(original.get("value")) == _compact(fields[key])
                    and all(original.get(item) == ref.get(item) for item in
                            ("source_path", "page", "quote", "binding", "supporting_sources"))):
                return current_contact_support(original, fields)
        return None
    if ref.get("method") not in _METHODS:
        return None
    supports = ref.get("supporting_sources")
    client = _current_client(fields)
    if not client or not isinstance(supports, list) or not 1 <= len(supports) <= 4:
        return None
    provenance = fields.get("_provenance")
    if not isinstance(provenance, dict):
        return None
    current = provenance.get("委托人") or []
    current = [current] if isinstance(current, dict) else current
    if not isinstance(current, list):
        return None
    for support in supports:
        if (not isinstance(support, dict) or support.get("field") != "委托人"
                or support.get("method") not in _METHODS
                or _compact(support.get("value")) != _compact(client)
                or not _ref_key((support.get("source_path"), support.get("page")))
                or not isinstance(support.get("quote"), str) or not support["quote"].strip()
                or "binding" in support or "supporting_sources" in support):
            return None
        if not any(isinstance(old, dict) and old.get("method") in _METHODS
                   and all(old.get(key) == support.get(key) for key in _COMPARE_KEYS)
                   for old in current):
            return None
    return deepcopy(supports)


def validate_contact_page(fact, candidate_text, client_value):
    """Shared full-page contact semantics, not a substitute for identity proof."""
    if not isinstance(fact, dict) or fact.get("field") not in ("地址", "委托人电话"):
        return None
    value, quote = fact.get("value"), fact.get("quote")
    if (not _single_name(client_value) or not isinstance(candidate_text, str)
            or not isinstance(value, str) or not 0 < len(value) <= 1000
            or not isinstance(quote, str) or not 0 < len(quote) <= 1500
            or not _compact(value) or _compact(quote) not in _compact(candidate_text)
            or _compact(value) not in _compact(quote)):
        return None
    if _UNSAFE.search(candidate_text) or _OFFICE_CONTACT.search(candidate_text):
        return None
    records = _records(candidate_text)
    names = [row for row in records if row[0] in _NAMES]
    if (len(names) != 1 or names[0][1] != _compact(client_value)
            or any(row[0] in _OTHERS for row in records)):
        return None
    labels = _ADDRESS if fact["field"] == "地址" else _PHONE
    contacts = [row for row in records if row[0] in labels]
    if len(contacts) != 1:
        return None
    contact = contacts[0]
    if (contact[1] != _compact(value) or contact[2] <= names[0][2]
            or not re.search(re.escape(contact[0]) + r"[:：]" + re.escape(_compact(value)), _compact(quote))):
        return None
    if fact["field"] == "委托人电话":
        if (not re.fullmatch(r"\+?[0-9()（） -]+", value.strip())
                or not 7 <= len(re.sub(r"\D", "", value)) <= 18):
            return None
    elif re.search(r"^(?:未提供|未记载|不详|未知|待定|无|空白)$", _compact(value)):
        return None
    identifiers = _client_identifier(records)
    if identifiers is None:
        return None
    return identifiers


def contact_page_candidates(page_text, client_value):
    """At most one address and one phone, using contiguous original quotations."""
    if not isinstance(page_text, str) or len(page_text) > 18000:
        return []
    result = []
    for label, _value, start, end in _records(page_text):
        field = "地址" if label in _ADDRESS else "委托人电话" if label in _PHONE else None
        if field is None:
            continue
        quote = page_text[start:end].lstrip("。;；!！?？\r\n \t").rstrip()
        match = re.fullmatch(re.escape(label) + r"\s*[:：]\s*(?P<value>[\s\S]+)", quote)
        if match:
            fact = {"field": field, "value": match["value"].strip(), "quote": quote}
            if validate_contact_page(fact, page_text, client_value) is not None:
                result.append(fact)
    return result[:2]


def contact_page_has_identifiers(page_text):
    # Without the old full page we cannot compare any supplied legal identity ID.
    return isinstance(page_text, str) and any(label in page_text for label in _IDS)


def contact_identifier_review_fields(page_text, client_value):
    """Locate a review, not a fact, when an unverified ID prevents linking."""
    if not isinstance(page_text, str) or _UNSAFE.search(page_text) or _OFFICE_CONTACT.search(page_text):
        return set()
    rows = _records(page_text)
    names = [row for row in rows if row[0] in _NAMES]
    if (len(names) != 1 or names[0][1] != _compact(client_value)
            or any(row[0] in _OTHERS for row in rows)):
        return set()
    return {field for field, labels in (("地址", _ADDRESS), ("委托人电话", _PHONE))
            if any(row[0] in labels for row in rows)}


def link_client_contact_fact(fact, *, candidate_source, candidate_text, client_value,
                             client_refs, texts_by_ref, allowed_refs):
    """Link an explicit contact field to a uniquely named, evidenced client.

    Only data in texts_by_ref is considered; model-supplied support references
    are ignored. Failure leaves the original candidate for ordinary review.
    """
    if (not isinstance(fact, dict) or fact.get("field") not in ("地址", "委托人电话")
            or not _single_name(client_value) or not isinstance(texts_by_ref, dict)
            or not isinstance(allowed_refs, (set, frozenset))
            or not isinstance(client_refs, (list, tuple)) or not 1 <= len(client_refs) <= 4):
        return None
    source = _ref_key(candidate_source)
    value, quote = fact.get("value"), fact.get("quote")
    if (source is None or source not in allowed_refs or not isinstance(candidate_text, str)
            or texts_by_ref.get(source) != candidate_text
            or not isinstance(value, str) or not 0 < len(value) <= 1000
            or not isinstance(quote, str) or not 0 < len(quote) <= 1500
            or not _compact(value) or _compact(quote) not in _compact(candidate_text)
            or _compact(value) not in _compact(quote)):
        return None
    identifiers = validate_contact_page(fact, candidate_text, client_value)
    if identifiers is None:
        return None
    supports = []
    for ref in client_refs:
        if not isinstance(ref, dict) or ref.get("method") not in _METHODS or "binding" in ref or "supporting_sources" in ref:
            return None
        key = _ref_key((ref.get("source_path"), ref.get("page")))
        text = texts_by_ref.get(key) if key in allowed_refs else None
        if (key is None or not isinstance(text, str)
                or _compact(ref.get("value")) != _compact(client_value)
                or not isinstance(ref.get("quote"), str)
                or not validate_fact("委托人", client_value, ref["quote"], text)):
            return None
        # Recheck the actual labelled occurrence, not an unrelated later mention
        # of the same name. The existing validator alone may accept a prefix.
        ref_records = _records(text)
        source_names = [row for row in ref_records if row[0] in (*_NAMES, *_IDENTITY_NAMES)]
        if len(source_names) != 1 or source_names[0][1] != _compact(client_value):
            return None
        identity = source_names[0]
        if (_UNSAFE.search(text[:identity[2]])
                or not re.search(re.escape(identity[0]) + r"[:：]" + re.escape(identity[1]), _compact(ref["quote"]))):
            return None
        # Read only identifiers within the client's block, never the firm's ID.
        identity_ids = {}
        for row in ref_records:
            if row[2] <= identity[2]:
                continue
            if row[0] in _OTHERS:
                break
            if row[0] in _IDS:
                category = "personal" if row[0].startswith("身份证") else row[0]
                if category in identity_ids:
                    return None
                identity_ids[category] = row[1]
        for category, identifier in identity_ids.items():
            if category in identifiers and identifiers[category] != identifier:
                return None
            identifiers[category] = identifier
        supports.append({**deepcopy(ref), "field": "委托人"})
    return {"source_path": source[0], "page": source[1], "quote": quote, "value": value,
            "method": "visual_agent_local_evidence", "binding": "client_contact",
            "supporting_sources": supports}
