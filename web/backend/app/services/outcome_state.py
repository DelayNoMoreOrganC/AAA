"""Reconcile one machine missing-result state; never infer or edit a result."""
from __future__ import annotations

import os

MISSING_OUTCOME_WARNING = "尚无已采纳的审办结果或结案小结；未从文书类别、诉请或执行申请推断处理结果，请核对后补充"
_FIELDS = ("结案小结", "审（办）结果", "审办结果")
_METHODS = frozenset(("visual_agent_local_evidence", "local_agent"))


def _refs(fields, field):
    refs = (fields.get("_provenance") or {}).get(field) or []
    return refs if isinstance(refs, list) else [refs]


def _human(fields, field, manual):
    value = fields.get(field)
    return ((field in manual and manual[field] == value) or any(
        isinstance(ref, dict) and ref.get("method") == "human" and ref.get("value") == value
        for ref in _refs(fields, field)))


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ""


def _has_current_result(fields, manual, manifest, issues, case_type=None, resolved_conflicts=()):
    # Explicitly clearing the canonical form must not resurrect an old alias.
    if _human(fields, "结案小结", manual) and not _text(fields.get("结案小结")):
        return False
    if any(_text(fields.get(key)) and _human(fields, key, manual) for key in _FIELDS):
        return True
    if any(isinstance(row, dict) and row.get("field") in _FIELDS and row.get("resolved") is not True
           for row in fields.get("_field_conflicts") or []):
        return False
    # An acknowledgement records review, not an automatic factual resolution.
    if any(isinstance(row, dict) and row.get("kind") == "field_conflict"
           and isinstance(row.get("detail"), dict) and row["detail"].get("field") in _FIELDS
           for row in issues or []):
        return False
    scope = {_path(row.get("path")): row["pages"] for row in manifest or []
             if isinstance(row, dict) and _path(row.get("path"))
             and type(row.get("pages")) is int and row["pages"] > 0}
    for key in _FIELDS:
        value = fields.get(key)
        if not _text(value):
            continue
        for ref in _refs(fields, key):
            if not isinstance(ref, dict):
                continue
            if ref.get('method') == 'model_form_synthesis':
                from .evidence_links import supporting_refs
                if supporting_refs(ref, fields, manifest) is not None:
                    return True
                continue
            count = scope.get(_path(ref.get("source_path")))
            if (ref.get("method") in _METHODS and ref.get("value") == value and _text(ref.get("quote"))
                    and count is not None and type(ref.get("page")) is int and 1 <= ref["page"] <= count):
                if ref.get('binding') in ('court_report_summary','case_timeline_summary'):
                    from .evidence_links import supporting_refs
                    if supporting_refs(ref, fields, manifest) is None:
                        continue
                return True
    from form_drafts import current_stage_summary_supported
    blocked = {(row.get("detail") or {}).get("field") for row in issues or []
               if isinstance(row, dict) and row.get("kind") == "field_conflict"
               and isinstance(row.get("detail"), dict) and row["detail"] not in resolved_conflicts}
    return current_stage_summary_supported(fields, manual, manifest, blocked, case_type=case_type,
                                           resolved_conflicts=resolved_conflicts)


def refresh_missing_outcome(analysis, manual_fields=None, source_manifest=None, issues=None, *, resolved_conflicts=()):
    """Keep unrelated warnings and source/history untouched; sync both stores.

    Machine refs here are already validated extraction evidence, not new input
    from a model. Scope/value checks prevent obsolete or unrelated refs from
    clearing this state. This does not certify legal correctness or closure.
    """
    fields = analysis.fields or {}
    manual = manual_fields or {}
    warnings = []
    for entry in list(getattr(analysis, "outcome_warnings", None) or []) + list(fields.get("_outcome_warnings") or []):
        if entry not in warnings:
            warnings.append(entry)
    managed = (MISSING_OUTCOME_WARNING in warnings or bool(fields.get("_field_normalization_version"))
               or any(key in manual or _human(fields, key, {}) for key in _FIELDS)
               or any(isinstance(row, dict) and row.get("kind") == "outcome"
                      and row.get("message") == MISSING_OUTCOME_WARNING for row in issues or []))
    if not managed:
        return
    warnings = [entry for entry in warnings if entry != MISSING_OUTCOME_WARNING]
    if not _has_current_result(fields, manual, source_manifest, issues, getattr(analysis, "case_type", None), resolved_conflicts):
        warnings.append(MISSING_OUTCOME_WARNING)
    analysis.outcome_warnings = warnings
    analysis.fields = dict(fields, _outcome_warnings=list(warnings))


def sync_missing_outcome_issue(issues, analysis):
    """Sync the machine state and existing form summary; keep conflict history."""
    from .task_workflow import issue
    result = [row for row in issues or [] if not (row.get("kind") == "outcome"
              and row.get("message") == MISSING_OUTCOME_WARNING)]
    if MISSING_OUTCOME_WARNING in (getattr(analysis, "outcome_warnings", None) or []):
        result.append(issue("outcome", MISSING_OUTCOME_WARNING))
    if (analysis.fields or {}).get("_form_drafts"):
        from form_drafts import draft_review_message
        message, summary = draft_review_message(analysis.fields)
        result = [row for row in result if row.get("kind") != "form_draft"]
        if message:
            result.append(issue("form_draft", message, detail=summary, blocking=False))
    return result
