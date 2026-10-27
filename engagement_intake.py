"""Bounded intake defaults for an explicitly linked batch risk engagement.

No fee-rate guessing or signature finding. Complete terms stay in provenance;
the small form cell states only the common base-fee rule and points to them.
"""
from copy import deepcopy
from datetime import date
import re
import unicodedata
from fact_evidence import validate_fact
from pleading_sources import unpack, references
from pleading_parties import roster, digest

KEY = '_engagement_intake_sources'
BINDING = 'batch_engagement_intake'
FIELDS = ('收费标准', '立案审批日期')


def compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text or '')))


def evaluate(source, client):
    if not isinstance(source, dict): return None
    pages = source.get('pages')
    if (not isinstance(pages, list) or not 1 <= len(pages) <= 24
        or any(not isinstance(p,dict) or not isinstance(p.get('quote'),str)
               or not 0 < len(p['quote']) <= 18000 or type(p.get('page')) is not int
               or p['page'] < 1 or not isinstance(p.get('source_path'),str) or not p['source_path'] for p in pages)):
        return None
    if any(p['source_path'] != pages[0]['source_path'] or p['page'] != pages[0]['page']+i for i,p in enumerate(pages)): return None
    head = [compact(s) for s in pages[0]['quote'].splitlines() if compact(s)]
    title = '委托代理合同(适用风险代理)'
    for index in range(min(3,len(head)-1)):
        if head[index:index+2]==['委托代理合同','(适用风险代理)']:
            head[index:index+2]=[title]
            break
    if title not in head[:3]: return None
    prefix = head[:head.index(title)]
    if any(not re.fullmatch(r'[A-Z]{2,10}[-_]?\d{6,24}', p) for p in prefix): return None
    if not client or not validate_fact('委托人',client,pages[0]['quote'],pages[0]['quote']): return None
    documents = unpack(source.get('pleadings'))
    if not documents or any(not roster(d) for d in documents): return None
    subjects = []
    for document in documents:
        text = compact('\n'.join(p['quote'] for p in document['pages']))
        found = set(re.findall(r'判令[一二三四五六七八九十\d]*被告在继承([^，,。；;()]{2,30})遗产的范围内',text))
        if len(found) != 1: return None
        subjects.extend(found)
    if len(set(subjects)) != 1: return None
    text = compact('\n'.join(p['quote'] for p in pages))
    # Explicit party/case link, not a name appearing somewhere in an attachment.
    if not re.search(r'甲方与'+re.escape(subjects[0])+r'等\d{1,3}户',compact('\n'.join(p['quote'] for p in pages[:2]))): return None
    if re.search(r'合同草稿|参考模板|填写示例|本合同已解除|本合同已作废',text): return None
    result = {}
    section = re.search(r'第四条律师代理的方式、费用、支付条件和方式(.*?)第五条',text)
    if section:
        terms = section[1]
        if (re.search(r'本合同代理方式为风险代理[，,]并按下列第1项执行[:：]1[.、]甲方不支付基础代理费',terms)
            and '甲方按下列第4点向乙方计付律师代理费用' in terms
            and re.search(r'\(4\)其他付款条件[:：]\(1\)无基础费用[。;；]',terms)):
            result['收费标准'] = {'value':'无基础费\n风险费依合同','terms':terms,
                                  'page': next(p['page'] for p in pages if '第四条' in compact(p['quote']))}
    pattern = r'(\d{4})年(\d{1,2})月(\d{1,2})日'
    choices = []
    for page in pages:
        content = compact(page['quote'])
        if '合同各方签章' not in content: continue
        signature = content.split('合同各方签章',1)[1].split('附件',1)[0]
        if re.search(r'拟签|预计|未签|待签|日期待定',signature): continue
        parts = re.split(r'乙方\(盖章\)',signature)
        if len(parts)!=2 or '甲方(盖章)' not in parts[0]: continue
        dates=[re.findall(pattern,p) for p in parts]
        if any(len(d)!=1 for d in dates) or dates[0]!=dates[1]: continue
        try: day=date(*map(int,dates[0][0]))
        except ValueError: continue
        choices.append((f'{day.year}年{day.month}月{day.day}日',page['page']))
    if choices and len({v for v,_ in choices})==1:
        result['立案审批日期']={'value':choices[0][0],'page':choices[0][1],
            'note':'按委托合同双方签章栏所载一致日期默认，不证明签署、审批或法院立案。'}
    return result


def current_support(ref, fields):
    if not isinstance(ref,dict) or ref.get('binding')!=BINDING: return None
    field=ref.get('input_field') if ref.get('method')=='derived_form_draft' else ref.get('field')
    source=fields.get(KEY)
    if field not in FIELDS or not isinstance(source,dict) or ref.get('bundle_digest')!=digest(source): return None
    if any(c.get('field') in ('委托人',field) and not c.get('resolved') for c in fields.get('_field_conflicts',[])): return None
    candidate=(evaluate(source,fields.get('委托人')) or {}).get(field)
    if not candidate or fields.get(field)!=candidate['value']: return None
    if ref.get('value')!=candidate['value'] and ref.get('input_value')!=candidate['value']: return None
    page=next((p for p in source['pages'] if p['page']==candidate['page']),None)
    if not page or any(ref.get(k)!=page[k] for k in ('source_path','page','quote')): return None
    return deepcopy(source['pages'])+references(source['pleadings'])


def scope_supported(fields, manifest):
    import os
    norm=lambda p:os.path.normcase(os.path.abspath(p))
    source=fields.get(KEY) or {}
    return source.get('scope') == {norm(r['path']):r['pages'] for r in manifest if r.get('path')}


def recall(fields, provenance, conflicts, *, page_cache, allowed_sources, document_units, manual_fields, method):
    documents=unpack(fields.get('_pleading_parties_source'))
    if not documents or any(c.get('field')=='委托人' and not c.get('resolved') for c in conflicts): return 0
    units=[u for u in document_units if u.doc_type=='contract']
    # Competing engagements need an explicit version decision.
    if len(units)!=1:return 0
    u=units[0]
    if not 0<=u.start_page<=u.end_page<u.start_page+24:return 0
    keys=[(u.source_path,n+1) for n in range(u.start_page,u.end_page+1)]
    if any(k not in allowed_sources or not page_cache.get(k) for k in keys):return 0
    import os
    scope={}
    for path,n in allowed_sources:
        key=os.path.normcase(os.path.abspath(path));scope[key]=max(scope.get(key,0),n)
    source={'pages':[{'source_path':p,'page':n,'quote':page_cache[(p,n)]} for p,n in keys],
            'pleadings':deepcopy(fields['_pleading_parties_source']),'scope':scope}
    candidates=evaluate(source,fields.get('委托人')) or {}
    if not candidates:return 0
    fields[KEY]=source;count=0
    for field,candidate in candidates.items():
        refs=provenance.get(field) or [];refs=[refs] if isinstance(refs,dict) else refs
        if (field in manual_fields or fields.get(field) or any(r.get('method')=='human' for r in refs)
            or any(c.get('field')==field and not c.get('resolved') for c in conflicts)):continue
        page=next(p for p in source['pages'] if p['page']==candidate['page'])
        ref={**deepcopy(page),'field':field,'value':candidate['value'],'method':method,
             'binding':BINDING,'derivation':BINDING,'bundle_digest':digest(source),
             **{k:v for k,v in candidate.items() if k not in ('page','value')}}
        fields[field]=candidate['value'];provenance[field]=refs+[ref];count+=1
    return count
