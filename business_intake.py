"""Contract-scope intake excerpts for non-litigation and counsel matters.

No model calls or completed-work inference. Full classified contracts are
retained as evidence. Existing human edits and source-form preservation remain
the workflow's responsibility. A quoted scope is not proof of performance.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
import unicodedata

KEY = '_business_intake_source'
BINDING = 'business_intake_excerpt'


def compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text or '')))


def digest(source):
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def collect(fields, *, page_cache, allowed_sources, document_units):
    fields.pop(KEY, None)
    contracts = [u for u in document_units if u.doc_type == 'contract']
    # Competing contracts/amendments need reconciliation, never first-page wins.
    if len(contracts) != 1:
        return
    u = contracts[0]
    if (type(u.confidence) not in (float, int) or not math.isfinite(u.confidence)
            or u.confidence < .85 or not 0 <= u.start_page <= u.end_page < u.start_page + 24):
        return
    keys = [(u.source_path, n + 1) for n in range(u.start_page, u.end_page + 1)]
    if any(k not in allowed_sources or not isinstance(page_cache.get(k), str)
           or not 0 < len(page_cache[k].strip()) <= 18000 for k in keys):
        return
    source = {'doc_id': str(u.doc_id), 'pages': [
        {'source_path': p, 'page': n, 'quote': page_cache[(p, n)]} for p, n in keys]}
    if summarize(source):
        fields[KEY] = source


def summarize(source):
    if not isinstance(source, dict) or not isinstance(source.get('pages'), list):
        return None
    pages = source['pages']
    if not 1 <= len(pages) <= 24 or any(not isinstance(p, dict) or not isinstance(p.get('quote'), str) for p in pages):
        return None
    text = ''.join(compact(p['quote']) for p in pages)
    # Independent title evidence: generic business contracts are not retainers.
    title = re.search(r'非诉讼法律事务委托合同|常年法律顾问合同', text[:1000])
    if not title:
        return None
    if re.search(r'示例|参考模板|另案材料', text[:title.start()]):
        return None
    start = re.search(r'一[、.．]甲方委托的具体事项详述如下[:：]', text)
    if start:
        end = re.search(r'二[、.．]', text[start.end():])
        if not end:
            return None
        scope = text[start.end():start.end() + end.start()]
        # Only complete, compact clauses: no clipping conditions to fit a cell.
        if not 8 <= len(scope) <= 230 or not scope.endswith(('。', ';', '；')):
            return None
        return '委托合同约定：' + scope
    # For a long counsel scope, show explicitly partial complete clauses;
    # do not imply that a short list includes all services or is already done.
    start = re.search(r'一[、.．]乙方律师担任常年法律顾问的主要工作内容[:：]', text)
    if not start:
        return None
    section = text[start.end():]
    first = re.match(r'1[、.．](.{4,100}?[;；。])2[、.．](.{4,100}?[;；。])', section)
    if not first:
        return None
    value = ('委托合同约定提供常年法律顾问服务。部分服务范围：' + first[1] + first[2]
             + '其余范围、另行收费及限制条件以合同为准。')
    return value if len(value) <= 280 else None


def draft(fields, units, scope):
    if fields.get('案件类别') not in ('非诉', '非诉讼', '法律顾问', '顾问', 'nonlit', 'counsel'):
        return None
    if any(x.get('field') in ('案情简介', '委托人', '当事人') for x in fields.get('_field_conflicts', []) if isinstance(x, dict)):
        return None
    if {'案情简介', '委托人', '当事人'} & set(fields.get('_form_draft_blocked_fields', ())):
        return None
    source = fields.get(KEY)
    value = summarize(source)
    if not value:
        return None
    is_counsel = fields.get('案件类别') in ('法律顾问', '顾问', 'counsel')
    if ('常年法律顾问服务' in value) != is_counsel:
        return None
    pages = source['pages']
    contracts = [u for u in units if u.doc_type == 'contract']
    if len(contracts) != 1:
        return None
    u = contracts[0]
    if (str(u.doc_id) != source['doc_id'] or [(p['source_path'], p['page']) for p in pages]
            != [(u.source_path, n + 1) for n in range(u.start_page, u.end_page + 1)]):
        return None
    refs = [{**deepcopy(p), 'field': '案情简介', 'value': value, 'method': 'business_excerpt',
             'binding': BINDING, 'bundle_digest': digest(source)} for p in pages]
    return (value, refs, ['contract_scope_not_performance']) if all(scope(r) for r in refs) else None


def current_support(ref, fields):
    source = fields.get(KEY)
    value = summarize(source)
    expected = ref.get('input_value') if ref.get('method') == 'derived_form_draft' else ref.get('value')
    if not value or value != expected or value != fields.get('案情简介') or ref.get('bundle_digest') != digest(source):
        return None
    pages = source['pages']
    return deepcopy(pages) if any(all(ref.get(k) == p[k] for k in ('source_path', 'page', 'quote')) for p in pages) else None
