"""Bounded report synthesis from a complete operative part and closure notice.

No free-form facts, I/O, model calls, payment inference or signature inference.
Only the recognized secured-loan judgment shape is condensed here; every other
shape stays with the existing extraction/review path, never a partial verdict.
"""
from copy import deepcopy
from datetime import date
import re
import math
import unicodedata

FIELD = '结案小结'
DERIVATION = 'court_report_summary'
IDENTITY = ('委托人', '对方当事人', '案由', '案号', '执行案号')
ALIASES = ('结案小结', '审（办）结果', '审(办)结果', '审办结果', '办案小结')


def compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))


def body(text):
    return compact(re.sub(r'(?m)^\s*\d+\s*/\s*\d+\s*$', '', text))


def _same_identities(fields):
    values = {key: compact(fields.get(key)) for key in IDENTITY}
    if not all(values.values()):
        return None
    if values['案由'] != '金融借款合同纠纷':
        return None
    clients = {compact(fields.get(k)) for k in ('委托人', '委托人名称', '委托方') if compact(fields.get(k))}
    if clients != {values['委托人']}:
        return None
    if any(isinstance(r, dict) and r.get('field') in (*IDENTITY, *ALIASES, '当事人')
           and r.get('resolved') is not True for r in fields.get('_field_conflicts') or []):
        return None
    return values


def _document(record):
    if not isinstance(record, dict) or record.get('kind') not in ('judgment', 'execution'):
        return None
    start, end = record.get('start_page'), record.get('end_page')
    if type(start) is not int or type(end) is not int or not 1 <= start <= end or end - start > 50:
        return None
    pages = record.get('pages')
    if not isinstance(pages, list) or not pages or len(pages) > 52:
        return None
    result = {}
    for page in pages:
        if not isinstance(page, dict):
            return None
        number, text = page.get('page'), page.get('quote')
        if (type(number) is not int or not start <= number <= end or number in result
                or not isinstance(text, str) or not 0 < len(text) <= 18000):
            return None
        result[number] = text
    return result if start in result and isinstance(record.get('source_path'), str) and record['source_path'] else None


