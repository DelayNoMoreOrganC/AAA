"""Read a labelled power-of-attorney roster without inferring signatures or fees.

Pure, case-scoped text processing. The caller owns source authorization/hashes.
Unknown formats remain available to the model/review path, never guessed here.
"""
from __future__ import annotations

from copy import deepcopy
import re
import unicodedata

FIELDS = ('委托人', '承办律师', '律师事务所')


def _compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))


def poa_candidates(page_text):
    if not isinstance(page_text, str) or not 0 < len(page_text) <= 18000:
        return []
    page = _compact(page_text)
    if not re.match(r'^授权委托书(?:\((?:民事|行政|诉讼)\))?', page):
        return []
    # A title alone is not an engagement. Require an operative declaration and
    # a closed roster. Do not learn parties from examples, reports or revocations.
    declaration = re.search(r'(?:现|兹|特)?委托上列受委托人[^。；;]{0,240}(?:作为|担任)我方诉讼代理人[。；;]', page)
    if not declaration or re.search(r'示例|范本|模板|另案|引用|转述|拟委托|尚未委托|未予委托|冒用|撤销(?:本|该|上述)?(?:授权|委托)|撤回(?:本|该)?授权|授权(?:已失效|无效)', page):
        return []
    header = page[:declaration.start()]
    client = re.search(r'(?<!受)委托人[:：](?P<name>[^:：,，。；;、()]{2,120}?)(?=受委托人姓名[:：])', header)
    if not client or len(re.findall(r'(?<!受)委托人[:：]', header)) != 1:
        return []
    name = client['name'].strip('_')
    if not name or re.search(r'拟|计划|并非|不是|尚未|法定代表人|住所|地址|电话', name):
        return []
    roster = header[client.end():]
    starts = list(re.finditer(r'(?:受委托人)?姓名[:：]', roster))
    if not starts or starts[0].start() != 0 or len(starts) > 6:
        return []
    lawyers, firms = [], []
    for index, start in enumerate(starts):
        stop = starts[index+1].start() if index+1 < len(starts) else len(roster)
        block = roster[start.end():stop]
        record = re.match(r'(?P<name>[\u3400-\u9fffA-Za-z·.]{2,30})工作单位[:：]_?(?P<firm>[^:：,，。；;_]{2,70}?律师事务所(?:分所)?)职务[:：]律师(?=电话[:：]|代理权限[:：]|$)', block)
        if not record or re.search(r'助理|实习|法务|拟|待定|未指定|不是', record['name']):
            return []
        # A non-lawyer or unknown block makes the roster incomplete. Never
        # silently discard that block and present the remainder as all counsel.
        tail = block[record.end():]
        if not re.fullmatch(r'(?:(?:电话[:：][0-9+()\-]{5,25})|(?:代理权限[:：](?:特别授权|一般授权)))*', tail):
            return []
        lawyers.append(record['name']);firms.append(record['firm'])
    lawyers = list(dict.fromkeys(lawyers))
    firms = list(dict.fromkeys(firms))
    # Keep the original page as evidence, including line wraps and qualification
    # statements. Joined names are an explicit roster projection, not a quote.
    values = {'委托人': name, '承办律师': '、'.join(lawyers)}
    if len(firms) == 1:values['律师事务所'] = firms[0]
    return [{'field':field,'value':value,'quote':page_text,'subject':name,
             'derivation':'labelled_poa_roster'} for field,value in values.items()]


def poa_fact_supported(field, value, quote, page_text):
    if field not in FIELDS or _compact(quote) != _compact(page_text):
        return False
    return any(row['field']==field and _compact(row['value'])==_compact(value)
               for row in poa_candidates(page_text))


def poa_reference_supported(field, value, ref, fields):
    """Check the roster projection against the currently represented client."""
    if not isinstance(ref,dict) or ref.get('derivation')!='labelled_poa_roster':return False
    quote=ref.get('quote')
    if not isinstance(quote,str) or not poa_fact_supported(field,value,quote,quote):return False
    clients={_compact(fields[key]) for key in ('委托人','委托人名称','委托方') if _compact(fields.get(key))}
    if clients!={_compact(ref.get('subject'))}:return False
    return not any(isinstance(row,dict) and row.get('field') in ('委托人','委托人名称','委托方',field)
                   and row.get('resolved') is not True for row in fields.get('_field_conflicts') or [])


def recall_poa_facts(fields, provenance, conflicts, *, page_cache, allowed_sources,
                     manual_fields=(), method='visual_agent_local_evidence', fact_review):
    """Fill absent fields only, with one unique client and a complete roster."""
    if method not in ('local_agent','visual_agent_local_evidence'):
        raise ValueError('unsupported_local_evidence_method')
    blocked = set(manual_fields)
    blocked.update(row.get('field') for row in conflicts if row.get('resolved') is not True)
    for field in FIELDS:
        refs=provenance.get(field,[]);refs=[refs] if isinstance(refs,dict) else refs
        if any(isinstance(row,dict) and row.get('method')=='human' for row in refs):blocked.add(field)
    if '委托人' in blocked and not _compact(fields.get('委托人')):
        return 0
    candidates=[]
    for source in sorted(set(page_cache)&set(allowed_sources)):
        path,number=source
        if not isinstance(path,str) or not path or type(number) is not int or number<1:continue
        for row in poa_candidates(page_cache[source]):
            candidates.append({**row,'source_path':path,'page':number,'method':method,
                               'candidate_origin':'local_cached_poa_roster'})
    clients={_compact(row['subject']) for row in candidates}
    for key in ('委托人','委托人名称','委托方'):
        if _compact(fields.get(key)):clients.add(_compact(fields[key]))
    if len(clients)!=1 or any(row.get('field') in ('委托人','委托人名称','委托方') and row.get('resolved') is not True for row in conflicts):
        if candidates:
            fact_review.append({'field':'委托人','reason_code':'local_evidence_rejected',
                'verification_code':'poa_client_conflict','source_path':candidates[0]['source_path'],
                'page':candidates[0]['page']})
        return 0
    count=0
    for field in FIELDS:
        if field in blocked or _compact(fields.get(field)):continue
        refs=[row for row in candidates if row['field']==field]
        values=list(dict.fromkeys(row['value'] for row in refs))
        if len(values)>1:
            conflicts.append({'field':field,'values':values,'sources':deepcopy(refs),
                              'source':deepcopy(refs[-1]),'reason_code':'poa_roster_conflict'})
            continue
        if not refs:continue
        fields[field]=values[0]
        old=provenance.get(field,[]);old=[old] if isinstance(old,dict) else old
        provenance[field]=old+[{k:v for k,v in row.items() if k!='field'} for row in refs]
        count+=1
        for review in fact_review:
            if review.get('field')==field and any(review.get('source_path')==row['source_path'] and review.get('page')==row['page'] for row in refs):
                review['resolution']='field_supported_by_cached_source'
    return count
