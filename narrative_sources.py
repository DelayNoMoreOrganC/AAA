"""Complete bounded, classified narrative sources using the shared local cache."""
def complete_narrative_pages(pages, units, evidence_seen, guard=None, budget=24):
    limits={'complaint':8,'contract':24,'judgment':20,'ruling':8,'mediation':8,'execution':10}
    lookup={(path,number):key for key,(path,number) in pages.pages.items()}
    metrics={'new_page_reads':0,'cache_hits':0,'incomplete_documents':0,'failed_reads':0,'max_new_page_reads':budget}
    ordered=sorted(units,key=lambda u:(0 if u.doc_type=='complaint' else 1 if u.doc_type=='contract' else 2,u.doc_id))
    for unit in ordered:
        # A moderately uncertain pleading can still be read within the same
        # budget. Reading is not acceptance: the complete source/title/roster
        # validators decide whether any fact may be used afterwards.
        threshold = .75 if unit.doc_type == 'complaint' else .85
        if unit.doc_type not in limits or unit.confidence<threshold:continue
        count=unit.end_page-unit.start_page+1
        if not 1<=count<=limits[unit.doc_type]:
            metrics['incomplete_documents']+=1;continue
        keys=[lookup.get((unit.source_path,n)) for n in range(unit.start_page,unit.end_page+1)]
        if any(k is None for k in keys):continue
        missing=[k for k in keys if k not in pages.read_pages]
        if len(missing)>budget-metrics['new_page_reads']:
            metrics['incomplete_documents']+=1;continue
        for key in keys:
            if guard:guard()
            if key in pages.read_pages:
                evidence_seen.add(key);metrics['cache_hits']+=1;continue
            metrics['new_page_reads']+=1
            try:
                if pages.read(key):evidence_seen.add(key)
            except (OSError,ValueError):
                metrics['failed_reads']+=1
    return metrics
