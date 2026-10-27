"""Build a bounded, memory-only identity view for compatible additions.

The caller has already checked the current source bytes and loaded the parent
snapshot inside the authorized organisation. This module performs no I/O and
does not turn parent fields into new extracted facts or model instructions.
"""
from __future__ import annotations

import copy
import hashlib
import os
import re

from .task_sources import source_version

IDENTITIES = ("委托人", "委托人名称", "委托方", "案号", "法院收案号", "合同号")
TARGETS = ("对方当事人", "审理法院", "地址", "委托人电话", "当事人")
FEE_FIELDS = ("应收业务费", "已收业务费", "尚欠业务费", "应退业务费")
RELEVANT = (*IDENTITIES, *TARGETS, *FEE_FIELDS, '案由', '立案审批日期', '收案日期', '_intake_contract_date_source')
MACHINE_METHODS = {"local_agent", "visual_agent_local_evidence"}
MAX_VALUE = 500
MAX_QUOTE = 2000
MAX_REFS = 4


def _path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ""


def _manifest(rows):
    if not isinstance(rows, list) or not rows:
        return None
    result, paths = {}, set()
    for row in rows:
        if not isinstance(row, dict):
            return None
        identity, path = row.get("file_id"), _path(row.get("path"))
        if (not isinstance(identity, str) or not identity or identity in result
                or not path or path in paths or not os.path.isabs(row["path"])
                or not isinstance(row.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
                or type(row.get("pages")) is not int or row["pages"] < 1
                or not isinstance(row.get("doc_type"), str) or not row["doc_type"]):
            return None
        result[identity] = row
        paths.add(path)
    return result


def _refs(fields, field):
    provenance = fields.get("_provenance") or {}
    if not isinstance(provenance, dict):
        return None
    refs = provenance.get(field) or []
    return [refs] if isinstance(refs, dict) else refs if isinstance(refs, list) else None


def _trusted_refs(value, refs, old_by_path, *, field=None):
    def literal(text):
        compact = re.sub(r"\s+", "", text)
        # Court numbers normalize bracket width during acceptance; that does
        # not authorize normalization of a person's or company's identity.
        return compact.replace("（", "(").replace("）", ")") if field in ("案号", "法院收案号") else compact

    trusted = []
    for ref in refs or []:
        if not isinstance(ref, dict) or ref.get("value") != value:
            continue
        method = ref.get("method")
        if method == "human":
            trusted.append({"method": "human", "value": value})
        elif method in MACHINE_METHODS:
            row, page = old_by_path.get(_path(ref.get("source_path"))), ref.get("page")
            quote = ref.get("quote")
            if (not row or type(page) is not int or not 1 <= page <= row["pages"]
                    or ref.get("file_id") not in (None, "", row["file_id"])
                    or "source_sha256" in ref and ref["source_sha256"] != row["sha256"]
                    or not isinstance(quote, str) or not 0 < len(quote) <= MAX_QUOTE
                    or not value.strip()
                    or literal(value) not in literal(quote)
                    # Identity refs must be original accepted evidence, not a
                    # recursively linked/derived fact needing an old full page.
                    or ref.get("binding") or ref.get("supporting_sources")):
                continue
            trusted.append({"method": method, "value": value, "quote": quote,
                            "source_path": row["path"], "page": page, "file_id": row["file_id"]})
        if len(trusted) >= MAX_REFS:
            break
    return trusted


def _human_resolved(conflict, fields, manual, parent, old_rows, case_type, stage):
    """Only a recorded explicit field save resolves a conflict for recall.

    A UI acknowledgement, old resolved flag, different field or later source
    generation does not certify the identity. An earlier explicit resolution
    can survive pure additions only through its unchanged source-scope digest.
    Raw audit history stays intact.
    """
    field, resolution = conflict.get("field"), conflict.get("resolution")
    value = fields.get(field)
    if not (conflict.get("resolved") is True and field in manual
            and isinstance(value, str) and manual[field] == value
            and isinstance(resolution, dict) and resolution.get("method") == "human_field_edit"
            and type(resolution.get("revision")) is int and resolution["revision"] > 0
            and type(resolution.get("task_id")) is int and 0 < resolution["task_id"] <= parent.id
            and (resolution["task_id"] < parent.id or resolution["revision"] <= parent.revision)
            and resolution.get("case_id") == parent.case_id
            and resolution.get("case_type") == case_type and resolution.get("case_stage") == stage
            and resolution.get("value_digest") == hashlib.sha256(value.encode("utf-8")).hexdigest()):
        return False
    scope = resolution.get("source_scope")
    if not isinstance(scope, list) or not scope:
        return False
    seen = set()
    for row in scope:
        if not isinstance(row, dict) or not isinstance(row.get("file_id"), str) or row["file_id"] in seen:
            return False
        current = old_rows.get(row["file_id"])
        if (not current or type(row.get("pages")) is not int
                or any(row.get(key) != current[key] for key in ("sha256", "pages", "doc_type"))):
            return False
        seen.add(row["file_id"])
    return resolution.get("source_version") == source_version(scope, case_type, stage)


def build_supplement_identity_context(task, parent, previous, snapshot, *, org_id, case_type, stage=""):
    """Return a trusted narrow context, or None without affecting analysis.

    No compatibility exception is granted to old snapshots/test doubles. The
    parent task, its snapshot revision and both frozen manifests must agree.
    Human blanks and unresolved conflict *facts* survive UI acknowledgements.
    """
    if not parent or not isinstance(snapshot, dict) or not isinstance(org_id, str) or not org_id:
        return None
    task_id, parent_id = getattr(task, "id", None), getattr(parent, "id", None)
    revision = getattr(parent, "revision", None)
    case_id = getattr(parent, "case_id", None)
    if (type(task_id) is not int or type(parent_id) is not int or not 0 < parent_id < task_id
            or type(revision) is not int or revision < 1 or not isinstance(case_id, str) or not case_id
            or getattr(task, "case_id", None) != case_id
            or getattr(task, "parent_task_id", None) != parent_id):
        return None
    old, current = getattr(parent, "source_manifest", None), getattr(task, "source_manifest", None)
    old_rows, current_rows = _manifest(old), _manifest(current)
    if not old_rows or not current_rows or not old_rows.keys() < current_rows.keys():
        return None
    for identity, row in old_rows.items():
        now = current_rows[identity]
        if (_path(row["path"]) != _path(now["path"])
                or any(row[key] != now[key] for key in ("sha256", "pages", "doc_type"))):
            return None
    parent_version, current_version = source_version(old, case_type, stage), source_version(current, case_type, stage)
    meta = snapshot.get("workflow")
    manual = getattr(parent, "manual_fields", None) or {}
    if (not isinstance(meta, dict) or not isinstance(manual, dict)
            or getattr(parent, "source_version", None) != parent_version
            or getattr(task, "source_version", None) != current_version
            or meta.get("revision") != revision or type(meta.get("revision")) is not int
            or meta.get("source_version") != parent_version or meta.get("source_manifest") != old
            or meta.get("manual_fields", {}) != manual
            or snapshot.get("case_type") != case_type or previous.case_type != case_type):
        return None
    fields = getattr(previous, "fields", None)
    recorded = getattr(parent, "fields", None)
    if not isinstance(fields, dict) or not isinstance(recorded, dict):
        return None
    for field in RELEVANT:
        if (fields.get(field) != recorded.get(field) or _refs(fields, field) is None
                or _refs(fields, field) != _refs(recorded, field)
                or field in manual and fields.get(field) != manual[field]):
            return None
    if fields.get("_field_conflicts", []) != recorded.get("_field_conflicts", []):
        return None
    conflicts = fields.get("_field_conflicts") or []
    parent_issues = getattr(parent, "issues", None) or []
    if not isinstance(conflicts, list) or not isinstance(parent_issues, list):
        return None
    conflict_fields = set()
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            return None
        if conflict.get("field") in RELEVANT and not _human_resolved(conflict, fields, manual, parent, old_rows, case_type, stage):
            conflict_fields.add(conflict["field"])
    for entry in parent_issues:
        if not isinstance(entry, dict):
            return None
        if entry.get("kind") == "field_conflict":
            detail = entry.get("detail")
            if not isinstance(detail, dict):
                return None
            if detail.get("field") in RELEVANT and not _human_resolved(detail, fields, manual, parent, old_rows, case_type, stage):
                conflict_fields.add(detail["field"])
    identity_fields, provenance = {}, {}
    old_by_path = {_path(row["path"]): row for row in old_rows.values()}
    for field in IDENTITIES:
        value = fields.get(field)
        if not isinstance(value, str) or len(value) > MAX_VALUE:
            continue
        refs = [{"method": "human", "value": value}] if field in manual else _trusted_refs(value, _refs(fields, field), old_by_path, field=field)
        if refs:
            identity_fields[field] = value
            provenance[field] = refs
    manual_fields = {field for field in RELEVANT if field in manual or any(
        isinstance(ref, dict) and ref.get("method") == "human" for ref in _refs(fields, field))}
    blocked = {field for field in TARGETS if field in manual_fields or fields.get(field) not in (None, "")}
    context = {
        "version": 1,
        "binding": {"org_id": org_id, "case_id": case_id, "task_id": task_id,
                    "parent_task_id": parent_id, "parent_revision": revision,
                    "parent_source_version": parent_version, "source_version": current_version},
        "fields": identity_fields, "provenance": provenance,
        "conflicts": [{"field": field, "resolved": False} for field in sorted(conflict_fields)],
        "manual_fields": sorted(manual_fields), "blocked_fields": sorted(blocked),
    }
    # Only existing, current-value original evidence can support a contact link.
    # A human identity without matching original evidence remains human-only;
    # no old quote is promoted to full-page text or an identifier certificate.
    client = fields.get("委托人")
    if isinstance(client, str) and client.strip():
        contact_refs = [ref for ref in _trusted_refs(client, _refs(fields, "委托人"), old_by_path)
                        if ref["method"] in MACHINE_METHODS]
        context["contact_provenance"] = [
            {**ref, "source_sha256": old_by_path[_path(ref["source_path"])]["sha256"]}
            for ref in contact_refs]
        context["contact_source_scope"] = [
            {key: row[key] for key in ("file_id", "path", "sha256", "pages")}
            for row in current]
    # A court-party link needs *both* original identity facts. Keep their small
    # accepted excerpts bound to unchanged source hashes; never substitute a
    # manual-only value or a previous derived summary for original evidence.
    party_provenance = {}
    for field in ("委托人", "案号"):
        value = fields.get(field)
        if not isinstance(value, str) or not value.strip():
            break
        refs = [ref for ref in _trusted_refs(value, _refs(fields, field), old_by_path, field=field)
                if ref["method"] in MACHINE_METHODS]
        if not refs:
            break
        party_provenance[field] = [
            {**ref, "field": field, "source_sha256": old_by_path[_path(ref["source_path"])]["sha256"]}
            for ref in refs]
    if set(party_provenance) == {"委托人", "案号"}:
        context["party_provenance"] = party_provenance
        context["party_source_scope"] = [
            {key: row[key] for key in ("file_id", "path", "sha256", "pages")}
            for row in current]
    fee_provenance = {}
    for field in ('委托人', '案号', '合同号'):
        value = fields.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        refs = [ref for ref in _trusted_refs(value, _refs(fields, field), old_by_path, field=field)
                if ref['method'] in MACHINE_METHODS]
        if refs:
            fee_provenance[field] = [
                {**ref, 'field': field, 'source_sha256': old_by_path[_path(ref['source_path'])]['sha256']}
                for ref in refs]
    if '委托人' in fee_provenance and {'案号', '合同号'}.intersection(fee_provenance):
        context['fee_provenance'] = fee_provenance
        context['fee_source_scope'] = [
            {key: row[key] for key in ('file_id', 'path', 'sha256', 'pages')} for row in current]
    context['date_previous_scope'] = [{key: row[key] for key in ('file_id', 'path', 'sha256', 'pages')} for row in old]
    context['date_current_scope'] = [{key: row[key] for key in ('file_id', 'path', 'sha256', 'pages')} for row in current]
    context['date_added_scope'] = [row for row in context['date_current_scope'] if row['file_id'] not in old_rows]
    return copy.deepcopy(context)
