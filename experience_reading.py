"""Apply approved reading guidance without overriding evidence/retention rules."""
from agent_experience import require_context

FIELD_MAP = {"case_intro": ["案情简介"], "closing_summary": ["结案小结"],
             "handling_result": ["审（办）结果"], "parties": ["委托人", "当事人", "对方当事人"],
             "fees": ["收费标准"], "dates": ["收案日期", "立案审批日期", "结案日期"]}
KIND_MAP = {"complaint":"pleading", "appeal":"pleading", "indictment":"pleading", "plea":"defense",
            "agent_opinion":"opinion", "legal_work":"work_record", "meeting_record":"work_record",
            "court_record":"work_record", "client_talk":"work_record"}


def apply_reading(context, plan, unit, document, rows_by_id, *, case_type, fields, substantive_sources_present):
    context = require_context(context)
    if context is None:
        return
    rows = [rows_by_id[k] for k in document['keys']]
    observations = [r.get('observation') or {} for r in rows]
    signals = {'field_conflict': bool(fields.get('_field_conflicts')),
               'missing_core_source': not substantive_sources_present,
               'unresolved_boundary': any(r.get('_boundary_unresolved') for r in rows)}
    # Only complete observations establish a negative. A model category never
    # establishes a signed/explicit attachment relation or a verified fact.
    def observed(name, key, known, positive):
        values = [o.get(key) for o in observations]
        if any(v in positive for v in values):
            signals[name] = True
        elif values and all(v in known for v in values):
            signals[name] = False
    observed('unclear_image', 'quality', {'clear'}, {'small_text','blurred','occluded'})
    observed('handwritten', 'writing', {'printed'}, {'handwritten','mixed'})
    rotations = [o.get('suggested_rotation') for o in observations]
    signals['unknown_orientation'] = any(type(r) is not int or r != 0 for r in rotations)
    if any(r.get('field_relevance',{}).get('fields') for r in rows):
        signals['field_reference'] = True
    elif rows and all('field_relevance' in r and r['field_relevance'].get('purpose') != 'unknown' for r in rows):
        signals['field_reference'] = False
    kind = KIND_MAP.get(unit.doc_type, unit.doc_type)
    candidates = context.matching({'case_type':case_type, 'document_kind':kind, 'signals':signals})
    records = []
    for rule in candidates:
        payload = rule['payload']
        record = {'id':rule['id'], 'revision':rule['revision'], 'action':payload['action'],
                  'status':'guidance_only', 'signals':dict(signals)}
        if payload['action'] == 'read_for_field':
            targets = [field for group in payload['target_fields'] for field in FIELD_MAP[group]]
            plan['target_fields'] = list(dict.fromkeys(plan['target_fields'] + targets))
            if not plan['selected_page_ids']:
                keys = document['keys']
                plan['selected_page_ids'] = list(dict.fromkeys([keys[0], keys[-1]]))
            if plan['tier'] == 'archive':
                plan['tier'] = 'supporting'
            plan['status'] = 'queued_for_field_reading'
            plan['partial_selection'] = len(plan['selected_page_ids']) < len(document['keys'])
            plan['reasons'].append('approved_experience_targeted_reading')
            record.update(status='reading_requested_not_fact_verified', target_fields=targets)
        # retain_only can never remove selected pages; boundaries are never
        # changed by this planner, only by the bounded visual/source checks.
        records.append(record)
    plan['experience'] = {'snapshot_sha256':context.identity, 'matched':records}
