"""Recheck provisional opponent links against the final represented client."""
from __future__ import annotations

import re

from linked_party_evidence import current_party_binding_supported


def reconcile_party_bindings(fields, provenance, conflicts):
    """Mutate this extraction's accepted facts; return source-only review items.

    This runs after all documents, so a later client correction or conflict has
    the same effect as an earlier one. Ordinary explicit opponent facts retain
    their previous behavior. No material is read and no model is called.
    """
    key = "对方当事人"
    refs = provenance.get(key, [])
    context = {**fields, "_provenance": provenance, "_field_conflicts": conflicts}
    rejected = [ref for ref in refs if not current_party_binding_supported(ref, context)]
    if not rejected:
        return []
    kept = [ref for ref in refs if ref not in rejected]
    provenance[key] = kept
    conflicts[:] = [item for item in conflicts if item.get("field") != key]
    fields.pop(key, None)
    seen = set()
    for ref in kept:
        value = ref["value"]
        identity = re.sub(r"\s+", "", value)
        if identity in seen:
            continue
        seen.add(identity)
        if key not in fields:
            fields[key] = value
        else:
            conflicts.append({"field": key, "values": [fields[key], value], "source": ref})
    return [{"field": key, "reason_code": "local_evidence_rejected",
             "verification_code": "represented_client_mismatch",
             "reason": "本页代理身份与全案委托人未能一致核实，请核对原页。",
             "source_path": ref["source_path"], "page": ref["page"]}
            for ref in rejected]
