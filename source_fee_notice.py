"""Summarize an explicitly selected fee option, retaining its source notice.

This is a document statement, not proof of a signed contract or money received.
Unknown layouts remain for the normal model/review path. No I/O or model calls.
"""
from copy import deepcopy
import re
import unicodedata

FIELD = '收费标准'
DERIVATION = 'selected_notice_fee'
IDENTITY = ('委托人', '对方当事人', '案由')


def compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))


def candidate(text, fields, *, summary_version=2):
    if type(summary_version) is not int or summary_version not in (1, 2):
        return None
    if not isinstance(text, str) or not 0 < len(text) <= 18000:
        return None
    page = compact(text).replace('_', '')
    identity = {key: compact(fields.get(key)) for key in IDENTITY}
    if not all(identity.values()) or any(len(v) > 160 for v in identity.values()):
        return None
    if not page.startswith('委托代理通知书') or re.search(
            r'示例|范本|参考模板|另案|转述|尚未决定|撤销本通知|通知书已作废', page):
        return None
    # The source itself must tie the selected fee to the same client, complete
    # opponent list and matter. Filename/title similarity cannot establish this.
    binding = '现决定将' + identity['委托人'] + '与' + identity['对方当事人'] + identity['案由'] + '案件交由贵所代理'
    if page.count(binding) != 1:
        return None
    selections = list(re.finditer(r'按照以下第([12])种计费方式计算律师费[:：]', page))
    if len(selections) != 1:
        return None
    selected = selections[0]
    block = page[selected.end():]
    # Stop only at the next numbered section; the complete original page is
    # retained below, including adjustment terms and references to continuations.
    end = re.search(r'二[、.．]', block)
    if not end:
        return None
    options = block[:end.start()]
    first = re.fullmatch(
        r'1[.．、]前期费用加风险代理收费方式\(1\)前期律师费[:：](?P<amount>\d+(?:\.\d{1,2})?)?元[。;；]?'
        r'\(2\)风险代理律师费费率为[:：]基准费率(?P<rate>\d+(?:\.\d+)?)?%[。;；]?'
        r'2[.．、]固定收费方式[:：]固定律师费[:：](?P<fixed>\d+(?:\.\d{1,2})?)?元[。;；]?', options)
    if not first:
        return None
    if selected[1] == '1':
        if not first['amount'] or not first['rate'] or not 0 < float(first['rate']) <= 100:
            return None
        summary = (f"前期{first['amount']}元\n风险等见通知书" if summary_version == 1
                   else f"前期{first['amount']}元\n风险基准{first['rate']}%")
    elif first['fixed']:
        summary = f"固定{first['fixed']}元\n调整见通知书"
    else:
        return None
    if sum(.5 if ord(c) < 128 else 1 for c in summary) > 15:
        return None  # Native renderer remains the final cell-capacity gate.
    result = {'field': FIELD, 'value': summary, 'quote': text,
            'derivation': DERIVATION, 'binding': DERIVATION,
            'bound_fields': identity, 'selected_option': selected[1],
            'fee_options': options, 'fee_terms': block,
            'subject': identity['委托人']}
    if summary_version == 2:
        result['summary_version'] = 2
    return result


def reference_supported(field, value, ref, fields):
    if (field != FIELD or not isinstance(ref, dict) or ref.get('derivation') != DERIVATION
            or ref.get('value') != value or fields.get(FIELD) != value):
        return False
    if any(isinstance(row, dict) and row.get('field') in (*IDENTITY, FIELD, '委托人名称', '委托方')
           and row.get('resolved') is not True for row in fields.get('_field_conflicts') or []):
        return False
    clients = {compact(fields.get(k)) for k in ('委托人', '委托人名称', '委托方') if compact(fields.get(k))}
    if clients != {compact(ref.get('subject'))}:
        return False
    # Historical summaries remain valid records. A normal field save must not
    # silently replace or clear them merely because a newer summary is richer.
    fresh = candidate(ref.get('quote'), fields, summary_version=ref.get('summary_version', 1))
    return bool(fresh and all(ref.get(k) == fresh[k] for k in fresh))


def reference_note(fields):
    """A visible source pointer for v2 summaries; never a payment assertion."""
    fields = fields or {}
    refs = (fields.get('_provenance') or {}).get(FIELD) or []
    refs = [refs] if isinstance(refs, dict) else refs
    for ref in refs:
        if (isinstance(ref, dict) and ref.get('summary_version') == 2
                and ref.get('method') in ('local_agent', 'visual_agent_local_evidence')
                and reference_supported(FIELD, fields.get(FIELD), ref, fields)):
            terms = ref['fee_terms']
            if all(word in terms for word in ('增加', '扣减', '上限', '债权转让')):
                return '收费增减、上限及转让计费等，详卷内委托代理通知书。'
            return '其他收费约定详卷内委托代理通知书。'
    return ''


def current_support(ref, fields):
    original = ref
    if ref.get('method') == 'derived_form_draft':
        if ref.get('input_field') != FIELD or ref.get('input_value') != fields.get(FIELD):
            return None
        refs = (fields.get('_provenance') or {}).get(FIELD) or []
        refs = [refs] if isinstance(refs, dict) else refs
        original = next((r for r in refs if isinstance(r, dict)
                         and r.get('method') == ref.get('input_method')
                         and all(r.get(k) == ref.get(k) for k in
                                 ('source_path', 'page', 'quote', 'fee_terms', 'bound_fields'))
                         and reference_supported(FIELD, fields.get(FIELD), r, fields)), None)
    return [] if original and reference_supported(FIELD, fields.get(FIELD), original, fields) else None


def recall_fee(fields, provenance, conflicts, *, page_cache, allowed_sources,
               manual_fields=(), method='visual_agent_local_evidence', fact_review):
    if method not in ('local_agent', 'visual_agent_local_evidence'):
        raise ValueError('unsupported_local_evidence_method')
    refs = provenance.get(FIELD) or []
    refs = [refs] if isinstance(refs, dict) else refs
    if (fields.get(FIELD) or FIELD in manual_fields
            or any(isinstance(r, dict) and r.get('method') == 'human' for r in refs)
            or any(r.get('field') in (*IDENTITY, FIELD) and r.get('resolved') is not True for r in conflicts)):
        return 0
    found = []
    for path, page in sorted(set(page_cache) & set(allowed_sources)):
        if not isinstance(path, str) or not path or type(page) is not int or page < 1:
            continue
        row = candidate(page_cache[(path, page)], fields)
        if row:
            found.append({**row, 'source_path': path, 'page': page, 'method': method,
                          'candidate_origin': 'local_cached_fee_notice'})
    if not found:
        return 0
    # Equal short summaries can conceal different risk rates or adjustments.
    # Compare complete fee text before any short value becomes accepted.
    if len({r['fee_terms'] for r in found}) != 1:
        conflicts.append({'field': FIELD, 'values': list(dict.fromkeys(r['value'] for r in found)),
                          'sources': deepcopy(found), 'source': deepcopy(found[-1]),
                          'reason_code': 'fee_notice_terms_conflict',
                          'reason': '收费通知书条款存在差异，请核对选用版本'})
        return 0
    fields[FIELD] = found[0]['value']
    provenance[FIELD] = refs + found
    for entry in fact_review:
        if entry.get('field') == FIELD and any(entry.get('source_path') == r['source_path']
                                             and entry.get('page') == r['page'] for r in found):
            entry['resolution'] = 'field_supported_by_cached_source'
    return 1