def summarize(documents, fields):
    identity = _same_identities(fields)
    if not identity or not isinstance(documents, list) or len(documents) != 2:
        return None
    judgment, execution = documents
    if not isinstance(judgment, dict) or not isinstance(execution, dict):
        return None
    if judgment.get('kind') != 'judgment' or execution.get('kind') != 'execution':
        return None
    jp, ep = _document(judgment), _document(execution)
    if not jp or not ep:
        return None
    client, opponents, number = (identity[k] for k in ('委托人', '对方当事人', '案号'))
    from court_roster_details import candidates
    first = jp[judgment['start_page']]
    roster = candidates(first, client, number)
    if not any(r['field'] == '对方当事人' and compact(r['value']) == opponents
               and r['role'] == '原告' for r in roster):
        return None
    heading = body(first)
    if '民事判决书' not in heading:
        return None
    # Only the complete trailing operative part can be condensed. A missing
    # continuation, extra numbered ruling or an unrecognized clause rejects the
    # whole summary instead of dropping an unfavorable/conditional obligation.
    starts = [n for n, text in jp.items() if '判决如下' in body(text)]
    if len(starts) != 1 or any(n not in jp for n in range(starts[0], judgment['end_page'] + 1)):
        return None
    tail = ''.join(body(jp[n]) for n in range(starts[0], judgment['end_page'] + 1))
    if tail.count('判决如下') != 1:
        return None
    operative = tail.split('判决如下', 1)[1].lstrip(':：')
    cost = re.search(r'本案案件受理费', operative)
    appeal = re.search(r'如不服本判决', operative)
    if not cost or not appeal or cost.start() >= appeal.start():
        return None
    numbered = list(re.finditer(r'(?<![^。;；])([一二三四五六七八九十]+)、', operative[:cost.start()]))
    if [m[1] for m in numbered] != ['一', '二', '三', '四'] or numbered[0].start() != 0:
        return None
    clauses = [operative[m.end():numbered[i+1].start() if i < 3 else cost.start()]
               for i, m in enumerate(numbered)]
    debtor, creditor = re.escape(opponents), re.escape(client)
    amount = r'\d+(?:\.\d{1,2})?'
    due = r'本判决发生法律效力之日起[一二三四五六七八九十百\d]+日内'
    first_clause = re.fullmatch(r'被告' + debtor + r'于(?P<due>' + due + r')向原告' + creditor
        + r'偿还拖欠本金(?P<principal>' + amount + r')元、利息' + amount
        + r'元、罚息' + amount + r'元、复利' + amount + r'元\((?P<formula>[^()]+)\)[;；。]?', clauses[0])
    second = re.fullmatch(r'被告' + debtor + r'于(?P<due>' + due + r')向原告' + creditor
        + r'支付律师费损失(?P<fee>' + amount + r')元[;；。]', clauses[1])
    third = re.fullmatch(r'原告' + creditor + r'对被告' + debtor
        + r'提供抵押的位于(?P<property>[^;；。]{3,160})的房地产在上述第一、二项判项确定的债权范围内享有优先受偿权[;；。]', clauses[2])
    fourth = re.fullmatch(r'驳回原告' + creditor + r'的其他诉讼请求。'
        + r'被告如果未按本判决指定的期间履行给付金钱义务的,应当依照[^。]{1,120}规定,加倍支付迟延履行期间的债务利息。', clauses[3])
    if not all((first_clause, second, third, fourth)) or first_clause['due'] != second['due']:
        return None
    # The complete interest formula is intentionally referenced, not rewritten
    # as a single interest rate or an asserted final payable total.
    if re.search(r'如|若|但|除非|抵扣|扣减|不承担|仅限', first_clause['formula']):
        return None
    if any(n not in ep for n in range(execution['start_page'], execution['end_page'] + 1)):
        return None
    e = ''.join(body(ep[n]) for n in range(execution['start_page'], execution['end_page'] + 1))
    header = re.match(r'(?P<court>[\u3400-\u9fff]{2,65}人民法院)(?:执行)?结案通知书'
                      + re.escape(identity['执行案号']), e)
    if not header or not re.fullmatch(r'\(\d{4}\)[\u3400-\u9fff\d]+执\d+号', identity['执行案号']):
        return None
    if not re.search(r'关于' + creditor + r'诉' + debtor + re.escape(identity['案由'])
                     + r'一案,本院作出的' + re.escape(number) + r'民事判决书已于\d{4}年\d{1,2}月\d{1,2}日发生法律效力。', e):
        return None
    registration = re.search(r'本院于(?P<date>\d{4}年\d{1,2}月\d{1,2}日)立案执行[,。]', e)
    auction = re.search(r'本院' + re.escape(identity['执行案号']) + r'案件已经拍卖了被执行人名下'
                        + re.escape(third['property']) + r'[,。]', e)
    # Wording/address differences are not silently normalized. Known literal
    # property reuse is required before reporting that this collateral sold.
    ending = re.search(r'拍卖款足以覆盖本案债务。本案已执行完毕。特此通知。$', e)
    if (not registration or not auction or not ending
            or re.search(r'撤销(?:本|上述|该)|通知书作废|尚未执行完毕|另案|示例文本|参考模板|(?:本件|本文书)[^。]{0,12}(?:示例|模板)', e)):
        return None
    try:
        date(*map(int, re.findall(r'\d+', registration['date'])))
    except ValueError:
        return None
    if ('偿还拖欠本金' + first_clause['principal'] + '元' not in e
            or '支付律师费损失' + second['fee'] + '元' not in e):
        return None
    procedure = '法院适用简易程序公开开庭审理。' if '本院受理后,依法适用简易程序公开开庭进行了审理。' in heading else ''
    period = first_clause['due'].replace('本判决', '判决')
    summary = (procedure + f'判决被告于{period}向委托人偿还本金{first_clause["principal"]}元'
               + f'及利息、罚息、复利，并支付律师费损失{second["fee"]}元；'
               + '委托人对判决所列抵押房产在前述债权范围内优先受偿，其他诉讼请求被驳回。'
               + '利息计算、迟延履行及案件费用分担详见判决。'
               + f'执行结案通知书记载：{registration["date"]}立案执行，抵押房产已拍卖，'
               + '拍卖款足以覆盖本案债务，本案已执行完毕。')
    if len(summary) > 320:
        return None
    return summary


