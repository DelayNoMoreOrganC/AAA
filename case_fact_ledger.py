"""One source index for form writing. No I/O, providers or invented chronology.

Dates below are document dates only when found in the closing lines, not dates
of every event mentioned inside a judgment. Amounts retain pleading/judgment
roles. This index helps writers; it does not certify the entire case.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import date
import re

VERSION = 1
ROLES = {'contract':'约定服务范围', 'complaint':'当事人主张', 'indictment':'指控',
         'judgment':'法院裁判', 'ruling':'法院裁定', 'execution':'执行程序记录',
         'legal_work':'法律服务材料', 'work_record':'办理记录', 'court_record':'庭审记录',
         'client_talk':'接案沟通', 'agent_opinion':'代理意见', 'meeting_record':'会见记录',
         'agreement_status':'顾问协议状态', 'plea':'辩护意见'}
INTAKE = {'contract','complaint','indictment','client_talk'}

def compact(text):
    return re.sub(r'\s+', '', str(text or ''))

def _date(text):
    # Only a standalone date in the final lines is eligible for sorting.
    dates = []
    for line in text.splitlines()[-18:]:
        raw = compact(line)
        m = re.fullmatch(r'([0-9〇○零一二三四五六七八九]{4})年([0-9一二三四五六七八九十]{1,3})月([0-9一二三四五六七八九十]{1,3})日',raw)
        if not m: continue
        digits = str.maketrans('〇○零一二三四五六七八九','000123456789')
        def number(s):
            s=s.translate(digits)
            if '十' in s:
                a,b=s.split('十');return int(a or 1)*10+int(b or 0)
            return int(s)
        try: normalized=date(number(m[1]),number(m[2]),number(m[3])).isoformat()
        except ValueError: continue
        dates.append({'value':normalized,'quote':raw,'meaning':'document_date_not_event_date'})
    return dates[0] if len(dates)==1 else None

def build(sources, coverage=None):
    groups=defaultdict(list)
    for source in sources:
        groups[(source['source_path'],source['doc_id'],source['kind'])].append(source)
    docs=[];conflicts=[]
    for (path,doc_id,kind),pages in groups.items():
        pages=sorted(pages,key=lambda s:s['page'])
        last=pages[-1];dt=_date(last['text']) if last.get('evidence_kind') != 'visual-field-synthesis-v1' else None
        amounts=[]
        for page in pages:
            if page.get('evidence_kind') == 'visual-field-synthesis-v1':
                continue  # A checked field quote is not a full-page amount/date source.
            text=compact(page['text'])
            for match in re.finditer(r'(?:贷款本金|尚欠本金|借款本金)[:：]?([0-9]+(?:\.[0-9]+)?)元',text):
                amounts.append({'value':match[1],'source_id':page['id'],'page':page['page'],
                    'quote':match[0], 'role':ROLES.get(kind,kind)})
        # Different loan/granted principal is normal. Flag only inconsistent
        # outstanding principal in the SAME pleading, not across court stages.
        owed=[a for a in amounts if re.match(r'贷款本金|尚欠本金',a['quote'])]
        if kind=='complaint' and len({a['value'] for a in owed})>1:
            conflicts.append({'code':'pleading_principal_difference','field':'案情简介',
                'action':'compare_original_pages_not_replace_with_judgment', 'evidence':owed,
                'source_path':path,'doc_id':doc_id})
        docs.append({'doc_id':doc_id,'kind':kind,'role':ROLES.get(kind,kind),
            'source_ids':[p['id'] for p in pages], 'source_path':path,
            'page_start':pages[0]['page'],'page_end':last['page'],
            'document_date':dict(dt,source_id=last['id']) if dt else None,'amounts':amounts})
    dated=sorted([d for d in docs if d['document_date']],key=lambda d:d['document_date']['value'])
    return {'version':VERSION,'coverage':deepcopy(coverage or {}),'documents':docs,
        'dated_documents':[{'doc_id':d['doc_id'],'source_ids':d['source_ids'],
                            'date':d['document_date']} for d in dated],
        'undated_documents':[d['doc_id'] for d in docs if not d['document_date']],
        'conflicts':conflicts,
        'field_sources':{field:[s['id'] for s in sources if field in s.get('allowed_fields', (field,))
                              and (field not in ('案情简介','案件或项目名称') or s['kind'] in INTAKE)]
                         for field in ('案情简介','案件或项目名称','审（办）结果','结案小结')}}

def public(ledger):
    result=deepcopy(ledger)
    for row in result['documents']+result['conflicts']:row.pop('source_path',None)
    return result

def caption_title_supported(claim, sources):
    """A judicial caption may supply the cause, never change pleading roles."""
    lookup={s['id']:s for s in sources};pleading='';captions=''
    for ref in claim.get('evidence',[]):
        source=lookup.get(ref.get('id'),{})
        if compact(ref.get('quote')) not in compact(source.get('text')):return False
        if source.get('kind')=='complaint':pleading+=compact(ref['quote'])
        elif source.get('kind')=='judgment':captions+=compact(ref['quote'])
        else:return False
    parties=[re.findall(role+r'[:：]([^，,。；;：:]{2,80})[，,。；;]',pleading) for role in ('原告','被告')]
    if any(len(set(p))!=1 for p in parties):return False
    a,b=parties[0][0],parties[1][0]
    m=re.search(r'原告'+re.escape(a)+r'诉被告'+re.escape(b)+r'([^。；：:]{2,24}纠纷)一案',captions)
    if m and compact(claim.get('text')).rstrip('。')==a+'诉'+b+m[1]:return True
    return False

def civil_candidates(sources, ledger, identity=None):
    """Narrow source-derived fallback for a single mortgage-loan proceeding.

    Complete matching clauses only. No amounts silently corrected, no inferred
    attorney work, no merging multiple judgments, no case-specific examples.
    All other kinds keep model writing with the same source ledger.
    """
    groups=defaultdict(list)
    for s in sources:groups[(s['kind'],s['doc_id'])].append(s)
    complaints=[v for (kind,_),v in groups.items() if kind=='complaint']
    judgments=[v for (kind,_),v in groups.items() if kind=='judgment']
    if len(complaints)!=1 or len(judgments)!=1:return {}
    cp=sorted(complaints[0],key=lambda s:s['page']);jp=sorted(judgments[0],key=lambda s:s['page'])
    ctext=''.join(compact(s['text']) for s in cp)
    jtext=''.join(compact(s['text']) for s in jp)
    raw_pleading='\n'.join(s['text'] for s in cp)
    for role in ('原告','被告'):
        if len(re.findall(r'(?:^|\n)\s*'+role+r'[一二三四五六七八九十\d]*[:：]',raw_pleading))!=1:return {}
    if '民事起诉状' not in compact(cp[0]['text'])[:80] or '民事判决书' not in compact(jp[0]['text'])[:100]:return {}
    plaintiffs=re.findall(r'(?:^|[。；;])原告[:：]([^，,。；;：:]{2,80})[，,。；;]',ctext)
    defendants=re.findall(r'(?:^|[。；;])被告[:：]([^，,。；;：:]{2,80})[，,。；;]',ctext)
    # Newline boundaries are significant in party rosters.
    if not plaintiffs:plaintiffs=re.findall(r'^原告[:：]([^，,。；;：:\n]{2,80})[，,。；;]',cp[0]['text'],re.M)
    if not defendants:defendants=re.findall(r'^被告[:：]([^，,。；;：:\n]{2,80})[，,。；;]',cp[0]['text'],re.M)
    if len(set(plaintiffs))!=1 or len(set(defendants))!=1:return {}
    plaintiff,defendant=compact(plaintiffs[0]),compact(defendants[0])
    if not plaintiff or not defendant or any(x not in jtext for x in (plaintiff,defendant)):return {}
    identity=identity or {}
    if identity.get('委托人') and compact(identity['委托人'])!=plaintiff:return {}
    if identity.get('对方当事人') and compact(identity['对方当事人'])!=defendant:return {}
    def numbers(text):return re.findall(r'[（(]\d{4}[）)][\u4e00-\u9fff\d]{1,30}号',compact(text).replace('(', '（').replace(')', '）'))
    case_numbers=numbers(jp[0]['text'])
    if not case_numbers:return {}
    case_number=case_numbers[0]
    if identity.get('案号') and numbers(identity['案号'])!=[case_number]:return {}
    if any(word in jtext for word in ('发回重审','撤销原判','二审','反诉')):return {}
    if not all(word in ctext for word in ('房屋按揭贷款合同','逾期','优先受偿权','诉讼请求','事实与理由')):return {}
    def evidence(needle,pages):
        matches=[s for s in pages if compact(needle) in compact(s['text'])]
        if not matches:return None
        source=matches[0];text=compact(source['text']);start=text.index(compact(needle))
        left=max(text.rfind('。',0,start),text.rfind('；',0,start))+1
        stops=[n for n in (text.find('。',start),text.find('；',start)) if n>=0]
        right=min(stops)+1 if stops else min(len(text),start+len(compact(needle))+80)
        quote=text[left:right]
        if not 6<=len(quote)<=2000:return None
        return {'id':source['id'],'quote':quote}
    def claim(text,needles,pages):
        refs=[evidence(n,pages) for n in needles]
        return {'text':text,'evidence':refs} if all(refs) else None
    facts=claim('原告诉称，双方签订房屋按揭贷款合同，被告逾期还款，经催收仍未清偿。',
        ['个人房屋按揭贷款合同','被告逾期还款时间','原告曾多次向被告催收','但被告拒不偿还'],cp)
    initial=re.findall(r'借款本金[:：](\d+(?:\.\d+)?)元',ctext)
    overdue=re.findall(r'被告逾期还款时间[:：](\d{4}年\d{1,2}月\d{1,2}日)',ctext)
    if len(set(initial))==1 and len(set(overdue))==1:
        facts=claim(f'原告诉称，双方签订房屋按揭贷款合同，借款本金{initial[0]}元；被告自{overdue[0]}起逾期还款，经催收仍未清偿。',
            ['个人房屋按揭贷款合同','借款本金：'+initial[0]+'元',
             '被告逾期还款时间：'+overdue[0],'但被告拒不偿还'],cp) or facts
    requests=claim('诉请被告清偿贷款本金、利息、罚息及复利，承担诉讼费用，并主张抵押房产处置款优先受偿权。',
        ['判令被告向原告清偿贷款本金','利息','罚息','复利','本案全部诉讼费用','优先受偿权'],cp)
    result={}
    gaps=['conflicting_sources'] if ledger['conflicts'] else []
    if facts and requests:result['案情简介']={'claims':[facts,requests],'missing':gaps}
    # Name uses the pleading's actual dispute; no court-result backfill.
    name=claim(f'{plaintiff}诉{defendant}房屋按揭贷款合同纠纷。',
        ['原告：'+plaintiff,'被告：'+defendant,'个人房屋按揭贷款合同'],cp)
    caption=re.search(r'原告'+re.escape(plaintiff)+r'诉被告'+re.escape(defendant)+r'([^。；：:]{2,24}纠纷)一案',jtext)
    if caption:
        title=claim(f'{plaintiff}诉{defendant}{caption[1]}。',
                    ['原告：'+plaintiff,'被告：'+defendant,caption[0]],cp+jp)
        if title and caption_title_supported(title,sources):name=title
    if name:result['案件或项目名称']={'claims':[name],'missing':[]}
    # Require the complete dispositive block and adverse part, not words from
    # quoted prayers. Cross-page fragments remain separate source references.
    marker=re.search(r'判决如下[:：]',jtext)
    if not marker:return result
    operative=re.split(r'如果未按本判决|如不服本判决',jtext[marker.end():],maxsplit=1)[0]
    if not all(word in operative for word in ('偿还借款本金','利息','罚息','复利','优先受偿权','驳回原告')):return result
    court=claim('法院判决被告偿还借款本金及相应利息、罚息、复利，确认原告在判决确定债权范围内对抵押房产处置价款享有优先受偿权，并驳回其他诉讼请求。',
        ['偿还借款本金','利息','罚息','复利','享有优先受偿权','三、驳回原告'+plaintiff+'其他诉讼请求'],jp)
    if not court:return result
    outcome=[court];work=[];completed=False
    # Only an explicit attendance record linked to the plaintiff proves work.
    attendance=re.search(r'原告的委托诉讼代理人([^，,。；;]{2,15})到庭参加诉讼',jtext)
    if attendance:
        lawyer=attendance[1]
        roster='委托诉讼代理人：'+lawyer
        if roster in compact(cp[0]['text']):
            a=claim(f'原告委托诉讼代理人{lawyer}到庭参加诉讼。',[attendance[0]],jp)
            if a:work.append(a)
    ep=[s for s in sources if s['kind']=='execution']
    # Multiple outcomes and competing party/case identities must not collapse
    # into a single current status. This fallback excludes that ambiguity.
    exec_groups=[sorted(v,key=lambda s:s['page']) for k,v in groups.items() if k[0]=='execution']
    linked_numbers=set()
    for pages in exec_groups:
        ns=numbers(''.join(s['text'] for s in pages))
        if ns and case_number in ns and '执' in ns[0]:linked_numbers.add(ns[0])
    if len(linked_numbers)>1:return result
    for pages in exec_groups:
        body=''.join(compact(s['text']) for s in pages)
        if not all(p in body for p in (plaintiff,defendant)):continue
        ns=numbers(body)
        if not ns or ns[0] not in linked_numbers:continue
        auction=re.search(r'裁定如下[:：](拍卖被执行人[^。]{1,240}。)',body)
        if auction:
            # Quote a short exact opening; statement does not imply sale.
            a=claim('执行阶段，法院裁定拍卖被执行人名下房产。',['拍卖被执行人'+defendant+'名下'],pages)
            if a:outcome.append(a)
        if '结案通知书' in body and '本案已执行完毕' in body and '终结本次执行' not in body:
            a=claim('法院结案通知书载明，被执行人已全面履行本案，本案已执行完毕。',
                ['被执行人'+defendant+'已向申请人'+plaintiff+'全面履行本案','本案已执行完毕'],pages)
            if a:outcome.append(a);completed=True
    if any('终结本次执行' in compact(s['text']) for s in ep):return result
    result['审（办）结果']={'claims':outcome,'missing':[] if completed else ['missing_result']}
    # A pleading is a party's request, not by itself proof counsel drafted/filed it.
    result['结案小结']={'claims':(([requests] if requests else [])+work+outcome),
                      'missing':([] if work else ['missing_work'])+([] if completed else ['missing_result'])}
    return result
