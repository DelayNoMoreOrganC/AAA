"""Law-office convention: contract date defaults only the generated intake form.

No signature, approval, court filing or other form's receipt date is inferred.
Only complete, already-read engagement documents in the current case are used.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
import os
import re
import unicodedata

from document_title_review import title_evidence
from fact_evidence import validate_fact

FIELD = '立案审批日期'
BINDING = 'intake_contract_date_default'
KEY = '_intake_contract_date_source'
NOTE = '按合同载明签订日默认，仅用于立案审批表，不证明已签署、已审批或法院立案。'
IDENTITY = ('委托人', '对方当事人', '案由')
# PDF text extraction can wrap inside a label. Match only these known labels
# across whitespace, leaving the original page and evidence offsets untouched.
LABEL = '(?:' + '|'.join(r'\s*'.join(map(re.escape, label)) for label in (
    '合同载明签订日期', '合同载明签订时间', '合同签订日期', '合同签订时间',
    '合同签署日期', '签订日期', '签约日期')) + ')'
DATE = r'(?P<y>\d{4})\s*(?:年|[-/.])\s*(?P<m>\d{1,2})\s*(?:月|[-/.])\s*(?P<d>\d{1,2})\s*日?'
RISK = re.compile(r'拟签|预计签|计划签|尚未签|未签署|未签订|待签署|待签订|签订日期待定|签约日期待定|参考模板|填写示例|补充协议|变更协议|解除协议|合同草稿|签订日期有误')


def compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def dates(document, identity):
    pages = document.get('pages') if isinstance(document, dict) else None
    if not isinstance(pages, list) or not 1 <= len(pages) <= 8: return None
    if any(not isinstance(p, dict) or not isinstance(p.get('source_path'), str) or not p['source_path']
           or type(p.get('page')) is not int or p['page'] < 1 or not isinstance(p.get('quote'), str)
           or not 0 < len(p['quote']) <= 18000 for p in pages): return None
    if any(p['source_path'] != pages[0]['source_path'] or p['page'] != pages[0]['page'] + i for i,p in enumerate(pages)): return None
    title = title_evidence(pages[0]['quote'])
    if not title or not title['verified'] or title['title'] not in ('委托代理合同','委托合同','法律服务合同'): return None
    text = '\n'.join(p['quote'] for p in pages)
    if RISK.search(compact(text)): return None
    client, opponent, matter = (identity.get(k) for k in IDENTITY)
    if not client or not opponent or not matter: return None
    if not validate_fact('委托人',client,pages[0]['quote'],pages[0]['quote']): return None
    # A second engagement for the same client is not automatically this case.
    if compact(matter) not in compact(text): return None
    if not any(compact(name) in compact(text) for name in re.split(r'[、，,；;]',opponent) if name.strip()): return None
    found=[]
    for page in pages:
        raw=unicodedata.normalize('NFKC',page['quote'])
        candidates=list(re.finditer(r'(?<![\w])'+LABEL+r'\s*[:：]\s*'+DATE,raw))
        # Chinese labels may follow a sentence or line, never 预计/生效/借款合同.
        labels=list(re.finditer(LABEL+r'\s*[:：]',raw))
        if len(candidates)!=len(labels): return None
        # A line break after a qualifier must not turn a proposed date or a
        # referenced loan contract date into this engagement's signing date.
        if any(re.search(r'(?:预计|计划|拟|借款|贷款|保证|担保|抵押|质押|生效)$',
                         compact(raw[:m.start()])) for m in candidates): return None
        candidates += list(re.finditer(r'(?:^|[。；;\n])\s*本合同于\s*'+DATE+r'\s*签订',raw))
        candidates += list(re.finditer(r'(?:^|[。；;\n])\s*双方于\s*'+DATE+r'\s*签订本合同',raw))
        for match in candidates:
            suffix=raw[match.end():match.end()+12]
            if suffix and not re.match(r'\s*(?:[。；;，,\n]|$)',suffix): return None
            try: parsed=date(int(match['y']),int(match['m']),int(match['d']))
            except ValueError: return None
            found.append({'value':f'{parsed.year}年{parsed.month}月{parsed.day}日',**deepcopy(page)})
    return found or None


def current_support(ref, fields):
    if not isinstance(ref,dict) or ref.get('binding')!=BINDING or ref.get('field')!=FIELD: return None
    if ref.get('method') not in ('local_agent','visual_agent_local_evidence'): return None
    source=fields.get(KEY)
    if not isinstance(source,dict) or ref.get('bundle_digest')!=digest(source): return None
    if source.get('identity')!={k:fields.get(k,'') for k in IDENTITY}: return None
    if any(r.get('field') in (*IDENTITY,FIELD) and not r.get('resolved') for r in fields.get('_field_conflicts',[])): return None
    choices=[]
    documents=source.get('documents')
    if not isinstance(documents,list) or not documents: return None
    for document in documents:
        rows=dates(document,source['identity'])
        if rows is None:return None
        choices.extend(rows)
    if {r['value'] for r in choices}!={fields.get(FIELD)} or ref.get('value')!=fields.get(FIELD):return None
    if not any(all(ref.get(k)==row[k] for k in ('value','source_path','page','quote')) for row in choices):return None
    return [deepcopy(page) for doc in documents for page in doc['pages']
            if any(page[k]!=ref.get(k) for k in ('source_path','page','quote'))]


def scope_supported(fields, manifest):
    def path(value):
        return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ''
    source = fields.get(KEY) or {}
    expected = {(path(r.get('source_path')), r.get('pages')) for r in source.get('source_scope') or []}
    actual = {(path(r.get('path')), r.get('pages')) for r in manifest or []}
    if not expected or expected != actual:
        return False
    if 'scope_certificates' in source:
        from intake_date_supplement import scope
        certified, current = scope(source['scope_certificates']), scope(manifest)
        if not certified or certified != current:
            return False
    return True


def recall(fields,provenance,conflicts,*,page_cache,allowed_sources,document_units,manual_fields=(),method='visual_agent_local_evidence'):
    for key in (FIELD,'收案日期'):
        refs=provenance.get(key) or [];refs=[refs] if isinstance(refs,dict) else refs
        if key in manual_fields or any(isinstance(r,dict) and r.get('method')=='human' for r in refs):return 0
    if fields.get('收案日期'):return 0
    previous=fields.get(FIELD)
    previous_source=deepcopy(fields.get(KEY))
    refs=provenance.get(FIELD) or [];refs=[refs] if isinstance(refs,dict) else refs
    if previous and not any(r.get('binding')==BINDING and r.get('value')==previous for r in refs):return 0
    fields.pop(KEY,None)
    if any(r.get('field') in (*IDENTITY,FIELD) and not r.get('resolved') for r in conflicts):return 0
    identity={k:fields.get(k,'') for k in IDENTITY}
    documents=[];choices=[]
    for unit in document_units:
        if unit.doc_type!='contract':continue
        if not 0<=unit.start_page<=unit.end_page<unit.start_page+8:return 0
        keys=[(unit.source_path,n+1) for n in range(unit.start_page,unit.end_page+1)]
        if any(k not in allowed_sources or not page_cache.get(k) for k in keys):return 0
        document={'pages':[{'source_path':p,'page':n,'quote':page_cache[(p,n)]} for p,n in keys]}
        rows=dates(document,identity)
        if rows is None:return 0
        documents.append(document);choices.extend(rows)
    if not choices:return 0
    values=sorted({r['value'] for r in choices})
    if len(values)>1 or previous and previous!=values[0]:
        values=sorted(set(values+([previous] if previous else [])))
        conflicts.append({'field':FIELD,'values':values,'reason_code':'engagement_dates_conflict',
                          'source':deepcopy(choices[0]),'sources':deepcopy(choices)})
        # Keep every candidate page available in the source viewer, but mark
        # these references stale/unaccepted through the unresolved binding.
        provenance[FIELD]=[{**deepcopy(row),'method':method,'field':FIELD,'binding':BINDING,
                             'derivation':BINDING} for row in choices]
        return 0
    paths={p for p,n in allowed_sources}
    scope=[{'source_path':p,'pages':max(n for path,n in allowed_sources if path==p)} for p in sorted(paths)]
    source={'identity':identity,'documents':documents,'source_scope':scope}
    fields[KEY]=source;fields[FIELD]=values[0]
    provenance[FIELD]=[{**deepcopy(choices[0]),'method':method,'field':FIELD,'binding':BINDING,
                        'derivation':BINDING,'bundle_digest':digest(source),'default_convention':NOTE}]
    return int(previous!=values[0] or previous_source!=source)


def presentation(fields):
    refs=(fields.get('_provenance') or {}).get(FIELD) or []
    refs=[refs] if isinstance(refs,dict) else refs
    if any(r.get('method')=='human' and r.get('value')==fields.get(FIELD) for r in refs):return None
    from engagement_intake import current_support as batch_support
    if any(current_support(r,fields) is not None or batch_support(r,fields) is not None for r in refs):
        return {'value':fields[FIELD]+'（按合同日期默认）','note':NOTE}
    return None
