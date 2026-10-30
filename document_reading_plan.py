"""Task-relative reading priorities. Retention, reading and fact acceptance differ."""
from __future__ import annotations
from form_cell_contracts import SOURCE_PRIORITY, LITERAL_SOURCES

PLAN_VERSION = 'reading-plan-v1'
CORE_TYPES = frozenset(('complaint','plea','appeal','indictment','agent_opinion',
    'judgment','ruling','mediation','preservation','execution','contract','legal_work','work_record',
    'meeting_record','court_record','agreement_status','client_talk'))
SUPPORT_TYPES = frozenset(('poa','agency_notice','invoice','fee_notice','fee_settlement',
    'client_intro','summons','acceptance_notice','court_notice','firm_letter','intake_approval','closure_report'))


def validated_relevance(raw):
    if not isinstance(raw, dict):
        raise ValueError('INVALID_FIELD_RELEVANCE')
    purpose = raw.get('purpose')
    fields = raw.get('fields')
    if (type(purpose) is not str or purpose not in ('core','supporting','retain_only','unknown')
            or not isinstance(fields,list) or len(fields)>40
            or any(type(f) is not str or f not in SOURCE_PRIORITY and f not in LITERAL_SOURCES for f in fields)
            or purpose=='retain_only' and fields):
        raise ValueError('INVALID_FIELD_RELEVANCE')
    return {'purpose':purpose,'fields':list(dict.fromkeys(fields))}


def plan_document(unit, document, rows_by_id, hints, *, fields=None, substantive_sources_present=False):
    """Planner may save extra extraction calls, never omit source pages.

    Only generic evidence unanimously screened as retain-only can defer deeper
    extraction. Missing/uncertain observations, source hints, field conflict or
    lack of substantive sources conservatively keep it in the reading queue.
    An impact declaration is a routing hint, not evidence for the target field.
    """
    fields = fields or {}
    keys = document['keys']
    rows = [rows_by_id[k] for k in keys]
    kind = unit.doc_type
    targets = [field for field, types in {**LITERAL_SOURCES, **SOURCE_PRIORITY}.items() if kind in types]
    impacts = list(dict.fromkeys(field for row in rows for field in row.get('field_relevance',{}).get('fields',[])))
    targets = list(dict.fromkeys(targets + impacts))
    reasons = []
    if kind in CORE_TYPES or any(r.get('field_relevance',{}).get('purpose')=='core' for r in rows):
        tier, reasons = 'core', ['substantive_document_for_case_or_service']
    elif kind in SUPPORT_TYPES or impacts or any(k in hints for k in keys):
        tier, reasons = 'supporting', ['specific_field_or_source_hint']
    else:
        tier, reasons = 'archive', ['preserve_original_and_screen_structure']
    unresolved = any(r.get('_boundary_unresolved') for r in rows)
    attention = []
    for row in rows:
        observation = row.get('observation') or {}
        reasons_for_page = []
        if observation.get('quality') in ('small_text','blurred','occluded'):
            reasons_for_page.append('legibility')
        if observation.get('writing') in ('handwritten','mixed'):
            reasons_for_page.append('handwriting')
        if observation.get('suggested_rotation') in (90,180,270):
            reasons_for_page.append('orientation')
        if reasons_for_page:
            attention.append({'page_id':row['page_id'], 'reasons':reasons_for_page,
                              'suggested_rotation':observation.get('suggested_rotation'),
                              'status':'visual_reinspection_requested_not_verified'})
    attention_ids = {item['page_id'] for item in attention}
    score = getattr(unit,'confidence',None)
    uncertain = kind=='unknown' or unresolved or bool(attention) or type(score) not in (int,float) or not 0.85<=score<=1
    conflicts = fields.get('_field_conflicts') or []
    if uncertain:
        tier = 'supporting' if tier=='archive' else tier
        reasons.append('unresolved_structure_or_legibility')
    if conflicts and kind=='evidence':
        tier = 'supporting'
        reasons.append('case_field_conflict_requires_support')
    explicitly_retain_only = bool(rows) and all(
        r.get('field_relevance',{}).get('purpose')=='retain_only'
        and r.get('observation',{}).get('quality')=='clear'
        and r.get('observation',{}).get('writing')=='printed'
        and type(r.get('observation',{}).get('suggested_rotation')) is int
        and r['observation']['suggested_rotation']==0 for r in rows)
    skip = (kind=='evidence' and explicitly_retain_only and not impacts
            and not any(k in hints for k in keys) and not uncertain and not conflicts
            and substantive_sources_present and bool(fields.get('_field_provenance')))
    selected = [] if skip else [k for k in keys if k in hints or k in attention_ids or k in (keys[0],keys[-1])
        or rows_by_id[k].get('field_relevance',{}).get('fields')]
    # Short key documents are read end-to-end; long ones retain explicit partial
    # coverage and can request relevant neighbors within existing tool budgets.
    if tier=='core' and len(keys)<=8:
        selected = list(keys)
    return {'version':PLAN_VERSION,'document_id':document['id'],'doc_type':kind,
        'source_path':unit.source_path,'start_page':unit.start_page+1,'end_page':unit.end_page+1,
        'tier':tier,'target_fields':targets,'reasons':reasons,'selected_page_ids':selected,
        'status':'retained_after_visual_screen' if skip else 'queued_for_field_reading',
        'all_source_pages_retained':True,'relevance_is_verified_fact':False,
        'routing_observations_complete':all('observation' in row and 'field_relevance' in row for row in rows),
        'attention_pages':attention,
        'partial_selection':len(selected)<len(keys)}


def priority_key(unit):
    return 0 if unit.doc_type in CORE_TYPES else 1 if unit.doc_type in SUPPORT_TYPES else 2
