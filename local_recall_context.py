"""Restricted parent identities for local cached-page recall, never model input.

The backend owns case authorization, snapshot/source hashes and page scope.
This module performs no I/O and never promotes inherited identities into this
extraction's fields or provenance. Its validation view is disposable.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re
import unicodedata

from linked_party_evidence import current_party_binding_supported
from source_court_evidence import current_court_binding_supported

CLIENT_KEYS = ("委托人", "委托人名称", "委托方")
NUMBER_KEYS = ("案号", "法院收案号")
CONTACT_TARGETS = frozenset(("地址", "委托人电话"))
TARGETS = frozenset(("对方当事人", "审理法院", "当事人", *CONTACT_TARGETS))


def _compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


def _refs(provenance, key):
    rows = provenance.get(key, [])
    return [rows] if isinstance(rows, dict) else rows


def local_recall_validation_context(fields, provenance, conflicts, supplied):
    """Return an isolated validation view and locally blocked recall targets.

    ``supplied`` is the internal v1 mapping produced by the supplement builder.
    Parent and delta disagreements block this dependency even if either side
    would pass in isolation. Acknowledgement is not conflict resolution.
    Invalid context fails closed for local recall; ordinary extraction is not
    changed. No returned parent identity is to be persisted as a delta fact.
    """
    view = {**fields, "_provenance": provenance, "_field_conflicts": conflicts}
    if supplied is None:
        return view, frozenset()
    if (not isinstance(supplied, Mapping) or type(supplied.get("version")) is not int
            or supplied["version"] != 1 or not isinstance(supplied.get("binding"), Mapping)
            or not supplied["binding"] or not isinstance(supplied.get("fields"), Mapping)
            or not isinstance(supplied.get("provenance"), Mapping)
            or not isinstance(supplied.get("conflicts"), list)
            or not isinstance(supplied.get("manual_fields"), (list, tuple, set, frozenset))
            or not isinstance(supplied.get("blocked_fields"), (list, tuple, set, frozenset))):
        return view, TARGETS
    parent_fields = supplied["fields"]
    parent_refs = supplied["provenance"]
    parent_conflicts = supplied["conflicts"]
    manual = supplied["manual_fields"]
    blocked = supplied["blocked_fields"]
    if (any(not isinstance(key, str) for key in (*manual, *blocked))
            or any(not isinstance(row, dict) for row in parent_conflicts)):
        return view, TARGETS
    blocked = set(TARGETS.intersection((*manual, *blocked)))
    blocked.update(row["field"] for row in parent_conflicts
                   if row.get("field") in TARGETS and row.get("resolved") is not True)
    # Deep-copy only the local validation view; never change caller-owned refs.
    view = deepcopy(view)
    for keys, target in ((CLIENT_KEYS, "对方当事人"), (NUMBER_KEYS, "审理法院"),
                         (CLIENT_KEYS, "当事人"), (NUMBER_KEYS, "当事人"),
                         (CLIENT_KEYS, "地址"), (CLIENT_KEYS, "委托人电话")):
        if any(row.get("field") in keys and row.get("resolved") is not True
               for row in parent_conflicts + list(conflicts)):
            blocked.add(target)
            continue
        if any(key in manual and not _compact(parent_fields.get(key)) for key in keys):
            blocked.add(target)
            continue
        if any(key in parent_fields and not isinstance(parent_fields[key], str) for key in keys):
            blocked.add(target)
            continue
        present = {key: parent_fields[key] for key in keys if key in parent_fields}
        if not any(_compact(value) for value in present.values()):
            # No inherited dependency: retain the existing self-contained path.
            continue
        parent = {**present, "_provenance": {key: deepcopy(parent_refs.get(key, [])) for key in keys},
                  "_field_conflicts": deepcopy(parent_conflicts)}
        if keys == CLIENT_KEYS:
            identity = next((_compact(present[key]) for key in keys if _compact(present.get(key))), "")
            probe = {"binding": "same_page_opponent", "subject": identity}
            guard = current_party_binding_supported
        else:
            identity = _compact(present.get("案号"))
            probe = {"binding": "court_case_number", "case_number": identity}
            guard = current_court_binding_supported
        if not guard(probe, parent):
            blocked.add(target)
            continue
        inconsistent = False
        for key in keys:
            current = fields.get(key)
            refs = _refs(provenance, key)
            if ((current is not None and not isinstance(current, str))
                    or not isinstance(refs, list)
                    or (_compact(current) and _compact(current) != identity)
                    or (key in fields and not _compact(current) and any(
                        isinstance(row, dict) and row.get("method") == "human" for row in refs))):
                inconsistent = True
                break
        if inconsistent:
            blocked.add(target)
            continue
        for key in keys:
            if key in present and not _compact(view.get(key)):
                view[key] = present[key]
            inherited = _refs(parent["_provenance"], key)
            existing = _refs(view["_provenance"], key)
            view["_provenance"][key] = deepcopy(inherited + existing)
        if not guard(probe, view):
            blocked.add(target)
    return view, frozenset(blocked)
