"""Source-bound procedural events and two distinct, bounded form summaries.

No network or OCR. An order/notice is never treated as a completed payment or
sale. Stored text is untrusted evidence, not a tool instruction. Human edits win.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import re
import unicodedata
from document_title_review import title_evidence

BINDING='case_timeline_summary'
FIELDS=('结案小结','审（办）结果')
IDENTITY=('案号','执行案号','委托人','对方当事人')
WORK_IDENTITY=(*IDENTITY,'案由','律师事务所','承办律师')


def compact(text):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(text or '')))


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def procedural_disposition(text):
    """Keep the scope of a short ruling, not a guessed whole-case outcome.

    A partial dismissal, denied withdrawal or withdrawn counterclaim cannot
    be reduced to 'the case ended'. Complete clauses retain that distinction.
    Longer or competing operative texts need further review, never truncation.
    """
    from fact_evidence import validate_fact
    markers=list(re.finditer(r'裁定(?:如下)?[:：]',text))
    if len(markers)!=1:return None
    marker=markers[0]
    body=re.split(r'如不服本裁定|审判长|审判员|代理审判员|书记员|裁判日期[:：]',
                  text[marker.end():],maxsplit=1)[0]
    if not body or len(body)>240 or not body.endswith(('。',';','；')):return None
    # Treat the following as a literal procedural disposition, including
    # refusal and counterclaim scope, not proof of finality or performance.
    if not re.match(r'(?:[一二三四五六七八九十\d]+[、.])?(?:驳回|准许|准予|不准许|不准予|不予准许)',body):return None
    candidate=marker[0]+body
    if not validate_fact('审办结果',candidate,candidate,text):return None
    return body


def engagement_scope(text, identity):
    """A contract's stated scope is not proof of signing or completed work."""
    from fact_evidence import validate_fact
    client,firm,matter=(identity.get(k,'') for k in ('委托人','律师事务所','案由'))
    opponents=[compact(n) for n in re.split(r'[、,，;；]',identity.get('对方当事人','')) if compact(n)]
    if not client or not firm or not matter or not opponents:return None
    if not validate_fact('委托人',client,text,text):return None
    body=compact(text)
    if re.search(r'拟委托|计划委托|尚未委托|未予委托|不委托|委托已解除|解除委托|撤销委托|合同草稿|参考模板|填写示例|补充协议|变更协议',body):return None
    if not re.search(r'受托人(?:\(乙方\))?[:：]'+re.escape(compact(firm))+r'(?=[。；;，,]|$)',body):return None
    clauses=re.findall(r'(?:^|[。；;])((?:甲方委托乙方|'+re.escape(compact(client))+r'委托'+re.escape(compact(firm))+r')代理[^。；;]{1,260})[。；;]',body)
    stages=[]
    for clause in clauses:
        if not all(re.search(re.escape(n)+r'(?=[、,，]|'+re.escape(compact(matter))+r')',clause) for n in opponents) or compact(matter) not in clause:continue
        if re.search(r'拟|计划|若|如果|可能|另案|除外|不包括|不含',clause):continue
        tail=clause.split(compact(matter),1)[1]
        found=re.fullmatch(r'(?:的)?((?:一审|二审|再审|执行)(?:[、及和](?:一审|二审|再审|执行))*)(?:案件|程序|事宜|事务|阶段)',tail)
        if found:stages.append('、'.join(dict.fromkeys(re.findall(r'一审|二审|再审|执行',found[1]))))
    if len(stages)!=1:return None
    return '委托合同载明本案'+stages[0]+'代理事项。'


