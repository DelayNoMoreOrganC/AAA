"""Case-bound, explicitly stated legal-fee settlement balances.

No arithmetic, payment inference from invoices, or summation of receipts.
The amounts describe the supplied settlement record, not bank verification.
"""
from copy import deepcopy
import os
import re
import unicodedata

FIELDS = ('应收业务费', '已收业务费', '尚欠业务费', '应退业务费')
BINDING = 'case_fee_settlement'
LABELS = {
    '应收业务费': ('应收业务费', '律师费应收总额', '应收律师费总额'),
    '已收业务费': ('已收业务费', '律师费累计实收', '累计已收律师费', '律师费实收总额'),
    '尚欠业务费': ('尚欠业务费', '尚欠律师费', '律师费未收余额'),
    '应退业务费': ('应退业务费', '应退律师费', '律师费应退金额'),
}
TITLE = re.compile(r'(?:本案)?(?:律师费|法律服务费|律师业务费)(?:收支)?结算(?:单|表)')
AMOUNT = r'(?:人民币)?(?:0|[1-9]\d{0,11}|[1-9]\d{0,2}(?:,\d{3})+)(?:\.\d{1,2})?(?:万元|元)'
RISK = re.compile(r'拟|预计|估算|暂估|待核|待确认|未经核对|作废|撤销|参考|模板|另案|其他案件|其他费用|包含诉讼费|含诉讼费|含代垫|含差旅|不含|其中|第一期|第二期|本次|部分收款|发票金额|开票金额|如已|如果|假设|声称|诉称|主张')


def compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))


def defer_candidate(field, ref, provenance):
    """Keep receipt/settlement evidence without setting a balance too early."""
    if field not in FIELDS:
        return False
    rows = provenance.setdefault(field, [])
    if ref not in rows:
        rows.append(ref)
    return True


def _supports_in_cache(supports, page_cache, allowed_sources):
    from fact_evidence import validate_fact
    return bool(supports) and all(item.get('method') == 'human' or (
        (item.get('source_path'), item.get('page')) in allowed_sources
        and validate_fact(item['field'], item['value'], item.get('quote'),
            page_cache.get((item.get('source_path'), item.get('page'))))) for item in supports)


def _same_identity(left, right):
    return all(left.get(key) == right.get(key) for key in
               ('field', 'value', 'method', 'quote', 'source_path', 'page'))


def _supplement_view(context, supplied):
    """Use internal immutable identity context without persisting it as a new fact."""
    if not (isinstance(supplied, dict) and supplied.get('version') == 1
            and isinstance(supplied.get('binding'), dict) and supplied['binding']
            and isinstance(supplied.get('fields'), dict) and isinstance(supplied.get('provenance'), dict)
            and isinstance(supplied.get('conflicts'), list) and isinstance(supplied.get('manual_fields'), list)
            and all(isinstance(key, str) for key in supplied['manual_fields'])):
        return context, set()
    view = deepcopy(context)
    blocked = set(supplied['manual_fields']).intersection(FIELDS)
    parent = supplied['fields']
    identity_keys = ('委托人', '委托人名称', '委托方', '案号', '法院收案号', '合同号')
    conflicts = supplied['conflicts'] + list(context.get('_field_conflicts', []))
    for row in conflicts:
        if not isinstance(row, dict):
            return context, set(FIELDS)
        if not row.get('resolved'):
            if row.get('field') in identity_keys:
                return context, set(FIELDS)
            if row.get('field') in FIELDS:
                blocked.add(row['field'])
    for key in identity_keys:
        value = parent.get(key)
        if key in supplied['manual_fields'] and not compact(value):
            return context, set(FIELDS)
        if value is None:
            continue
        if not isinstance(value, str) or (compact(context.get(key)) and compact(context[key]) != compact(value)):
            return context, set(FIELDS)
        if not compact(view.get(key)):
            view[key] = value
        old = supplied['provenance'].get(key) or []
        new = view['_provenance'].get(key) or []
        old = [old] if isinstance(old, dict) else old
        new = [new] if isinstance(new, dict) else new
        if not isinstance(old, list) or not isinstance(new, list):
            return context, set(FIELDS)
        view['_provenance'][key] = deepcopy(old + new)
    return view, blocked


