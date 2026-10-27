"""A court's explicit party roster linked to existing client/case evidence.

No I/O, inferred representation, or identity equivalence beyond the complete
name. Source ownership/hash and human edits remain caller responsibilities.
"""
from copy import deepcopy
import os
import re

from fact_evidence import validate_fact
from linked_party_evidence import current_party_binding_supported
from source_court_evidence import extract_court_header_candidate, current_court_binding_supported

_METHODS = frozenset(("local_agent", "visual_agent_local_evidence"))
_ROLES = ("被上诉人", "上诉人", "被告人", "原告", "被告")
_ROLE = re.compile(r"(?:^|[。;；\r\n])\s*(?:本案)?(?P<role>" + "|".join(_ROLES) + r")\s*[:：]\s*")
_DISCLAIMER = re.compile(
    r"(?:上述|以上|前述|所列|本页|本件|该)(?:的)?(?:当事人|诉讼|原被告|原告|被告|上诉人|被上诉人|各方|身份|名单)[^。;；!?！？]{0,45}"
    r"(?:假设|假定|拟|示例|参考|引用|转述|未确认|未获|尚未|并非|不是|不属于|另案)|"
    r"(?:假设|假定|假如|如果|拟|示例|参考|引用|转述|声称|诉称|辩称|不能认定|并非|不是)[^。;；\r\n]{0,20}(?:原告|被告|上诉人|当事人)[:：]")
_IDS = re.compile(r"(?P<label>统一社会信用代码|组织机构代码|身份证号码|身份证号)\s*[:：]?\s*(?P<value>[A-Za-z0-9-]{5,30})(?![A-Za-z0-9-])")
_ID_LABEL = re.compile(r"统一社会信用代码|组织机构代码|身份证(?:号码|号)")
_COMPARE = ("source_path", "page", "quote", "method")


def _name(value):
    return re.sub(r"\s+", "", value) if isinstance(value, str) else ""


def _number(value):
    return _name(value).translate(str.maketrans("（）", "()"))


def _rows(provenance, field):
    rows = provenance.get(field, []) if isinstance(provenance, dict) else []
    return [rows] if isinstance(rows, dict) else rows


def _equal(field, left, right):
    compare = _number if field == "案号" else _name
    return bool(compare(left)) and compare(left) == compare(right)


def _same_ref(field, left, right):
    return (isinstance(left, dict) and isinstance(right, dict)
            and _equal(field, left.get("value"), right.get("value"))
            and all(left.get(key) == right.get(key) for key in _COMPARE)
            and all(left.get(key) == right.get(key) for key in ("file_id", "source_sha256")
                    if left.get(key) is not None and right.get(key) is not None))


def _party_declaration(page_text, client_value, current_case_number):
    """Read only the bounded roster after a current judicial heading.

    Only the uniquely matched complete client is represented. Other named
    people in that role are not silently added to the represented-party field.
    """
    if not isinstance(page_text, str) or not _name(client_value) or _DISCLAIMER.search(page_text):
        return None
    heading = extract_court_header_candidate(page_text, current_case_number)
    if not heading or not re.search(r"(?:民事|行政|刑事)(?:判决书|裁定书|调解书)", _name(heading["quote"])):
        return None
    start = page_text.find(heading["quote"])
    end = start + len(heading["quote"])
    # Do not seek through a narrative or quoted roster. Stop at the court's
    # narrative; roles mentioned in reasons are not the heading's declarations.
    body = page_text[end:end+1500]
    stop = re.search(r"(?:^|[。;；\r\n])\s*(?:本院|本案(?:现|于|经|由|系)|经审理|判决如下|裁定如下)", body)
    if stop:
        body = body[:stop.start()]
    matches = list(_ROLE.finditer(body))
    if not matches or body[:matches[0].start()].strip():
        return None
    roster = []
    for index, match in enumerate(matches):
        limit = matches[index+1].start() if index+1 < len(matches) else len(body)
        remainder = body[match.end():limit]
        boundary = re.search(r"[。;；,，]", remainder)
        if boundary is None:
            # A final unpunctuated line can be complete only at the original
            # page edge or a separately recognized next roster/narrative line.
            if end + len(body) < len(page_text) and not stop and index+1 == len(matches):
                return None
            name_end = limit
        else:
            name_end = match.end() + boundary.start()
        raw = body[match.end():name_end].strip()
        if not raw or len(_name(raw)) > 120:
            return None
        roster.append((match["role"], raw, match.end(), name_end, limit))
    found = [row for row in roster if _name(row[1]) == _name(client_value)]
    if len(found) != 1:
        return None
    role, value, value_start, name_end, limit = found[0]
    title = _name(heading["quote"])
    if role == "被告人" and "刑事" not in title:
        return None
    if role in ("原告", "被告") and "刑事" in title:
        return None
    return ({"field": "当事人", "value": value,
            "quote": page_text[start:end+name_end].strip(),
            "binding": "client_court_party", "subject": client_value,
            "case_number": current_case_number, "role": role}, body[value_start:limit])


