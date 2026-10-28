"""Recall explicit contracting parties from a classified contract header.

No fees, signature, batch-case membership or completed work is inferred here.
The existing field validators and later case-link checks remain authoritative.
"""
import re
from fact_evidence import validate_fact

def header_contacts(text):
    """Read only the closed contracting-client block, never the firm's block."""
    body=re.sub(r'\s+','',str(text or ''))
    if '委托代理合同' not in body[:150] or re.search(r'合同草稿|填写示例|合同作废|未予委托',body):return {}
    rows=re.findall(r'委托方[（(]甲方[）)][:：](.+?)受托方[（(]乙方[）)][:：]',body)
    if len(rows)!=1:return {}
    block=rows[0]
    name=re.match(r'([^:：]{2,100}?)(?=住所[:：])',block)
    if not name:return {}
    result={'委托人':name[1]}
    for field,label in (('委托人电话','电话'),('委托人传真','传真')):
        matches=re.findall(label+r'[:：]_?([+\d()\-]{7,24})(?![\d+()\-])',block)
        if len(matches)==1 and 7<=len(re.sub(r'\D','',matches[0]))<=18:
            result[field]=matches[0]
    return result


def recall_contacts(fields, provenance, conflicts, *, page_cache, allowed_sources,
                    document_units, manual_fields=(), method='visual_agent_local_evidence'):
    client=fields.get('委托人')
    if not client or any(c.get('field')=='委托人' and not c.get('resolved') for c in conflicts):return 0
    candidates={key:[] for key in ('委托人电话','委托人传真')}
    for unit in document_units:
        if unit.doc_type!='contract' or unit.confidence<.85:continue
        key=(unit.source_path,unit.start_page+1);text=page_cache.get(key,'')
        if key not in allowed_sources:continue
        values=header_contacts(text)
        if values.get('委托人')!=re.sub(r'\s+','',client):continue
        for field in candidates:
            if field in values and validate_fact(field,values[field],text,text):
                candidates[field].append({'field':field,'value':values[field],'quote':text,
                    'source_path':key[0],'page':key[1],'method':method,
                    'candidate_origin':'closed_contract_client_contact'})
    count=0
    for field,refs in candidates.items():
        old=provenance.get(field) or [];old=[old] if isinstance(old,dict) else old
        if field in manual_fields or any(r.get('method')=='human' for r in old):continue
        if any(c.get('field')==field and not c.get('resolved') for c in conflicts):continue
        values=list(dict.fromkeys([r['value'] for r in refs]+([fields[field]] if fields.get(field) else [])))
        if len(values)>1:
            conflicts.append({'field':field,'values':values,'sources':old+refs,'reason_code':'client_contact_conflict'})
        elif refs and not fields.get(field):
            fields[field]=values[0];provenance[field]=old+refs;count+=1
    return count


def recall(fields, provenance, conflicts, *, page_cache, allowed_sources, document_units,
           manual_fields=(), method='visual_agent_local_evidence'):
    candidates={key:[] for key in ('委托人','律师事务所')}
    for u in document_units:
        if u.doc_type!='contract' or u.confidence<.85:continue
        key=(u.source_path,u.start_page+1)
        text=page_cache.get(key)
        if key not in allowed_sources or not isinstance(text,str):continue
        compact=re.sub(r'\s+','',text)
        if '委托代理合同' not in compact[:150] or any(x in compact for x in ('合同草稿','填写示例','合同作废','未予委托')):continue
        for field,pattern in (
            ('委托人',r'委托方[（(]甲方[）)][:：]([^:：]{2,100}?)(?=住所[:：])'),
            ('律师事务所',r'受托方[（(]乙方[）)][:：]([^:：]{2,100}?律师事务所)(?=住所[:：])')):
            found=re.findall(pattern,compact)
            if len(found)!=1 or not validate_fact(field,found[0],text,text):continue
            candidates[field].append({'field':field,'value':found[0],'quote':text,
                'source_path':key[0],'page':key[1],'method':method,'candidate_origin':'explicit_contract_header'})
    count=0
    for field,refs in candidates.items():
        old=provenance.get(field) or [];old=[old] if isinstance(old,dict) else old
        if (field in manual_fields or fields.get(field) or any(r.get('method')=='human' for r in old)
                or any(c.get('field')==field and not c.get('resolved') for c in conflicts)):continue
        values=list(dict.fromkeys(r['value'] for r in refs))
        if len(values)>1:
            conflicts.append({'field':field,'values':values,'sources':refs,'reason_code':'contract_header_conflict'})
        elif values:
            fields[field]=values[0];provenance[field]=old+refs;count+=1
    return count

def recall_court_number(fields, provenance, conflicts, *, page_cache, allowed_sources,
                       document_units, manual_fields=(), method='visual_agent_local_evidence'):
    """Use a court's own heading after both parties are independently known."""
    client,opponent=(fields.get(k) for k in ('委托人','对方当事人'))
    if not client or not opponent or any(c.get('field') in ('委托人','对方当事人') and not c.get('resolved') for c in conflicts):return 0
    rows=[]
    for u in document_units:
        if u.doc_type!='judgment' or u.confidence<.85:continue
        key=(u.source_path,u.start_page+1);text=page_cache.get(key,'')
        if key not in allowed_sources:continue
        body=re.sub(r'\s+','',text)
        # Require closed court rosters, not party names somewhere in quotations.
        if not all(re.search(role+r'[:：]'+re.escape(name)+r'[，,。；;]',body)
                   for role,name in (('原告',client),('被告',opponent))):continue
        header=body.split('原告',1)[0]
        found=re.findall(r'([（(]\d{4}[）)][\u4e00-\u9fff\d]{2,30}号)',header)
        if len(found)!=1 or '民事判决书' not in header or not validate_fact('案号',found[0],text,text):continue
        rows.append({'field':'案号','value':found[0],'quote':text,'source_path':key[0],'page':key[1],
                     'method':method,'candidate_origin':'court_own_heading_with_current_parties'})
    old=provenance.get('案号') or [];old=[old] if isinstance(old,dict) else old
    if ('案号' in manual_fields or fields.get('案号') or any(r.get('method')=='human' for r in old)
            or any(c.get('field')=='案号' and not c.get('resolved') for c in conflicts)):return 0
    values=list(dict.fromkeys(r['value'] for r in rows))
    if len(values)>1:
        conflicts.append({'field':'案号','values':values,'sources':rows,'reason_code':'multiple_court_stages'})
    elif values:
        fields['案号']=values[0];provenance['案号']=old+rows;return 1
    return 0