def documented_attendance(text, identity, related_documents=()):
    """Require both the represented party's counsel roster and actual attendance."""
    client,firm=(compact(identity.get(k)) for k in ('委托人','律师事务所'))
    lawyers=[compact(n) for n in re.split(r'[、,，;；]',identity.get('承办律师','')) if compact(n)]
    if not client or not firm or not lawyers:return None
    # A closed court roster is essential: a lawyer merely mentioned in the
    # judgment, or counsel for the opposing party, cannot prove our attendance.
    start=re.search(r'(?:^|[。;；\n])\s*(原告|被告)\s*[:：]\s*'+re.escape(client)+r'(?=[，,。；;\s])',text)
    if not start:return None
    tail=text[start.end():]
    stop=re.search(r'(?:^|[。;；\n])\s*(?:原告\s*[:：]|被告\s*[:：]|第三人\s*[:：]|本院|本案|原告[^:：\n]{2,150}诉被告)',tail)
    if not stop:return None
    roster=compact(tail[:stop.start()]);body=compact(tail[stop.start():])
    for lawyer in lawyers:
        listed=re.search(r'委托(?:诉讼)?代理人[:：]'+re.escape(lawyer)+r'[，,]'+re.escape(firm)+r'律师(?:[。；;]|$)',roster)
        # A separately supplied complete engagement can identify counsel when
        # the court's compact roster omits the firm. It does not prove court
        # attendance: that still needs the explicit event in this judgment.
        if not listed:
            for doc in related_documents:
                if doc.get('kind')!='contract' or not events_for(doc,identity):continue
                contract=compact('\n'.join(p['quote'] for p in doc['pages']))
                if re.search(r'(?:^|[。；;])(?:指派)?承办律师[:：]'+re.escape(lawyer)+r'[。；;]',contract):
                    listed=True;break
        if not listed:continue
        expression=re.escape(start[1])+r'(?:'+re.escape(client)+r')?(?:的)?委托(?:诉讼)?代理人'+re.escape(lawyer)+r'到庭(?:参加诉讼)?'
        for clause in re.split(r'[。；;]',body):
            if re.search(r'拟|计划|将|若|如果|未|不曾|未能|称|另案|假设|引用|记载为',clause):continue
            court_opening=r'(?:本院于\d{4}年\d{1,2}月\d{1,2}日(?:公开|不公开)开庭审理本案[，,])?'
            if re.fullmatch(court_opening+expression,clause):
                return '法院记载委托方代理律师到庭参加诉讼。'
    return None


