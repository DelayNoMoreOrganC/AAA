"""Read a closed first-instance roster linked to the represented court party.

Uses already-read source pages, not document titles alone. An address is the
document's recorded address; no claim is made that it is a current service address.
"""
from copy import deepcopy
import re

from source_party_evidence import current_client_party_support, _name, _rows
from source_court_evidence import extract_court_header_candidate

FIELDS=('对方当事人','地址','委托人电话','承办律师','案由')
DERIVATION='court_party_details'
_ROLE=re.compile(r'(?:^|[。；;\r\n])\s*(?P<role>原告|被告|第三人)\s*[:：]\s*')
_RISK=re.compile(r'另案|参考案例|引用案例|拟|假设|范本|模板|原告反诉|被告反诉|反诉原告|反诉被告')


def candidates(text,client,number):
    if not isinstance(text,str) or not 0<len(text)<=18000 or _RISK.search(text):return []
    heading=extract_court_header_candidate(text,number)
    if (not heading or not re.search(r'(?:民事|行政)(?:判决书|裁定书|调解书)',_name(heading['quote']))
            or not re.search(r'(?:民|行)初\d+号$',_name(number))):return []
    body=text[text.index(heading['quote'])+len(heading['quote']):]
    # A list ending at the page edge may continue with more parties. Require
    # the court's case narrative before treating the opposing roster as closed.
    stop=re.search(r'(?:^|\n)\s*(?:原告(?=[^:：]{2,150}诉被告)|本院|本案(?:现|于|经|由)|经审理)',body)
    if not stop:return []
    body=body[:stop.start()]
    matches=list(_ROLE.finditer(body))
    if not matches or body[:matches[0].start()].strip():return []
    roster=[]
    for index,match in enumerate(matches):
        block=body[match.end():matches[index+1].start() if index+1<len(matches) else len(body)]
        split=re.search(r'[，,。；;]',block)
        if not split:return []
        name=_name(block[:split.start()])
        if (not 2<=len(name)<=120 or re.search(r'[:：、/]|等人|及|以及|原告|被告|委托',name)):
            return []
        roster.append((match['role'],name,block))
    represented=[row for row in roster if row[1]==_name(client)]
    if len(represented)!=1 or represented[0][0] not in ('原告','被告'):return []
    role,_,block=represented[0]
    opposite='被告' if role=='原告' else '原告'
    names=[name for current_role,name,_ in roster if current_role==opposite]
    values={}
    if names and len(names)==len(set(names)) and not any(name==_name(client) for name in names):
        values['对方当事人']='、'.join(names)
    own=re.split(r'法定代表人|负责人|委托(?:诉讼)?代理人|代理律师',block,maxsplit=1)[0]
    address=re.search(r'(?:住所地|住所|地址)[:：]?\s*([^。;；]+)',own)
    if address:
        value=re.split(r'[,，]?(?:统一社会信用代码|组织机构代码|身份证(?:号|号码)|联系电话|电话)\s*[:：]?',address[1],maxsplit=1)[0]
        value=_name(value).strip('，,')
        if value and len(value)<=200 and not re.search(r'曾住|原住|旧址|暂住|待核|不详|变更|迁至',value):values['地址']=value
    phone=re.search(r'(?:联系电话|电话)[:：]\s*([0-9+()（）\-\s]{7,25})(?=[。;；,，]|$)',own)
    if phone and 7<=len(re.sub(r'\D','',phone[1]))<=18:values['委托人电话']=_name(phone[1])
    # Named counsel in the represented party's closed roster, not every lawyer
    # mentioned by the judgment. This does not prove each one attended court.
    lawyer_rows=re.findall(r'委托(?:诉讼)?代理人[:：]\s*([^，,。；;\n]{2,20})[，,]\s*([^。；;]{2,100}律师事务所)律师(?:[。；;]|$)',block)
    lawyer_labels=re.findall(r'委托(?:诉讼)?代理人[:：]',block)
    if lawyer_rows and len(lawyer_rows)==len(lawyer_labels):
        values['承办律师']='、'.join(dict.fromkeys(_name(name) for name,firm in lawyer_rows))
    if role=='原告' and len(names)==1:
        caption=re.search(r'原告'+re.escape(_name(client))+r'诉被告'+re.escape(names[0])+r'([^。；：:]{2,24}纠纷)一案',_name(text))
        if caption:values['案由']=caption[1]
    return [{'field':field,'value':value,'quote':text,'subject':client,'case_number':number,
             'role':role,'binding':DERIVATION,'derivation':DERIVATION} for field,value in values.items()]


