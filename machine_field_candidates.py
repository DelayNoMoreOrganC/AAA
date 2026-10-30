"""Private immutable observation of accepted Agent fields, before manual edits.

This is NOT a Word/rendering receipt. Later normalization, derived drafts and
native form layout have their own checks. Original quotes stay in provenance.
"""
from copy import deepcopy
import os
from form_field_policy import RULES
from form_cell_contracts import MANUAL_AREAS, optional_output

KEY = '_machine_field_candidates'
VERSION = 'machine-field-candidates-v1'


def capture(fields, metadata, source_identities, *, case_type):
    sources = {os.path.normcase(os.path.abspath(path)): row for path,row in source_identities.items()}
    manual = {field for names in MANUAL_AREAS.values() for field in names}
    context = {**fields, '_provenance':metadata.get('_provenance') or {},
               '_field_conflicts':metadata.get('_field_conflicts') or []}
    cells = {}
    for field in sorted(set(RULES) | manual):
        raw = fields.get(field, '')
        valid = raw is None or type(raw) is str
        value = (raw or '') if valid else ''
        mode = 'manual_blank' if field in manual else RULES[field][0]
        projection = optional_output(field, value, context) if valid else None
        projected = '' if field in manual else projection['value'] if projection else value
        refs = context['_provenance'].get(field) or []
        refs = refs if isinstance(refs,list) else [refs]
        anchors, invalid_sources, human = [], 0, False
        expanded = []
        for ref in refs:
            if isinstance(ref,dict) and ref.get('value') == value and ref.get('binding') == 'model_form_synthesis':
                from form_synthesis import current_support
                support = current_support(ref, context)
                if support is None:
                    invalid_sources += 1
                else:
                    expanded.extend({**item, 'value':value} for item in support)
        for ref in [*refs, *expanded]:
            if not isinstance(ref,dict) or ref.get('value') != value:
                continue
            if ref.get('method') == 'human':
                human = True
                continue
            path, page = ref.get('source_path'), ref.get('page')
            if path is None and page is None:
                continue  # A binding alone is not a physical page citation.
            source = sources.get(os.path.normcase(os.path.abspath(path))) if type(path) is str else None
            if (not source or type(page) is not int or not 1 <= page <= source['page_count']
                    or ref.get('source_sha256',source['sha256']) != source['sha256']):
                invalid_sources += 1
                continue
            anchor = {'source_sha256':source['sha256'], 'page':page}
            if anchor not in anchors:anchors.append(anchor)
        cells[field] = {'value':value, 'value_type_valid':valid, 'mode':mode,
            'policy_projection':projected, 'projection_code':projection['code'] if projection else mode,
            'sources':anchors, 'invalid_source_count':invalid_sources, 'human_influenced':human,
            'unresolved_conflict':any(isinstance(row,dict) and row.get('field') == field and not row.get('resolved')
                                      for row in context['_field_conflicts'])}
    from agent_trace import digest
    return {'version':VERSION, 'stage':'accepted_agent_fields_before_normalization_and_manual_edits',
            'cell_policy_digest':digest({'rules':RULES, 'manual_areas':MANUAL_AREAS}),
            'case_type':case_type, 'native_output_verified':False, 'cells':deepcopy(cells)}