def events_for(document, identity, related_documents=()):
    pages=document.get('pages',[])
    if not pages or len(pages)>50:return []
    if any(not isinstance(p.get('quote'),str) or not 0<len(p['quote'])<=18000
           or type(p.get('page')) is not int or p['page']!=document['start_page']+i
           for i,p in enumerate(pages)):return []
    if pages[-1]['page']!=document['end_page']:return []
    title=title_evidence(pages[0]['quote'],case_type='civil')
    if not title or not title['verified'] or title['doc_type']!=document['kind']:return []
    text=compact('\n'.join(p['quote'] for p in pages))
    if document['kind']=='contract':
        if title['title'] not in ('委托代理合同','委托合同','法律服务合同'):return []
        scope=engagement_scope('\n'.join(p['quote'] for p in pages),identity)
        return [{'code':'engagement_scope','summary':scope,'status':'contract_stated',
                 'source_path':document['source_path'],'page_start':document['start_page'],
                 'page_end':document['end_page'],'case_number':''}] if scope else []
    if document['kind']=='complaint':
        from complaint_brief import summarize
        parties=[compact(identity.get('委托人')),*re.split(r'[、,，;；]',compact(identity.get('对方当事人')))]
        if not all(p and p in text for p in parties):return []
        source={'pages':[dict(p,source_path=document['source_path']) for p in pages]}
        brief=summarize(source)
        if not brief:return []
        # Reuse the bounded, complete fact excerpt, including the default or
        # dispute after its opening sentence. Do not re-introduce the first-
        # sentence-only loss that the intake summary has already resolved.
        fact=re.match(r'原告诉称：(.+?)(?=诉请(?:摘录|概括)：)',brief)
        if not fact or len(fact[1])>150:return []
        return [{'code':'pleading_facts','summary':'起诉材料载明：'+fact[1],'status':'allegation',
                 'source_path':document['source_path'],'page_start':document['start_page'],
                 'page_end':document['end_page'],'case_number':''}]
    number=title.get('_identity','')
    known={compact(identity.get(k)) for k in ('案号','执行案号') if identity.get(k)}
    if number:
        if number not in known:
            # Preservation has its own number. Both current parties and a
            # preservation heading are required; no arbitrary other-case link.
            if not (document['kind']=='preservation' and all(identity.get(k) and compact(identity[k]) in text
                    for k in ('委托人','对方当事人'))):return []
    else:return []
    if re.search(r'本文书作废|撤销本裁定|参考模板|示例文本|仅供参考',text):return []
    found=[]
    def add(code,label,status='documented'):
        found.append({'code':code,'summary':label,'status':status,'source_path':document['source_path'],
                      'page_start':document['start_page'],'page_end':document['end_page'],'case_number':number})
    kind=document['kind'];heading=title['title']
    if kind=='ruling':
        disposition=procedural_disposition(text)
        if disposition:add('procedural_ruling','法院裁定：'+disposition,'ordered')
        return found
    operative=re.search(r'(?:判决|裁定)如下[:：](.*)',text)
    order=operative[1] if operative else ''
    literal_order=''
    if kind=='judgment':
        from fact_evidence import validate_fact
        # Read the complete operative block across the whole document. A
        # shorthand heading must not silently reduce it to its first sentence.
        markers=list(re.finditer(r'判决(?:如下)?[:：]',text))
        if len(markers)!=1:return []
        marker=markers[0]
        order=text[marker.end():]
        disposition=re.split(
            r'如不服本判决|(?:如果|如)未按本判决指定的期间|审判长|审判员|代理审判员|书记员|裁判日期[:：]',
            order,maxsplit=1)[0]
        candidate=marker[0]+disposition
        if not validate_fact('审办结果',candidate,candidate,text):return []
        if len(disposition)<=240 and disposition.endswith(('。',';','；')):
            literal_order=disposition
    if kind=='preservation':
        add('preservation','法院材料记载财产保全事项。')
    elif kind=='judgment' and order:
        header=text.split('判决如下',1)[0]
        if re.search(r'本院(?:立案|受理)后[^。]{0,45}(?:公开|不公开)开庭(?:进行了|进行|予以)?审理',header):
            add('trial_hearing','案件经法院开庭审理。')
        elif re.search(r'(?:^|[。;；])本院于\d{4}年\d{1,2}月\d{1,2}日(?:公开|不公开)开庭审理本案[，,。]', header):
            add('trial_hearing','案件经法院开庭审理。')
        attendance=documented_attendance('\n'.join(p['quote'] for p in pages),identity,related_documents)
        if attendance:add('counsel_attendance',attendance,'documented')
        if re.search(r'(?:被告|被申请人)[^。;；]{0,180}(?:偿还|清偿|返还)[^。;；]{0,40}(?:本金|借款)',order):
            add('repayment_judgment','法院判决：'+literal_order if literal_order else '法院判决确定借款偿还义务，给付范围以判决为准。','ordered')
        else:add('judgment','法院判决：'+literal_order if literal_order else '法院已作出判决，具体权利义务以判决为准。','ordered')
    elif kind=='execution':
        if heading in ('执行案件受理通知书','受理执行案件通知书','执行立案通知书','受理案件通知书'):
            add('execution_accepted','法院受理执行案件。')
        elif heading=='评估结果通知书':add('valuation_notice','执行中形成评估结果通知。')
        elif heading in ('拍卖事项通知','拍卖事项通知书'):add('auction_notice','法院发出拍卖事项通知。','notified')
        elif heading in ('限制消费令','限制高消费令'):add('consumption_restriction','法院作出限制消费令。','ordered')
        if order:
            if re.match(r'(?:[一二三\d]+[、.])?拍卖',order):add('auction_order','执行中法院裁定拍卖财产。','ordered')
            terminal = re.match(r'(?:[一二三\d]+[、.])?(?:本院\([^。]{0,40}号案)?终结(?:本案|本次|[^。]{0,40}号案件的本次)执行',order)
            if terminal and '本次' in terminal[0]:add('terminate_current','法院裁定终结本次执行程序。','current_procedure_ended')
        if heading in ('执行情况告知书','执行情况通知书','结案通知书','执行结案通知书','执行案件结案通知书'):
            clauses=re.split(r'[。;；]',text)
            for clause in clauses:
                if re.search(r'拟|将|计划|若|如果|未|不曾|申请人称|诉称|另案',clause):continue
                if re.search(r'(?:本院|本案)[^。]{0,160}(?:拍卖成交|已经拍卖|已拍卖)',clause):
                    add('auction_completed','执行情况文书记载财产已拍卖。','completed')
                elif re.search(r'本院依法拍卖[^。]{0,160}得款[\d,.]+元',clause):
                    add('auction_completed','执行情况文书记载财产已拍卖。','completed')
                if re.search(r'(?:本院|本案)[^。]{0,80}(?:已发放|已划付|已支付)[^。]{0,60}(?:申请执行人|执行款)',clause):
                    add('funds_disbursed','执行情况文书记载执行款已发放，金额以原文为准。','completed')
                if re.search(r'(?:本案|该案)(?:已|已经)执行完毕',clause):
                    add('execution_completed','执行结案文书记载本案已执行完毕。','completed')
    return list({e['code']:e for e in found}.values())


