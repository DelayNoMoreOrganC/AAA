"""Use checked image-field quotes without promoting whole VLM transcripts.

Known text-disagreement pages are excluded from automatic narrative input, not
deleted from the case/cache. Only current scoped field quotes may replace them.
"""
from copy import deepcopy
import math
import os

from fact_evidence import normalized_source_text as compact
from visual_fact_readback import has_readback, reference_supported

VERSION = 'visual-field-synthesis-v1'
NARRATIVE_FIELDS = ('案情简介', '案件或项目名称', '审（办）结果', '结案小结')
RESULT_FIELDS = ('审（办）结果', '结案小结')
TARGETS = {
    **{name: NARRATIVE_FIELDS for name in ('委托人', '当事人', '对方当事人', '案由', '案号', '审理法院')},
    **{name: RESULT_FIELDS for name in ('执行案号', '审级', '结案日期', '结案小结', '阶段工作情况', '顾问协议状态')},
    '案件或项目名称': ('案件或项目名称', '结案小结'),
    **{name: ('结案小结',) for name in ('承办律师', '律师事务所', '收费标准', '收案日期')},
}


def _path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ''


def _receipt_source(ref, manifest):
    if not isinstance(ref, dict):
        return None
    source = manifest.get(_path(ref.get('source_path')))
    page = ref.get('page')
    if (not source or type(page) is not int or not 1 <= page <= source['pages']
            or ref.get('source_sha256') != source.get('sha256')):
        return None
    return (_path(ref['source_path']), page)


def apply(sources, coverage, units, fields, provenance, conflicts, manifest, *, max_chars):
    """Return an independent prompt pool; never rewrite OCR or caller facts."""
    current = {_path(row.get('path')): row for row in manifest or []
               if isinstance(row, dict) and type(row.get('pages')) is int and row['pages'] > 0
               and isinstance(row.get('sha256'), str) and len(row['sha256']) == 64}
    blocked = {r.get('field') for r in conflicts if isinstance(r, dict) and not r.get('resolved')}
    quarantined, visual, seen, omitted = set(), [], set(), 0
    for field, refs in provenance.items():
        refs = [refs] if isinstance(refs, dict) else refs if isinstance(refs, list) else []
        for ref in refs:
            if not has_readback(ref):
                continue
            location = _receipt_source(ref, current)
            if location is None:
                continue  # An old hash cannot quarantine a different new file.
            quarantined.add(location)
            candidates = [u for u in units if _path(u.source_path) == location[0]
                          and u.start_page + 1 <= location[1] <= u.end_page + 1]
            if (field not in TARGETS or field in blocked or len(candidates) != 1
                    or not reference_supported(ref, field, fields.get(field), manifest)):
                omitted += 1
                continue
            unit = candidates[0]
            if (type(unit.confidence) not in (int, float) or not math.isfinite(unit.confidence)
                    or unit.confidence < .85):
                omitted += 1
                continue
            identity = ref['visual_readback']['sha256']
            if identity in seen:
                continue
            seen.add(identity)
            visual.append({'source_path': ref['source_path'], 'page': ref['page'],
                'kind': unit.doc_type, 'doc_id': str(unit.doc_id), 'text': ref['quote'],
                'evidence_kind': VERSION, 'source_field': field, 'verified_value': ref['value'],
                'allowed_fields': list(TARGETS[field]), 'scope': 'checked_field_quote_not_full_page',
                'visual_reference': deepcopy(ref)})
    # Quarantine before budgeting, including doubtful/stale field values from
    # the same current page; do not revive their original mismatched OCR text.
    retained = [deepcopy(s) for s in sources if (_path(s['source_path']), s['page']) not in quarantined]
    selected, size = [], 0
    for source in [*visual, *retained]:
        if size + len(source['text']) > max_chars:
            omitted += 1
            continue
        size += len(source['text'])
        selected.append({**source, 'id': f'S{len(selected)+1}'})
    result = deepcopy(coverage)
    for document in result.get('documents', []):
        matching = [u for u in units if str(u.doc_id) == document['doc_id']]
        if len(matching) != 1:
            continue
        unit = matching[0]
        expected = set(range(unit.start_page + 1, unit.end_page + 2))
        old_partial = set(document['missing_or_partial_pages'])
        still_selected = {s['page'] for s in selected if s.get('evidence_kind') != VERSION
                          and _path(s['source_path']) == _path(unit.source_path) and s['doc_id'] == document['doc_id']}
        partial = old_partial | (expected - still_selected)
        document.update(complete_pages=len(expected - partial), missing_or_partial_pages=sorted(partial))
    result.update(selected_excerpts=len(selected), characters=size,
        excluded_or_partial=result.get('excluded_or_partial', 0) + len(quarantined) + omitted,
        visual_fields={'version': VERSION, 'selected_quotes': sum(s.get('evidence_kind') == VERSION for s in selected),
                       'quarantined_text_pages': len(quarantined), 'omitted_quotes_or_excerpts': omitted,
                       'scope': 'field_quotes_only_other_page_content_requires_review'})
    return selected, result


def public_source(source):
    return {k: deepcopy(v) for k, v in source.items() if k not in ('source_path', 'visual_reference')}


def citation_allowed(field, source, quote, claim):
    if source.get('evidence_kind') != VERSION:
        return True
    if field not in source.get('allowed_fields', []) or compact(quote) != compact(source['text']):
        return False  # No shortened quote dropping the field's subject/conditions.
    if source.get('source_field') not in ('结案小结', '阶段工作情况', '顾问协议状态'):
        return compact(source.get('verified_value', '')) in compact(claim)
    return True  # Narrative paraphrases still need the existing semantic reviewer.


def current_sources(sources, fields, provenance, manifest=None, *, generated=None):
    """Bind narrative use to the exact accepted input, including after editing."""
    generated = generated or {}
    for source in sources:
        if source.get('evidence_kind') != VERSION:
            continue
        field, value = source.get('source_field'), source.get('verified_value')
        ref = source.get('visual_reference')
        if (not reference_supported(ref, field, value, manifest)
                or source.get('allowed_fields') != list(TARGETS.get(field, ()))
                or source.get('text') != ref['quote'] or source.get('page') != ref['page']
                or _path(source.get('source_path')) != _path(ref['source_path'])):
            return False
        refs = provenance.get(field, [])
        refs = [refs] if isinstance(refs, dict) else refs if isinstance(refs, list) else []
        if not any(row == ref for row in refs):
            return False
        if fields.get(field) != value:
            # A literal conclusion can be an input to its own rewritten cell.
            # Only this bundle's exact generated output permits that transition.
            row = generated.get(field)
            if not isinstance(row, dict) or fields.get(field) != row.get('value'):
                return False
        if any(isinstance(r, dict) and r.get('field') == field and not r.get('resolved')
               for r in fields.get('_field_conflicts', [])):
            return False
    return True