def extract_current_party_candidate(page_text, client_value, current_case_number):
    result = _party_declaration(page_text, client_value, current_case_number)
    return result[0] if result else None


def _identifiers(block):
    # A representative's identity number does not identify the represented
    # company. Stop before a separately labelled representative/agent.
    block = re.split(r"法定代表人|负责人|委托(?:诉讼)?代理人|代理律师", block, maxsplit=1)[0]
    ids = {}
    matches = list(_IDS.finditer(block))
    if len(matches) != len(list(_ID_LABEL.finditer(block))):
        return None
    for match in matches:
        category = "身份证" if match["label"].startswith("身份证") else match["label"]
        if category in ids:
            return None
        ids[category] = match["value"]
    return ids


def _client_identifiers(text, client):
    # The already-validated client occurrence, not the law firm's adjacent ID.
    from source_engagement_evidence import poa_candidates
    if any(row['field']=='委托人' and _name(row['value'])==_name(client)
           for row in poa_candidates(text)):
        # This closed POA layout contains only the client name before the
        # lawyer roster. It carries no client ID; lawyer records must not be
        # misread as additional clients or their identifiers.
        return None if _ID_LABEL.search(text) else {}
    from linked_fact_evidence import _records, _NAMES, _IDENTITY_NAMES, _OTHERS
    records = _records(text)
    names = [row for row in records if row[0] in (*_NAMES, *_IDENTITY_NAMES)]
    if len(names) != 1 or names[0][1] != _name(client):
        return None
    start = names[0][2]
    end = next((row[2] for row in records if row[2] > start and row[0] in _OTHERS), len(text))
    return _identifiers(text[start:end])


def _cached_client_ids(rows, fields, page_cache, allowed_sources):
    ids = {}
    for row in rows:
        if (not isinstance(row, dict) or row.get("method") not in _METHODS
                or not _equal("委托人", row.get("value"), fields.get("委托人"))):
            continue
        source = (row.get("source_path"), row.get("page"))
        text = page_cache.get(source) if source in allowed_sources else None
        if not isinstance(text, str) or not validate_fact("委托人", fields["委托人"], row.get("quote"), text):
            continue
        current = _client_identifiers(text, fields["委托人"])
        if current is None or any(key in ids and ids[key] != value for key, value in current.items()):
            return None
        ids.update(current)
    return ids


def current_client_party_support(ref, fields):
    """Fresh dual supports or None. Callers recheck all three source scopes."""
    if not isinstance(ref, dict) or ref.get("binding") != "client_court_party" or not isinstance(fields, dict):
        return None
    if ref.get("method") == "derived_form_draft":
        if (ref.get("input_field") != "当事人" or ref.get("input_method") not in _METHODS
                or not _equal("当事人", ref.get("input_value"), fields.get("当事人"))):
            return None
        originals = _rows(fields.get("_provenance"), "当事人")
        if not isinstance(originals, list):
            return None
        for original in originals:
            if (isinstance(original, dict) and original.get("method") == ref["input_method"]
                    and _equal("当事人", original.get("value"), ref["input_value"])
                    and all(original.get(key) == ref.get(key) for key in
                            (*_COMPARE[:3], "binding", "subject", "case_number", "role", "supporting_sources"))
                    and all(original.get(key) == ref.get(key) for key in ("file_id", "source_sha256") if key in ref)):
                return current_client_party_support(original, fields)
        return None
    if (ref.get("method") not in _METHODS or ref.get("role") not in _ROLES
            or not _equal("委托人", ref.get("value"), ref.get("subject"))
            or not current_party_binding_supported({"binding": "same_page_opponent", "subject": ref.get("subject")}, fields)
            or not current_court_binding_supported({"binding": "court_case_number", "case_number": ref.get("case_number")}, fields)):
        return None
    # Recheck the stored literal declaration, not a mutable role tag. This is
    # consistency of the saved span, not a substitute for the original full
    # page checks at adoption or the caller's current source/hash checks.
    declaration = extract_current_party_candidate(ref.get("quote"), ref.get("subject"), ref.get("case_number"))
    if (not declaration or declaration["role"] != ref["role"]
            or not _equal("当事人", declaration["value"], ref.get("value"))
            or (_name(fields.get("当事人")) and not _equal("当事人", fields["当事人"], ref["value"]))):
        return None
    if any(not isinstance(row, dict) or (row.get("field") == "当事人" and row.get("resolved") is not True)
           for row in fields.get("_field_conflicts", [])):
        return None
    target_refs = _rows(fields.get("_provenance"), "当事人")
    if (not isinstance(target_refs, list) or ("当事人" in fields and not _name(fields["当事人"])
            and any(isinstance(row, dict) and row.get("method") == "human" for row in target_refs))):
        return None
    supports = ref.get("supporting_sources")
    if not isinstance(supports, list) or not 2 <= len(supports) <= 4:
        return None
    supported = set()
    for support in supports:
        if not isinstance(support, dict):
            return None
        field = support.get("field")
        if field not in ("委托人", "案号"):
            return None
        rows = _rows(fields.get("_provenance"), field)
        if (field not in ("委托人", "案号") or support.get("method") not in _METHODS
                or not _equal(field, support.get("value"), fields.get(field))
                or not isinstance(support.get("source_path"), str) or not support["source_path"]
                or type(support.get("page")) is not int or support["page"] < 1
                or not isinstance(support.get("quote"), str) or not support["quote"].strip()
                or "binding" in support or "supporting_sources" in support
                or not isinstance(rows, list) or not any(_same_ref(field, row, support) for row in rows)):
            return None
        supported.add(field)
    return deepcopy(supports) if supported == {"委托人", "案号"} else None