def rebuild(bundle, fields):
    if not isinstance(bundle,dict) or not isinstance(bundle.get('identity'),dict):return None
    # Old bundles retain their original identity scope and produce no new
    # contract/counsel assertions without the newly bound identities.
    keys=set(bundle['identity'])
    if keys not in (set(IDENTITY),set(WORK_IDENTITY)):return None
    if bundle['identity']!={k:str(fields.get(k) or '') for k in keys}:return None
    docs=bundle.get('documents')
    if not isinstance(docs,list) or not 1<=len(docs)<=80:return None
    try:events=[event for doc in docs for event in events_for(doc,bundle['identity'],docs)]
    except (KeyError,TypeError,ValueError):return None
    if len({e['summary'] for e in events if e['code']=='engagement_scope'})>1:
        return None  # Multiple scope statements need their relationship checked.
    if not events or any(e['code']=='terminate_current' for e in events) and any(e['code']=='execution_completed' for e in events):
        return None  # Needs dates/reopening evidence; do not select a terminal state.
    return events


def summaries(events):
    for code in ('procedural_ruling','repayment_judgment','judgment'):
        if len({e['summary'] for e in events if e['code']==code})>1:
            return None  # Relationship/chronology must be checked, not last-wins.
    unique=list({e['code']:e for e in events}.values())
    essential={'repayment_judgment','judgment','procedural_ruling','dismiss_action','withdrawal','auction_completed',
               'funds_disbursed','terminate_current','execution_completed'}
    if not any(e['code'] in essential for e in unique):return None
    brief=''.join(e['summary'] for e in unique if e['code'] in essential or e['code']=='trial_hearing')
    # Work scope precedes procedure regardless of physical source order. This
    # is topical ordering, never a fabricated dated chronology.
    narrative=sorted(unique,key=lambda e:0 if e['code']=='engagement_scope' else 1)
    full='卷内办理材料反映：'+''.join(e['summary'] for e in narrative)
    if len(full)>320:
        # A lengthy pleading sentence remains in the intake form; do not drop
        # adverse outcomes or terminal-state qualifications to fit the cell.
        full='卷内办理材料反映：'+''.join(e['summary'] for e in narrative if e['code']!='pleading_facts')
    if any(e['code']=='terminate_current' for e in unique):full+='本小结不据终本认定债务已清偿。'
    if len(brief)>300 or len(full)>320:return None
    return {'审（办）结果':brief,'结案小结':full}


def compatible_result_conflict(row, provenance, docs, identity):
    compatible={'auction_order','terminate_current'}
    values=row.get('values')
    if not isinstance(values,list) or len(values)!=2:return False
    refs=provenance.get(row.get('field')) or [];refs=[refs] if isinstance(refs,dict) else refs
    matched=[];matched_kinds=[]
    for value in values:
        candidates=[];kinds=set()
        for ref in refs:
            if ref.get('method') not in ('local_agent','visual_agent_local_evidence') or ref.get('value')!=value:continue
            for doc in docs:
                if ref.get('source_path')!=doc['source_path']:continue
                page=next((p for p in doc['pages'] if p['page']==ref.get('page')),None)
                if page and compact(value) and compact(ref.get('quote')) and compact(value) in compact(page['quote']) and compact(ref.get('quote')) in compact(page['quote']):
                    kinds.add(doc['kind'])
                    candidates.extend(e['code'] for e in events_for(doc,identity) if e['code'] in compatible)
        if len(kinds)!=1:return False
        matched_kinds.append(next(iter(kinds)))
        matched.append(candidates[0] if len(set(candidates))==1 else None)
    # A judgment and a subsequent execution record are different stages,
    # not competing values of one fact. Both complete sources are retained.
    return set(matched)==compatible or set(matched_kinds)=={'judgment','execution'}