def current_detail_support(ref,fields):
    if not isinstance(ref,dict) or ref.get('binding')!=DERIVATION:return None
    field=ref.get('input_field') if ref.get('method')=='derived_form_draft' else ref.get('field')
    if field not in FIELDS:return None
    if ref.get('method')=='derived_form_draft':
        for original in _rows(fields.get('_provenance'),field):
            if (isinstance(original,dict) and original.get('value')==ref.get('input_value')==fields.get(field)
                    and original.get('method')==ref.get('input_method')
                    and all(original.get(key)==ref.get(key) for key in
                            ('source_path','page','quote','subject','case_number','role','supporting_sources','binding','derivation'))):
                return current_detail_support(original,fields)
        return None
    if ref.get('method') not in ('local_agent','visual_agent_local_evidence'):return None
    if any(isinstance(row,dict) and row.get('field')==field and not row.get('resolved')
           for row in fields.get('_field_conflicts') or []):return None
    if fields.get(field) and fields[field]!=ref.get('value'):return None
    if not any(row['field']==field and row['value']==ref.get('value') and row['role']==ref.get('role')
               for row in candidates(ref.get('quote'),ref.get('subject'),ref.get('case_number'))):return None
    supports=ref.get('supporting_sources')
    if not isinstance(supports,list) or len(supports)!=1:return None
    party=supports[0]
    if (not isinstance(party,dict) or party.get('field')!='当事人'
            or party.get('source_path')!=ref.get('source_path') or party.get('page')!=ref.get('page')
            or party.get('subject')!=ref.get('subject') or party.get('case_number')!=ref.get('case_number')
            or party.get('role')!=ref.get('role')):return None
    current=next((row for row in _rows(fields.get('_provenance'),'当事人') if isinstance(row,dict)
                  and all(row.get(key)==value for key,value in party.items() if key!='field')),None)
    if current is None:return None
    foundations=current_client_party_support(current,fields)
    return [deepcopy(party),*foundations] if foundations is not None else None


def reference_supported(field,value,ref,fields):
    return (field in FIELDS and ref.get('field')==field and ref.get('value')==value
            and current_detail_support(ref,fields) is not None)


def recall_details(fields,provenance,conflicts,*,page_cache,allowed_sources,manual_fields,fact_review,method):
    context={**fields,'_provenance':provenance,'_field_conflicts':conflicts}
    eligible={field for field in FIELDS if not fields.get(field) and field not in manual_fields
              and not any(isinstance(row,dict) and row.get('method')=='human' for row in _rows(provenance,field))
              and not any(isinstance(row,dict) and row.get('field')==field and not row.get('resolved') for row in conflicts)}
    pending={field:[] for field in eligible}
    for party in _rows(provenance,'当事人'):
        if not isinstance(party,dict) or current_client_party_support(party,context) is None:continue
        source=(party.get('source_path'),party.get('page'))
        text=page_cache.get(source) if source in allowed_sources else None
        if not text:continue
        for candidate in candidates(text,fields.get('委托人'),fields.get('案号')):
            field=candidate['field']
            if field not in eligible:continue
            ref={**candidate,'source_path':source[0],'page':source[1],'method':method,
                 'candidate_origin':'local_cached_court_details','supporting_sources':[{**deepcopy(party),'field':'当事人'}]}
            if reference_supported(field,ref['value'],ref,context):pending[field].append(ref)
    count=0
    for field,refs in pending.items():
        values=list(dict.fromkeys(row['value'] for row in refs))
        if len(values)>1:
            conflicts.append({'field':field,'values':values,'sources':refs,'reason_code':'court_details_conflict'})
            continue
        if not refs:continue
        fields[field]=values[0];provenance[field]=_rows(provenance,field)+refs;count+=1
        for entry in fact_review:
            if entry.get('field')==field and any(entry.get('source_path')==ref['source_path'] and entry.get('page')==ref['page'] for ref in refs):
                entry['resolution']='field_supported_by_cached_source'
    return count