def _certified_support(supports, source, page_cache, allowed_sources, supplied):
    """Keep source hashes on inherited references; never synthesize old pages."""
    if _supports_in_cache(supports, page_cache, allowed_sources):
        return supports, {}
    if not supports or not isinstance(supplied, dict):
        return None, {}
    scope, certificates = supplied.get('fee_source_scope'), supplied.get('fee_provenance')
    if not isinstance(scope, list) or not isinstance(certificates, dict):
        return None, {}
    def path(value):
        return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ''
    by_path = {path(row.get('path')): row for row in scope if isinstance(row, dict)}
    if len(by_path) != len(scope) or '' in by_path:
        return None, {}
    def valid(row, page):
        return (isinstance(row, dict) and isinstance(row.get('file_id'), str) and bool(row['file_id'])
                and isinstance(row.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
                and type(row.get('pages')) is int and type(page) is int and 1 <= page <= row['pages'])
    primary = by_path.get(path(source[0]))
    if not valid(primary, source[1]):
        return None, {}
    result = []
    for ref in supports:
        if _supports_in_cache([ref], page_cache, allowed_sources):
            result.append(deepcopy(ref)); continue
        rows = certificates.get(ref['field'])
        if not isinstance(rows, list):
            return None, {}
        chosen = None
        for cert in rows:
            if not isinstance(cert, dict) or not _same_identity(ref, cert):
                continue
            row = by_path.get(path(cert.get('source_path')))
            if (valid(row, cert.get('page')) and cert.get('file_id') == row['file_id']
                    and cert.get('source_sha256') == row['sha256']):
                chosen = deepcopy(cert); break
        if chosen is None:
            return None, {}
        result.append(chosen)
    return result, dict(file_id=primary['file_id'], source_sha256=primary['sha256'])


def _other_case_record(text, fields):
    """Both explicit client and trial number must differ; other stages alone
    are not enough to declare another case. This never removes original pages.
    """
    from fact_evidence import validate_fact
    supports = identity_support(fields, '案号')
    if not amounts(text) or not supports:
        return False
    lines = [compact(line) for line in text.splitlines() if compact(line)]
    clients = [m[1] for line in lines if (m := re.fullmatch(r'(?:委托人|委托方):(.+?)[。;；]?', line))]
    numbers = [m[1] for line in lines if (m := re.fullmatch(r'案号:(.+?)[。;；]?', line))]
    return (len(clients) == len(numbers) == 1
            and clients[0] != compact(supports[0]['value']) and numbers[0] != compact(supports[1]['value'])
            and validate_fact('案号', numbers[0], '案号:' + numbers[0], '案号:' + numbers[0]))


def amounts(text):
    if not isinstance(text, str) or not 0 < len(text) <= 18000:
        return {}
    lines = [compact(line) for line in text.splitlines() if compact(line)]
    if not lines or not TITLE.fullmatch(lines[0]) or RISK.search(compact(text)):
        return {}
    # Complete labelled rows only: no cropped amounts, percentages, missing
    # currencies or continuation prose. This is deliberately not a bank parser.
    result = {}
    for field, aliases in LABELS.items():
        rows = []
        for line in lines[1:]:
            match = re.fullmatch('(?:' + '|'.join(aliases) + r')[:：](' + AMOUNT + r')[。;；]?', line)
            if match:
                rows.append(match[1])
        mentioned = re.findall('(?:' + '|'.join(aliases) + r')[:：]', compact(text))
        if len(rows) == len(mentioned) == 1:
            result[field] = rows[0]
    return result


def validate_settlement_fact(field, value, quote, page):
    if not (field in FIELDS and all(isinstance(x, str) and x.strip() for x in (value, quote, page))
            and compact(quote) in compact(page) and compact(value) in compact(quote)):
        return False
    if amounts(page).get(field) == compact(value):
        return True
    # Preserve receipt-event evidence accepted by the existing fact verifier.
    # It remains provisional: recall() will not print it as a cumulative balance
    # without the independent case-bound settlement record above.
    if field == '已收业务费' and not RISK.search(compact(page)):
        lines = [compact(line) for line in page.splitlines() if compact(line)]
        if not lines:
            return False
        if lines[0] in ('律师费收据', '律师费收款收据', '收据'):
            rows = lines[1:]
        elif len(lines) == 1 and lines[0].startswith('收据:'):
            rows = [lines[0][3:]]
        else:
            return False
        pattern = r'(?:本所)?(?:实收|实际收到|收讫)(?:本案)?律师费[:：]?(' + AMOUNT + r')[。]?'
        return any(m[1] == compact(value) for row in rows if (m := re.fullmatch(pattern, row)))
    return False


def identity_support(fields, identity_key=None):
    from pleading_parties import client_ref
    from fact_evidence import validate_fact
    client = client_ref(fields)
    if not client:
        return None
    if any(compact(fields.get(alias)) and compact(fields[alias]) != compact(client['value'])
           for alias in ('委托人名称', '委托方')):
        return None
    if (fields.get('案号') and fields.get('法院收案号')
            and compact(fields['案号']) != compact(fields['法院收案号'])):
        return None
    if any(r.get('field') in ('委托人名称', '委托方', '法院收案号') and not r.get('resolved')
           for r in fields.get('_field_conflicts', [])):
        return None
    for key in ('案号', '合同号'):
        if identity_key is not None and key != identity_key:
            continue
        value = fields.get(key)
        if not value or any(r.get('field') == key and not r.get('resolved') for r in fields.get('_field_conflicts', [])):
            continue
        refs = (fields.get('_provenance') or {}).get(key) or []
        refs = [refs] if isinstance(refs, dict) else refs
        for ref in reversed(refs):
            if not isinstance(ref, dict) or ref.get('value') != value:
                continue
            if ref.get('method') == 'human' or (ref.get('method') in ('local_agent', 'visual_agent_local_evidence')
                    and not ref.get('derivation') and validate_fact(key, value, ref.get('quote'), ref.get('quote'))):
                return [client, {**deepcopy(ref), 'field': key}]
    return None


def bound_amounts(text, fields, identity_key=None):
    values = amounts(text)
    if not values:
        return {}, None
    lines = [compact(line) for line in text.splitlines() if compact(line)]
    supports = None
    for key in (identity_key,) if identity_key else ('案号', '合同号'):
        candidate = identity_support(fields, key)
        labels = ('案号',) if key == '案号' else ('委托合同编号', '委托代理合同编号')
        matches = [m[1] for line in lines if (m := re.fullmatch('(?:' + '|'.join(labels) + r')[:：](.+?)[。;；]?', line))]
        if candidate and matches == [compact(candidate[1]['value'])]:
            supports = candidate
            break
    if not supports:
        return {}, None
    client, identity = supports
    for key, value, labels in [
        ('委托人', client['value'], ('委托人', '委托方')),
        (identity['field'], identity['value'], ('案号',) if identity['field'] == '案号' else ('委托合同编号', '委托代理合同编号')),
    ]:
        matches = [m[1] for line in lines if (m := re.fullmatch('(?:' + '|'.join(labels) + r')[:：](.+?)[。;；]?', line))]
        if len(matches) != 1 or matches[0] != compact(value):
            return {}, None
    # Other visible case/contract identifiers cannot contradict this binding.
    for line in lines:
        m = re.fullmatch(r'(案号|委托合同编号|委托代理合同编号)[:：](.+?)[。;；]?', line)
        if m:
            key = '案号' if m[1] == '案号' else '合同号'
            if fields.get(key) and compact(fields[key]) != m[2]:
                return {}, None
    return values, supports


def current_support(ref, fields):
    if not isinstance(ref, dict) or ref.get('binding') != BINDING:
        return None
    field = ref.get('field')
    if field not in FIELDS or fields.get(field) != ref.get('value'):
        return None
    if any(r.get('field') in (field, '委托人', '案号', '合同号') and not r.get('resolved')
           for r in fields.get('_field_conflicts', [])):
        return None
    original_support = ref.get('identity_support')
    if (not isinstance(original_support, list) or len(original_support) != 2
            or not all(isinstance(item, dict) for item in original_support)):
        return None
    values, supports = bound_amounts(ref.get('quote'), fields, original_support[1].get('field'))
    if (values.get(field) != compact(ref.get('value')) or not supports
            or not all(_same_identity(now, old) for now, old in zip(supports, original_support))):
        return None
    return [deepcopy(item) for item in original_support if item.get('method') != 'human']


def recall(fields, provenance, conflicts, *, page_cache, allowed_sources, manual_fields, method, fact_review, supplied=None):
    """Resolve candidates only after all identities and cached pages are known."""
    context = {**fields, '_provenance': provenance, '_field_conflicts': conflicts}
    context, blocked = _supplement_view(context, supplied)
    found = {key: [] for key in FIELDS}
    def review_record(path, page, code, reason):
        if not any(row.get('source_path') == path and row.get('page') == page
                   and row.get('reason_code') == code for row in fact_review):
            fact_review.append(dict(field='', source_path=path, page=page, reason_code=code, reason=reason))
    for path, page in sorted(set(page_cache) & set(allowed_sources)):
        text = page_cache[(path, page)]
        values, supports = bound_amounts(text, context)
        supports, source_binding = _certified_support(supports, (path, page), page_cache, allowed_sources, supplied)
        if not supports:
            if amounts(text):
                known = identity_support(context, '案号')
                different = _supports_in_cache(known, page_cache, allowed_sources) and _other_case_record(text, context)
                review_record(path, page, 'fee_record_other_case' if different else 'fee_record_scope_unverified',
                    '这份费用记录的委托人和案号均与本案不同，未用于本案金额；请核对材料归属' if different
                    else '这份费用记录尚未与本案及委托人可靠关联，请核对材料归属')
            continue
        for field, value in values.items():
            if field in blocked:
                continue
            found[field].append(dict(field=field, value=value, quote=text, source_path=path, page=page,
                method=method, binding=BINDING, derivation=BINDING, identity_support=deepcopy(supports), **source_binding))
    for field in FIELDS:
        refs = provenance.get(field) or []
        refs = [refs] if isinstance(refs, dict) else refs
        for ref in refs:
            if not isinstance(ref, dict) or ref.get('method') == 'human':
                continue
            location = (ref.get('source_path'), ref.get('page'))
            text = page_cache.get(location)
            if (location in allowed_sources and not amounts(text)
                    and validate_settlement_fact(field, ref.get('value'), ref.get('quote'), text)):
                review_record(*location, 'fee_receipt_balance_unverified',
                    '单笔收款证据已保留，尚未与累计结算核对；请核对是否影响本案费用余额')
    count = 0
    for field in FIELDS:
        refs = provenance.get(field) or []
        refs = [refs] if isinstance(refs, dict) else refs
        if field in manual_fields or any(r.get('method') == 'human' for r in refs):
            continue
        values = list(dict.fromkeys(r['value'] for r in found[field]))
        if len(values) > 1 and not any(r.get('field') == field and not r.get('resolved') for r in conflicts):
            conflicts.append(dict(field=field, values=values, sources=deepcopy(found[field]),
                reason_code='fee_settlement_conflict', reason='费用结算记录金额不一致，请核对适用记录'))
        if len(values) == 1 and not any(r.get('field') == field and not r.get('resolved') for r in conflicts):
            if fields.get(field) and compact(fields[field]) != compact(values[0]):
                conflicts.append(dict(field=field, values=[fields[field], values[0]], sources=deepcopy(found[field]),
                    reason_code='fee_settlement_conflict'))
            else:
                changed = fields.get(field) != values[0] or any(r not in refs for r in found[field])
                fields[field] = values[0]
                provenance[field] = refs + [r for r in found[field] if r not in refs]
                count += int(changed)
                for row in fact_review:
                    if row.get('field') == field and any(row.get('source_path') == r['source_path'] and row.get('page') == r['page'] for r in found[field]):
                        row['resolution'] = 'field_supported_by_cached_source'
                continue
        # A syntactically valid model amount cannot bypass case identity or a
        # conflicting settlement record. Keep audit evidence, not a printed sum.
        if fields.get(field) or refs:
            fields[field] = ''
            if any(row.get('field') == field and not row.get('resolved') for row in conflicts):
                continue  # Existing conflict already includes its source rows.
            locations = {(r.get('source_path'), r.get('page')) for r in refs
                         if isinstance(r.get('source_path'), str) and type(r.get('page')) is int}
            for path, page in locations or {(None, None)}:
                if path is not None and any(row.get('source_path') == path and row.get('page') == page
                        and row.get('reason_code') in ('fee_record_other_case', 'fee_record_scope_unverified',
                                                      'fee_receipt_balance_unverified') for row in fact_review):
                    continue
                row = dict(field=field, reason_code='fee_settlement_unbound',
                    reason='费用结算金额尚未与本案及委托人可靠关联')
                if path is not None:
                    row.update(source_path=path, page=page)
                fact_review.append(row)
    return count
