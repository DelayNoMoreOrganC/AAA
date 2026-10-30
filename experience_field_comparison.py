"""Compare recorded Agent field candidates, not final native form rendering."""
from agent_experience import ExperienceError
from agent_trace import TRACE_RUNS
from machine_field_candidates import KEY, VERSION
from form_field_policy import RULES
from form_cell_contracts import MANUAL_AREAS
from experience_boundary_comparison import project as source_projection

FIELDS = set(RULES) | {field for names in MANUAL_AREAS.values() for field in names}


def fail():
    raise ExperienceError('EXPERIENCE_FIELD_RESULT_INVALID')


def references(raw):
    if type(raw) is not dict or set(raw) != {'baseline_task_id','baseline_revision','candidate_task_id',
            'candidate_revision','expected_applicable','reference_reviewed','cells'}:
        fail()
    if (any(type(raw[k]) is not int or raw[k] < 1 for k in
            ('baseline_task_id','baseline_revision','candidate_task_id','candidate_revision'))
            or raw['baseline_task_id'] == raw['candidate_task_id']
            or raw['reference_reviewed'] is not True or type(raw['expected_applicable']) is not bool
            or type(raw['cells']) is not list or not 1 <= len(raw['cells']) <= len(FIELDS)):
        fail()
    seen=set()
    for cell in raw['cells']:
        if (type(cell) is not dict or set(cell) != {'field','mode','accepted_values','allowed_sources'}
                or type(cell['field']) is not str or cell['field'] not in FIELDS or cell['field'] in seen
                or cell['mode'] not in ('blank','exact','grounded_nonempty')
                or type(cell['accepted_values']) is not list or len(cell['accepted_values']) > 10
                or any(type(v) is not str or not v.strip() or len(v)>8192 for v in cell['accepted_values'])
                or (cell['mode']=='exact') != bool(cell['accepted_values'])
                or type(cell['allowed_sources']) is not list or len(cell['allowed_sources'])>100):
            fail()
        seen.add(cell['field'])
        if cell['mode']=='blank' and cell['allowed_sources'] or cell['mode']!='blank' and not cell['allowed_sources']:
            fail()
        for source in cell['allowed_sources']:
            if (type(source) is not dict or set(source) != {'file_id','page'}
                    or type(source['file_id']) is not str or not source['file_id']
                    or type(source['page']) is not int or source['page']<1):
                fail()
    return raw


def project(fields, manifest, experience_sha256):
    original = source_projection(fields,manifest,experience_sha256)
    record=fields[TRACE_RUNS][0]['body']['payload'].get(KEY)
    if (type(record) is not dict or record.get('version') != VERSION
            or record.get('stage') != 'accepted_agent_fields_before_normalization_and_manual_edits'
            or type(record.get('cell_policy_digest')) is not str or len(record['cell_policy_digest']) != 64
            or record.get('native_output_verified') is not False or type(record.get('cells')) is not dict
            or set(record['cells']) != FIELDS):
        fail()
    for cell in record['cells'].values():
        if (type(cell) is not dict or type(cell.get('value')) is not str
                or type(cell.get('policy_projection')) is not str or type(cell.get('sources')) is not list
                or any(type(cell.get(k)) is not bool for k in ('value_type_valid','human_influenced','unresolved_conflict'))
                or type(cell.get('invalid_source_count')) is not int or cell['invalid_source_count']<0):
            fail()
        for source in cell['sources']:
            if (type(source) is not dict or set(source) != {'source_sha256','page'}
                    or type(source['source_sha256']) is not str or type(source['page']) is not int
                    or not any(row['sha256']==source['source_sha256'] and 1<=source['page']<=row['pages'] for row in manifest)):
                fail()
    return {**original,'cells':record['cells'],'cell_policy_digest':record['cell_policy_digest']}


def compare(reference, baseline, candidate, manifest):
    if baseline['cell_policy_digest'] != candidate['cell_policy_digest']:
        raise ExperienceError('EXPERIENCE_COMPARISON_FIELD_POLICY_MISMATCH')
    rows={row['file_id']:row for row in manifest}
    results=[]
    for label in references(reference)['cells']:
        allowed=set()
        for source in label['allowed_sources']:
            owner=rows.get(source['file_id'])
            if not owner or source['page']>owner['pages']:fail()
            allowed.add((owner['sha256'],source['page']))
        result={'field':label['field'],'mode':label['mode']}
        for name, observed in [('baseline',baseline),('candidate',candidate)]:
            cell=observed['cells'][label['field']]
            value=cell['policy_projection']
            anchors={(source['source_sha256'],source['page']) for source in cell['sources']}
            checks={'valid_value_type':cell['value_type_valid'], 'not_human_influenced':not cell['human_influenced'],
                    'no_unresolved_conflict':not cell['unresolved_conflict'], 'source_scope_valid':cell['invalid_source_count']==0}
            if label['mode']=='blank':
                checks['value_requirement']=not value.strip()
            else:
                checks['value_requirement']=(value in label['accepted_values'] if label['mode']=='exact' else bool(value.strip()))
                checks['source_requirement']=bool(anchors) and anchors<=allowed
            result[name]={'checks':checks,'matches':all(checks.values())}
        results.append(result)
    return {'cells':results,'baseline_checks_match':all(row['baseline']['matches'] for row in results),
        'candidate_checks_match':all(row['candidate']['matches'] for row in results),
        'new_errors':any(passed and not row['candidate']['checks'][key] for row in results
                         for key,passed in row['baseline']['checks'].items()),
        'evaluated_fields':[row['field'] for row in results],
        'not_evaluated_fields':sorted(FIELDS-{row['field'] for row in results}),
        'semantic_completeness_verified':False,'native_output_verified':False,
        'stage':'accepted_agent_fields_with_blank_policy_projection'}