def current_support(ref, fields):
    if not isinstance(ref, dict):
        return None
    original = ref
    if ref.get('method') == 'derived_form_draft':
        if ref.get('input_field') != FIELD or ref.get('input_value') != fields.get(FIELD):
            return None
        refs = (fields.get('_provenance') or {}).get(FIELD) or []
        refs = [refs] if isinstance(refs, dict) else refs
        original = next((r for r in refs if isinstance(r, dict) and r.get('method') == ref.get('input_method')
                         and all(r.get(k) == ref.get(k) for k in ('documents', 'source_path', 'page', 'quote'))), None)
    if not original or original.get('value') != fields.get(FIELD) or original.get('binding') != DERIVATION:
        return None
    documents = original.get('documents')
    if summarize(documents, fields) != original['value']:
        return None
    sources = [{'source_path': d['source_path'], **p} for d in documents for p in d['pages']]
    if not sources or any(original.get(k) != sources[0].get(k) for k in ('source_path', 'page', 'quote')):
        return None
    return sources[1:]


def reference_supported(field, value, ref, fields):
    return field == FIELD and value == fields.get(FIELD) and current_support(ref, fields) is not None


def recall_report(fields, provenance, conflicts, *, page_cache, allowed_sources, document_units=(),
                  manual_fields=(), method='visual_agent_local_evidence', fact_review):
    if method not in ('local_agent', 'visual_agent_local_evidence'):
        raise ValueError('unsupported_local_evidence_method')
    context = {**fields, '_field_conflicts': conflicts}
    if not _same_identities(context):
        return 0
    for key in ALIASES:
        refs = provenance.get(key) or []; refs = [refs] if isinstance(refs, dict) else refs
        if key in manual_fields or any(isinstance(r, dict) and r.get('method') == 'human' for r in refs):
            return 0
        if key != FIELD and fields.get(key):
            return 0
        if fields.get(key) and compact(fields[key]) != '本案已执行完毕。':
            return 0  # Preserve an already accepted substantive or human summary.
    documents = []
    for unit in document_units:
        kind = getattr(unit, 'doc_type', None)
        confidence = getattr(unit, 'confidence', None)
        start, end, path = (getattr(unit, k, None) for k in ('start_page', 'end_page', 'source_path'))
        if (kind not in ('judgment', 'execution') or type(confidence) not in (float, int)
                or not math.isfinite(confidence) or confidence < .75
                or type(start) is not int or type(end) is not int or not 0 <= start <= end
                or end - start > 50 or not isinstance(path, str) or not path):
            continue
        start, end = start + 1, end + 1
        if kind == 'execution' and unit.title not in ('结案通知书', '执行结案通知书'):
            continue
        pages = [{'page': n, 'quote': page_cache[(path, n)]} for n in range(start, end + 1)
                 if (path, n) in allowed_sources and (path, n) in page_cache]
        documents.append({'kind': kind, 'source_path': path, 'start_page': start, 'end_page': end, 'pages': pages})
    found = []
    for j in (d for d in documents if d['kind'] == 'judgment'):
        for e in (d for d in documents if d['kind'] == 'execution'):
            if value := summarize([j, e], context):
                found.append((value, [j, e]))
    if not found:
        return 0
    if len({value for value, _ in found}) != 1:
        sources = [{'value': v, 'source_path': docs[1]['source_path'], **docs[1]['pages'][0]}
                   for v, docs in found]
        conflicts.append({'field': FIELD, 'values': list(dict.fromkeys(value for value, _ in found)),
                          'sources': sources, 'source': sources[-1],
                          'reason_code': 'court_report_sources_conflict'})
        return 0
    value, documents = found[0]
    primary = documents[0]['pages'][0]
    ref = {'field': FIELD, 'value': value, 'method': method, 'derivation': DERIVATION, 'binding': DERIVATION,
           'documents': deepcopy(documents), 'source_path': documents[0]['source_path'], **primary,
           'candidate_origin': 'local_cached_court_report'}
    fields[FIELD] = value
    old = provenance.get(FIELD) or []; old = [old] if isinstance(old, dict) else old
    provenance[FIELD] = old + [ref]
    # Retain previous rejected candidates and their exact reasons in the audit.
    return 1
