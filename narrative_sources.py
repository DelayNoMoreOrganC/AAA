"""Complete bounded, classified narrative sources using the shared local cache."""
import math

BUSINESS_PRIORITY = {
    'nonlit': ('contract', 'legal_work', 'client_talk', 'work_record', 'agreement_status'),
    'counsel': ('contract', 'work_record', 'agreement_status', 'legal_work', 'client_talk'),
    'criminal': ('indictment', 'contract', 'plea', 'agent_opinion', 'ruling', 'judgment', 'meeting_record'),
}

def complete_narrative_pages(pages, units, evidence_seen, guard=None, budget=24, *, case_type=None):
    if type(budget) is not int or not 0 <= budget <= 128:
        raise ValueError('invalid narrative read budget')
    limits={'complaint':8,'contract':24,'judgment':20,'ruling':8,'mediation':8,'execution':10,
            'indictment':12,'plea':12,'agent_opinion':12,'meeting_record':8,
            'legal_work':12,'work_record':12,'agreement_status':8,'client_talk':8}
    category={'非诉':'nonlit','非诉讼':'nonlit','顾问':'counsel','法律顾问':'counsel','刑事':'criminal'}.get(case_type,case_type)
    priority=BUSINESS_PRIORITY.get(category,('complaint','contract'))
    lookup={(path,number):key for key,(path,number) in pages.pages.items()}
    metrics={'new_page_reads':0,'cache_hits':0,'incomplete_documents':0,'failed_reads':0,
             'max_new_page_reads':budget,'completed_documents':0,'incomplete_reasons':[]}
    ordered=sorted(units,key=lambda u:(priority.index(u.doc_type) if u.doc_type in priority else len(priority),u.doc_id))
    def incomplete(unit, reason):
        metrics['incomplete_documents']+=1
        metrics['incomplete_reasons'].append({'doc_id':unit.doc_id,'doc_type':unit.doc_type,'reason':reason})
    for unit in ordered:
        # A moderately uncertain pleading can still be read within the same
        # budget. Reading is not acceptance: the complete source/title/roster
        # validators decide whether any fact may be used afterwards.
        threshold = .75 if unit.doc_type == 'complaint' else .85
        if unit.doc_type not in limits:continue
        if type(unit.confidence) not in (int,float) or not math.isfinite(unit.confidence) or unit.confidence<threshold:
            incomplete(unit,'classification_uncertain');continue
        count=unit.end_page-unit.start_page+1
        if not 1<=count<=limits[unit.doc_type]:
            incomplete(unit,'document_length_limit');continue
        keys=[lookup.get((unit.source_path,n)) for n in range(unit.start_page,unit.end_page+1)]
        if any(k is None for k in keys):
            incomplete(unit,'source_page_missing');continue
        missing=[k for k in keys if k not in pages.read_pages]
        if len(missing)>budget-metrics['new_page_reads']:
            incomplete(unit,'local_read_budget');continue
        complete=True
        for key in keys:
            if guard:guard()
            if key in pages.read_pages:
                evidence_seen.add(key);metrics['cache_hits']+=1;continue
            metrics['new_page_reads']+=1
            try:
                if pages.read(key):evidence_seen.add(key)
                else:complete=False
            except (OSError,ValueError):
                metrics['failed_reads']+=1;complete=False
        if complete:metrics['completed_documents']+=1
        else:incomplete(unit,'empty_or_failed_read')
    return metrics
