"""Link a ruled evidence index to existing units, without moving source pages.

OCR geometry separates the name and page columns; prose references in the
proof column never become attachment names. Ambiguous layouts stay unparsed.
"""
from __future__ import annotations
import re
import statistics


def compact(value):
    return re.sub(r"\s+", "", str(value or ""))


def is_index(title):
    return bool(re.fullmatch(r"证据(?:材料)?(?:清单|目录)(?:[（(][^（）()]{1,80}[)）])?", compact(title)))


def parse_index(blocks):
    rows=[]
    for b in blocks or []:
        box=b.get('normalized_box')
        if not isinstance(box,(list,tuple)) or len(box)!=4 or not all(type(x) in (float,int) and 0<=x<=1 for x in box):continue
        if not box[0]<box[2] or not box[1]<box[3]:continue
        rows.append(dict(text=compact(b.get('text')),box=box,x=(box[0]+box[2])/2,y=(box[1]+box[3])/2))
    names=[r for r in rows if r['text']=='证据名称']; pages=[r for r in rows if r['text']=='页码']
    if len(names)!=1 or len(pages)!=1:return []
    name,page=names[0],pages[0]
    if abs(name['y']-page['y'])>.04 or page['x']<=name['x']:return []
    header_y=max(name['box'][3],page['box'][3])
    width=name['box'][2]-name['box'][0]
    name_left,name_right=name['x']-width*.9,name['x']+width*.9
    candidates=sorted([r for r in rows if r['y']>header_y and abs(r['x']-page['x'])<.035
                       and re.fullmatch(r'\d{1,4}(?:[-—–~～至]\d{0,4})?',r['text'])],key=lambda r:r['y'])
    if not candidates:return []
    height=statistics.median(r['box'][3]-r['box'][1] for r in candidates)
    cells=[]
    for r in candidates:
        if cells and re.search(r'[-—–~～至]',cells[-1]['text']) and r['box'][1]-cells[-1]['bottom']<height*1.4:
            cells[-1]['text']+=r['text'];cells[-1]['bottom']=r['box'][3]
        else:cells.append(dict(text=r['text'],top=r['box'][1],bottom=r['box'][3],y=r['y']))
    result=[]
    for i,c in enumerate(cells):
        m=re.fullmatch(r'(\d{1,4})(?:[-—–~～至](\d{1,4}))?',c['text'])
        if not m:return []
        start,end=int(m[1]),int(m[2] or m[1])
        if not 1<=start<=end<=2000:return []
        top=header_y if i==0 else (cells[i-1]['bottom']+c['top'])/2
        bottom=1 if i==len(cells)-1 else (c['bottom']+cells[i+1]['top'])/2
        parts=sorted([r for r in rows if top<r['y']<bottom and name_left<r['x']<name_right],key=lambda r:(r['y'],r['x']))
        title=''.join(r['text'] for r in parts)
        if not title or len(title)>160:return []
        result.append({'title':title,'printed_start':start,'printed_end':end})
    if result[0]['printed_start']!=1 or any(b['printed_start']!=a['printed_end']+1 for a,b in zip(result,result[1:])):return []
    return result


def families(title):
    text=compact(title)
    result=set()
    for name,pattern in [('identity',r'身份证'),('registration',r'不动产登记证明|房地产登记证明'),
                         ('loan_contract',r'贷款合同|借款合同'),('bank_capture',r'系统截图|系统.*截图|借据信息截图|贷款台账截图'),
                         ('debt_detail',r'本息计算|欠款.*明细'),('agency_contract',r'委托代理合同'),('loan_receipt',r'借款借据')]:
        if re.search(pattern,text):result.add(name)
    return result


def reconcile(units, *, layouts, page_cache, allowed_sources):
    groups=[];confirmed=[]
    for i,index in enumerate(units):
        if index.doc_type!='evidence' or not is_index(index.title):continue
        key=(index.source_path,index.start_page+1)
        if key not in allowed_sources:continue
        entries=parse_index(layouts.get(key,[]))
        if not entries:continue
        children=[];end=index.end_page
        for unit in units[i+1:]:
            if (unit.source_path!=index.source_path or unit.start_page!=end+1
                or unit.doc_type!='evidence' or unit.catalog_seq!=index.catalog_seq or is_index(unit.title)):break
            children.append(unit);end=unit.end_page
        offset=index.end_page+1
        # Two separate precise title/range matches establish relative page
        # numbering. No offset is accepted merely because pages follow a list.
        anchors=[]
        for e in entries:
            start,stop=e['printed_start']+offset,e['printed_end']+offset
            matches=[u for u in children if u.start_page+1==start and u.end_page+1==stop
                     and u.confidence>=.85 and families(u.title)&families(e['title'])]
            if len(matches)==1:anchors.append(matches[0].doc_id)
        if len(set(anchors))<2:continue
        linked=[]
        for e in entries:
            start,stop=e['printed_start']+offset,e['printed_end']+offset
            matches=[u for u in children if start<=u.start_page+1 and u.end_page+1<=stop]
            coverage=[n for u in matches for n in range(u.start_page+1,u.end_page+2)]
            mapped=coverage==list(range(start,stop+1))
            expected=families(e['title']);actual=set().union(*(families(u.title) for u in matches)) if matches else set()
            state='matched_range' if mapped and expected and expected<=actual else 'partial_match' if matches else 'listed_not_located'
            linked.append({**e,'source_start':start,'source_end':stop,'doc_ids':[u.doc_id for u in matches],'status':state})
            for u in matches:
                # A screenshot's bank heading independently supports placement;
                # legibility/amount/date extraction remains a separate check.
                text=compact(page_cache.get((u.source_path,u.start_page+1),''))
                if (mapped and 'bank_capture' in expected and 'bank_capture' in families(u.title)
                    and (u.source_path,u.start_page+1) in allowed_sources
                    and re.search(r'借据信息|贷款台账|综合业务系统',text)
                    and u.manual_catalog_seq is None and u.confidence<.85):
                    u.confidence=.85
                    confirmed.append({'doc_id':u.doc_id,'source_path':u.source_path,'page':u.start_page+1,
                        'index_page':index.start_page+1,'effective_doc_type':'evidence','title':u.title,
                        'method':'evidence_index_context','independent_context_verified':True,
                        'reason_code':'index_range_and_bank_heading','fields_verified':False})
        groups.append({'source_path':index.source_path,'index_page':index.start_page+1,
            'start_page':index.start_page+1,'end_page':end+1,'doc_ids':[index.doc_id]+[u.doc_id for u in children],
            'offset':offset,'anchors':anchors,'entries':linked,'attachment_completeness_verified':False})
    from evidence_group_state import bind_groups
    return bind_groups(groups,units),confirmed
