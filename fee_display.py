"""Bounded form presentation of evidenced fees; full accepted terms stay intact."""
from copy import deepcopy
import re
from fact_evidence import validate_fact
from document_title_review import title_evidence

FIELD = '收费标准'
KEY = '_contract_fee_display'


def compact(text):
    return re.sub(r'\s+', '', str(text or ''))


def summarize(value):
    # Recognize complete structures, not isolated numbers. Unknown adjustments,
    # ceilings, deductions and alternative choices must stay in normal review.
    amount = r'(?P<amount>\d{1,8}(?:\.\d{1,2})?)(?P<unit>万元|元)'
    stage = r'(?P<stage>一审|二审|再审)?'
    payment = r'(?:基础费于合同(?:订立|签订)后[一二三四五六七八九十百\d]{1,6}日内支付[，,]风险费于实际回款后结算[。]?)?'
    match = re.fullmatch(stage + r'基础律师费' + amount + r'[；;]另按实际(?:收回款项|回款)(?:的)?(?P<rate>\d{1,2}(?:\.\d{1,2})?)%收取风险代理费[。]' + payment, compact(value))
    if not match:
        match = re.fullmatch(stage + r'基础(?:代理费|律师费)' + amount + r'[，,]按实际回款金额另收(?P<rate>\d{1,2}(?:\.\d{1,2})?)%[。]', compact(value))
    if not match or not 0 < float(match['rate']) <= 100 or float(match['amount']) <= 0: return None
    short = f"基础{match['amount']}{match['unit']}\n回款{match['rate']}%详合同"
    if any(sum(.5 if ord(c) < 128 else 1 for c in line) > 8 for line in short.splitlines()): return None
    note = (match['stage'] or '') + '收费条款及付款、结算条件详卷内委托代理合同。'
    return {'value': short, 'note': note}


def _refs(fields):
    refs = fields.get('_provenance', {}).get(FIELD, [])
    return [refs] if isinstance(refs, dict) else refs


def current(fields):
    if not isinstance(fields, dict): return None
    source = fields.get(KEY)
    if not isinstance(source, dict) or source.get('version') != 1: return None
    if source.get('terms') != fields.get(FIELD) or source.get('client') != fields.get('委托人'): return None
    if any(r.get('field') in (FIELD, '委托人') and not r.get('resolved') for r in fields.get('_field_conflicts', [])): return None
    refs = _refs(fields)
    if any(r.get('method') == 'human' and r.get('value') == fields.get(FIELD) for r in refs if isinstance(r, dict)): return None
    if source.get('reference') not in refs: return None
    ref = source['reference']; page = source.get('page_text', '')
    if ref.get('method') not in ('local_agent', 'visual_agent_local_evidence'): return None
    title = title_evidence(source.get('title_page', ''))
    if not title or not title['verified'] or title['doc_type'] != 'contract' or title['title'] not in ('委托代理合同', '委托合同', '法律服务合同'): return None
    if not validate_fact(FIELD, source['terms'], ref.get('quote'), page): return None
    if not validate_fact('委托人', source['client'], source.get('title_page'), source.get('title_page')): return None
    if 'p0-b0-r9-c0' in (fields.get('_preview_custom_values', {}).get('立案审批表') or {}): return None
    return summarize(source['terms'])


def collect(fields, provenance, conflicts, *, page_cache, allowed_sources, document_units, manual_fields):
    fields.pop(KEY, None)
    if FIELD in manual_fields or not summarize(fields.get(FIELD)): return
    context = {**fields, '_provenance': provenance, '_field_conflicts': conflicts}
    refs = _refs(context)
    found = []
    for unit in document_units:
        if unit.doc_type != 'contract' or unit.confidence < .85: continue
        start = (unit.source_path, unit.start_page + 1)
        if start not in allowed_sources or not page_cache.get(start): continue
        for ref in refs:
            if not isinstance(ref, dict) or ref.get('value') != fields.get(FIELD): continue
            key = (ref.get('source_path'), ref.get('page'))
            if (key not in allowed_sources or key not in page_cache or key[0] != unit.source_path
                    or type(key[1]) is not int or not unit.start_page + 1 <= key[1] <= unit.end_page + 1): continue
            source = {'version': 1, 'terms': fields[FIELD], 'client': fields.get('委托人'),
                      'reference': deepcopy(ref), 'page_text': page_cache[key], 'title_page': page_cache[start]}
            if current({**context, KEY: source}): found.append(source)
    # Different underlying terms were handled by the field-conflict gate. Keep
    # this presentation bound to one current reference, never invent new facts.
    if found: fields[KEY] = found[0]
