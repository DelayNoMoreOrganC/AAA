"""Missing contacts linked to a server-validated parent, without old-page reads.

This is a reviewable full-name/source association, not statutory identity
verification. A stored quote is never used as a reconstructed full page.
"""
from copy import deepcopy
import os
import re

from linked_fact_evidence import (contact_page_candidates, contact_page_has_identifiers,
                                 contact_identifier_review_fields, current_contact_support)

CONTACT_FIELDS = frozenset(("地址", "委托人电话"))


def _path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ""


def parent_contact_candidates(text, source, context, supplied, eligible):
    """Return (field, ref) pairs plus fixed, source-only review entries."""
    if not isinstance(supplied, dict) or not isinstance(context, dict):
        return [], []
    supports = supplied.get("contact_provenance")
    scope = supplied.get("contact_source_scope")
    client = context.get("委托人")
    if (not isinstance(supports, list) or not 1 <= len(supports) <= 4
            or any(not isinstance(item, dict) for item in supports)
            or not isinstance(scope, list) or not isinstance(client, str) or not client.strip()):
        return [], []
    by_path = {_path(row.get("path")): row for row in scope if isinstance(row, dict)}
    row = by_path.get(_path(source[0]))
    if (not row or type(source[1]) is not int or not 1 <= source[1] <= row.get("pages", 0)
            or not re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", ""))):
        return [], []
    # No parent full-page identifier certificate exists in this release. Do not
    # silently weaken the original full-batch comparison or infer it from quotes.
    if contact_page_has_identifiers(text):
        return [], [{"field": field, "source_path": source[0], "page": source[1],
                     "reason_code": "local_evidence_rejected",
                     "verification_code": "contact_identifier_unverified",
                     "reason": "新增联系页包含身份号码，尚无可比对的已核验身份号码依据，请核对两处原页"}
                    for field in sorted(contact_identifier_review_fields(text, client) & set(eligible))]
    candidates = [fact for fact in contact_page_candidates(text, client) if fact["field"] in eligible]
    if not candidates:
        return [], []
    validation = deepcopy(context)
    provenance = validation.setdefault("_provenance", {})
    refs = provenance.get("委托人") or []
    refs = [refs] if isinstance(refs, dict) else refs
    if not isinstance(refs, list):
        return [], []
    provenance["委托人"] = refs + deepcopy(supports)
    for support in supports:
        original = by_path.get(_path(support.get("source_path")))
        if (not original or support.get("file_id") != original.get("file_id")
                or support.get("source_sha256") != original.get("sha256")
                or not re.fullmatch(r"[0-9a-f]{64}", support.get("source_sha256", ""))
                or type(support.get("page")) is not int
                or not 1 <= support["page"] <= original.get("pages", 0)):
            return [], []
    results = []
    for fact in candidates:
        ref = {"source_path": source[0], "page": source[1], "value": fact["value"],
               "quote": fact["quote"], "method": "visual_agent_local_evidence",
               "binding": "client_contact", "candidate_origin": "local_cached_candidate",
               "file_id": row["file_id"], "source_sha256": row["sha256"],
               "supporting_sources": [{**deepcopy(item), "field": "委托人"} for item in supports]}
        if current_contact_support(ref, validation) is not None:
            results.append((fact["field"], ref))
    return results, []
