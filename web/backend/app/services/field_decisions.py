"""Source-bound human fact decisions; no I/O, model, or database writes.

The route owns authorization/current-source checks and the single-worker case
lock. A receipt is saved with the task fields and the field-save snapshot marker.
"""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import os

from .task_sources import source_version
from .supplement_identity_context import _human_resolved

RECEIPT = "_field_decision_receipt"


class FieldDecisionError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def conflict_digest(detail):
    return digest({key: value for key, value in detail.items()
                   if key not in ("resolved", "resolution", "fact_resolved")})


def validate_decision_snapshot(task, snapshot):
    meta = snapshot.get("workflow") or {}
    if (meta.get("source_version") != task.source_version or meta.get("source_manifest") != task.source_manifest
            or meta.get("revision") != task.revision
            or source_version(task.source_manifest, snapshot.get("case_type"), meta.get("case_stage", "")) != task.source_version):
        raise FieldDecisionError("当前快照缺少可验证的修订或材料身份，请先恢复分析后再核对")


def fact_conflict_resolved(task, detail, *, fields=None, manual=None, revision=None):
    if task is None or not isinstance(detail, dict):
        return False
    resolution = detail.get("resolution")
    if not isinstance(resolution, dict):
        return False
    fields = (getattr(task, "fields", None) or {}) if fields is None else fields
    manual = (getattr(task, "manual_fields", None) or {}) if manual is None else manual
    manifest = getattr(task, "source_manifest", None)
    kind, stage = resolution.get("case_type"), resolution.get("case_stage")
    if (not isinstance(manifest, list) or not manifest or not isinstance(kind, str)
            or not isinstance(stage, str) or any(not isinstance(row, dict) for row in manifest)
            or source_version(manifest, kind, stage) != getattr(task, "source_version", None)):
        return False
    if "conflict_digest" in resolution and resolution["conflict_digest"] != conflict_digest(detail):
        return False
    # Existing source-bound human edits predate this field-specific audit hash.
    # New decisions must always carry it; never trust a bare resolved flag.
    if resolution.get("operation") in ("accept_current", "accept_candidate") and "conflict_digest" not in resolution:
        return False
    rows = {row.get("file_id"): row for row in manifest}
    context = SimpleNamespace(id=getattr(task, "id", None), case_id=getattr(task, "case_id", None),
        revision=revision if revision is not None else getattr(task, "revision", None))
    if type(context.id) is not int or type(context.revision) is not int:
        return False
    try:
        return _human_resolved(detail, fields, manual, context, rows, kind, stage)
    except (KeyError, TypeError, ValueError):
        return False


def project_issues(task, issues=None):
    projected = deepcopy((getattr(task, "issues", None) or []) if issues is None else issues)
    for row in projected:
        if row.get("kind") == "field_conflict" and isinstance(row.get("detail"), dict):
            row["detail"]["fact_resolved"] = fact_conflict_resolved(task, row["detail"])
    return projected


def _audit_entries(fields):
    provenance = fields.get("_provenance") or {}
    if isinstance(provenance, dict):
        for refs in provenance.values():
            for ref in refs if isinstance(refs, list) else [refs]:
                if isinstance(ref, dict):
                    yield ref
    for row in fields.get("_field_conflicts") or []:
        if isinstance(row, dict) and isinstance(row.get("resolution"), dict):
            yield row["resolution"]