def collect(fields, provenance, conflicts, *, page_cache, allowed_sources, document_units, manual_fields=()):
    identity={k:str(fields.get(k) or '') for k in WORK_IDENTITY}
    if not identity['案号'] and not identity['执行案号']:return 0
    if any(c.get('field') in WORK_IDENTITY and not c.get('resolved') for c in conflicts):return 0
    docs=[]
    for u in document_units:
        if u.doc_type not in ('contract','complaint','preservation','judgment','ruling','execution') or u.confidence<.85:continue
        keys=[(u.source_path,n+1) for n in range(u.start_page,u.end_page+1)]
        if len(keys)>50 or any(k not in allowed_sources or not page_cache.get(k) for k in keys):continue
        doc={'kind':u.doc_type,'doc_id':str(u.doc_id),'source_path':u.source_path,
             'start_page':u.start_page+1,'end_page':u.end_page+1,
             'pages':[{'page':n,'quote':page_cache[(p,n)]} for p,n in keys]}
        if events_for(doc,identity):docs.append(doc)
    # Do not replace a precise single-document result with generic prose. This
    # synthesis exists to combine independently documented procedural events.
    if len(docs) < 2:
        return 0
    bundle={'identity':identity,'documents':docs}
    events=rebuild(bundle,fields)
    if not events:
        # An earlier automatic narrative cannot remain source-verified after
        # newly read complete documents contradict its scope/terminal state.
        fields.pop('_case_timeline',None)
        return 0
    fields['_case_timeline']=dict(bundle,events=events,order='source_order',coverage='cached_complete_documents')
    proposed=summaries(events)
    if not proposed:return 0
    # Only a proved non-exclusive auction order / current-procedure ending may
    # replace the old single-result conflict. All original values are retained.
    resolved=[]
    for row in conflicts:
        if row.get('field') in FIELDS and not row.get('resolved'):
            if row.get('field') in manual_fields:return 0
            if not compatible_result_conflict(row,provenance,docs,identity):return 0
            resolved.append(row)
    count=0
    aliases=('审（办）结果','审办结果')
    for field,value in proposed.items():
        refs=provenance.get(field) or [];refs=[refs] if isinstance(refs,dict) else refs
        if field == '审（办）结果' and any(k in manual_fields or any(r.get('method')=='human' for r in
            ([provenance[k]] if isinstance(provenance.get(k),dict) else provenance.get(k) or [])) for k in aliases):continue
        if field in manual_fields or any(r.get('method')=='human' for r in refs):continue
        # Existing substantive automatic prose is preserved unless all its
        # sources are amongst the complete documents in this synthesis.
        if fields.get(field) and not all(any(r.get('source_path')==d['source_path'] and
                type(r.get('page')) is int and d['start_page']<=r['page']<=d['end_page'] for d in docs) for r in refs):continue
        if fields.get(field) and not refs:continue
        if fields.get(field)==value and any(r.get('binding')==BINDING and r.get('bundle_digest')==digest(bundle) for r in refs):continue
        first=docs[0];page=first['pages'][0]
        ref={'method':'visual_agent_local_evidence','binding':BINDING,'derivation':BINDING,
             'field':field,'value':value,'source_path':first['source_path'],**page,'bundle_digest':digest(bundle)}
        fields[field]=value
        provenance[field]=list(refs)+[ref];count+=1
    if all(fields.get(k)==v for k,v in proposed.items()):
        for row in resolved:
            row.update(resolved=True,resolution='distinct_procedural_events',resolution_method=BINDING,
                       resolution_digest=digest(bundle), resolution_values_digest=digest(row.get('values')))
    return count


def current_support(ref,fields):
    field=ref.get('field');bundle=fields.get('_case_timeline')
    events=rebuild(bundle,fields);proposed=summaries(events) if events else None
    if not proposed or field not in FIELDS or fields.get(field)!=proposed[field] or ref.get('value')!=proposed[field]:return None
    canonical={k:bundle[k] for k in ('identity','documents')}
    if ref.get('bundle_digest')!=digest(canonical):return None
    supports=[{'source_path':d['source_path'],**p} for d in bundle['documents'] for p in d['pages']]
    if not supports or any(ref.get(k)!=supports[0][k] for k in ('source_path','page','quote')):return None
    return deepcopy(supports[1:])


def resolved_conflict_supported(row,fields):
    if row.get('resolution_method')!=BINDING:return False
    bundle=fields.get('_case_timeline');events=rebuild(bundle,fields)
    proposed=summaries(events) if events else None
    return bool(proposed and row.get('resolved') is True
        and ({'auction_order','terminate_current'} <= {e['code'] for e in events}
             or {'judgment','execution'} <= {d['kind'] for d in bundle['documents']})
        and compatible_result_conflict(row,fields.get('_provenance') or {},bundle['documents'],bundle['identity'])
        and row.get('resolution_values_digest')==digest(row.get('values'))
        and row.get('resolution_digest')==digest({k:bundle[k] for k in ('identity','documents')})
        and all(fields.get(k)==v for k,v in proposed.items()))