def _path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ""


def _in_scope(row, page):
    return (isinstance(row, dict) and isinstance(row.get("file_id"), str) and bool(row["file_id"])
            and isinstance(row.get("sha256"), str) and bool(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]))
            and type(row.get("pages")) is int and type(page) is int and 1 <= page <= row["pages"])


def link_client_court_party(page_text, source, fields, *, page_cache, allowed_sources, supplied=None):
    """Revalidate cached sources or a server-issued parent source certificate.

    The latter is internal context, never model input. A saved quotation is not
    passed as a fabricated full page. Missing parent certificates fail closed.
    """
    if source not in allowed_sources or page_cache.get(source) != page_text:
        return None
    declaration = _party_declaration(page_text, fields.get("委托人"), fields.get("案号"))
    if not declaration:
        return None
    candidate, client_block = declaration
    candidate_ids = _identifiers(client_block)
    if candidate_ids is None:
        return None
    supports = []
    scope = supplied.get("party_source_scope", []) if isinstance(supplied, dict) else []
    certificates = supplied.get("party_provenance", {}) if isinstance(supplied, dict) else {}
    if not isinstance(scope, list):
        return None
    by_path = {_path(row.get("path")): row for row in scope if isinstance(row, dict)}
    if scope and (len(by_path) != len(scope) or "" in by_path):
        return None
    primary = by_path.get(_path(source[0]))
    for field in ("委托人", "案号"):
        rows = _rows(fields.get("_provenance"), field)
        if not isinstance(rows, list):
            return None
        if field == "委托人":
            known_ids = _cached_client_ids(rows, fields, page_cache, allowed_sources)
            if known_ids is None or any(key in known_ids and known_ids[key] != value for key, value in candidate_ids.items()):
                return None
        chosen = None
        for ref in rows:
            if (not isinstance(ref, dict) or ref.get("method") not in _METHODS
                    or not _equal(field, ref.get("value"), fields.get(field))
                    or "binding" in ref or "supporting_sources" in ref):
                continue
            key = (ref.get("source_path"), ref.get("page"))
            if key in allowed_sources and isinstance(page_cache.get(key), str):
                if validate_fact(field, fields[field], ref.get("quote"), page_cache[key]):
                    if field == "委托人":
                        old_ids = _client_identifiers(page_cache[key], fields[field])
                        if old_ids is None or any(label in old_ids and old_ids[label] != value
                                                  for label, value in candidate_ids.items()):
                            return None
                    chosen = {**deepcopy(ref), "field": field}
                    break
            else:
                if field == "委托人" and candidate_ids:
                    # Parent certificates carry quotes, not complete old-page
                    # identity blocks. Never pretend an unobserved ID matched.
                    continue
                stored = certificates.get(field, []) if isinstance(certificates, dict) else []
                if not isinstance(stored, list):
                    continue
                for cert in stored:
                    if not isinstance(cert, dict):
                        continue
                    row = by_path.get(_path(cert.get("source_path"))) if isinstance(cert, dict) else None
                    if (_in_scope(row, cert.get("page")) and _same_ref(field, ref, cert) and cert.get("field") == field
                            and cert.get("file_id") == row.get("file_id")
                            and cert.get("source_sha256") == row.get("sha256")
                            and isinstance(cert.get("source_sha256"), str)
                            and re.fullmatch(r"[0-9a-f]{64}", cert["source_sha256"])):
                        chosen = deepcopy(cert)
                        break
            if chosen:
                break
        if not chosen:
            return None
        supports.append(chosen)
    # Any inherited support requires the current primary page's certificate too.
    inherited = any((row["source_path"], row["page"]) not in allowed_sources for row in supports)
    if inherited and not _in_scope(primary, source[1]):
        return None
    ref = {**candidate, "source_path": source[0], "page": source[1],
           "method": "visual_agent_local_evidence", "candidate_origin": "local_cached_candidate",
           "supporting_sources": supports}
    if inherited:
        ref.update(file_id=primary["file_id"], source_sha256=primary["sha256"])
    return ref if current_client_party_support(ref, fields) is not None else None