def field_candidates(task, field):
    """Human choices with in-case page anchors, never automatic fact acceptance."""
    def path(value):
        return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ''
    manifest = [r for r in (task.source_manifest or []) if isinstance(r, dict)]
    by_path = {path(r.get('path')): r for r in manifest if path(r.get('path'))}
    by_id = {r.get('file_id'): r for r in manifest if r.get('file_id')}
    details = [r for r in (task.fields or {}).get('_field_conflicts', []) if isinstance(r, dict)]
    details += [r.get('detail', {}) for r in task.issues or [] if r.get('kind') == 'field_conflict']
    choices = {}
    for detail in details:
        if detail.get('field') != field or fact_conflict_resolved(task, detail):
            continue
        values = detail.get('values')
        if not isinstance(values, list):
            values = [detail.get('saved'), detail.get('new')]
        for ref in detail.get('sources') or []:
            if not isinstance(ref, dict):
                continue
            value, page = ref.get('value'), ref.get('page')
            if (not isinstance(value, str) or not value.strip() or len(value) > 20000
                    or value not in values or not isinstance(ref.get('quote'), str) or not ref['quote'].strip()):
                continue
            source = by_id.get(ref.get('file_id')) or by_path.get(path(ref.get('source_path')))
            if (not source or (ref.get('file_id') and ref['file_id'] != source.get('file_id'))
                    or (ref.get('source_path') and path(ref['source_path']) != path(source.get('path')))
                    or type(page) is not int or type(source.get('pages')) is not int
                    or not 1 <= page <= source['pages']
                    or (ref.get('source_sha256') and ref['source_sha256'] != source.get('sha256'))):
                continue
            anchor = dict(file_id=source['file_id'], filename=source.get('filename', '来源材料'), page=page)
            item = choices.setdefault(value, dict(value=value, sources=[]))
            if anchor not in item['sources']:
                item['sources'].append(anchor)
    return list(choices.values()) if len(choices) <= 12 else []


def prepare_accept_current(task, body, *, actor_id, org_id):
    """Return (receipt, replay). Authorization/currentness precedes this call."""
    payload = body.model_dump() if hasattr(body, "model_dump") else dict(body)
    payload_digest = digest(dict(payload, actor_id=actor_id, org_id=org_id,
                                 case_id=task.case_id, task_id=task.id))
    fields = task.fields or {}
    operation = payload.get('action', 'accept_current')
    chosen = payload.get('selected_value') if operation == 'accept_candidate' else payload['current_value']
    recent = fields.get(RECEIPT)
    used = (isinstance(recent, dict) and recent.get("request_id") == payload["request_id"])
    used = used or any(row.get("request_id") == payload["request_id"] for row in _audit_entries(fields))
    if used:
        if (isinstance(recent, dict) and recent.get("request_id") == payload["request_id"]
                and recent.get("actor_id") == actor_id and recent.get("org_id") == org_id
                and recent.get("case_id") == task.case_id and recent.get("task_id") == task.id
                and recent.get("payload_digest") == payload_digest
                and recent.get("applied_revision") == task.revision
                and recent.get("source_version") == task.source_version == payload["source_version"]
                and fields.get(payload["field"]) == chosen):
            return recent, True
        raise FieldDecisionError("该请求已使用或内容已变化，请刷新后重新核对")
    field = payload["field"]
    if (field.startswith("_") or task.revision != payload["expected_revision"]
            or task.source_version != payload["source_version"]
            or fields.get(field) != payload["current_value"]):
        raise FieldDecisionError("字段、材料或修订已变化，请刷新后重新核对")
    rows = [(row.get("detail") or {}, row.get("id")) for row in task.issues or []
            if row.get("kind") == "field_conflict" and isinstance(row.get("detail"), dict)
            and row["detail"].get("field") == field]
    raw = [row for row in fields.get("_field_conflicts") or []
           if isinstance(row, dict) and row.get("field") == field]
    if not any(not fact_conflict_resolved(task, row) for row in raw + [row for row, _ in rows]):
        raise FieldDecisionError("当前字段没有尚待事实核对的冲突")
    selected = None
    if operation == 'accept_candidate':
        selected = next((r for r in field_candidates(task, field) if r['value'] == chosen), None)
        if selected is None:
            raise FieldDecisionError('候选内容或来源已变化，请刷新后重新核对')
    receipt = {"request_id": payload["request_id"], "payload_digest": payload_digest,
        "actor_id": actor_id, "org_id": org_id, "case_id": task.case_id, "task_id": task.id,
        "source_version": task.source_version, "base_revision": task.revision,
        "applied_revision": task.revision + 1, "operation": operation, "field": field,
        "conflicts": sorted(set(conflict_digest(row) for row in raw + [row for row, _ in rows])),
        "issue_ids": sorted(row_id for _, row_id in rows if isinstance(row_id, str))}
    if selected:
        receipt.update(selected_value=chosen, selected_sources=deepcopy(selected['sources']))
    return receipt, False
