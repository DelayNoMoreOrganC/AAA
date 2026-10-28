from types import SimpleNamespace as NS
import pytest
from narrative_sources import complete_narrative_pages

class Pages:
    def __init__(self):
        self.pages={f'p{i}':('fiction.pdf',i) for i in range(6)}
        self.read_pages={'p0'};self.calls=[]
    def read(self,k):
        self.calls.append(k);self.read_pages.add(k);return 'fictional text'

def unit(kind,start,end,score=.95):
    return NS(doc_type=kind,doc_id=start,source_path='fiction.pdf',start_page=start,end_page=end,confidence=score)

def test_complete_pleading_first_with_bounded_new_reads_and_reused_cache():
    p=Pages();seen=set()
    metrics=complete_narrative_pages(p,[unit('judgment',3,5),unit('complaint',0,2)],seen,budget=2)
    assert p.calls==['p1','p2'] and seen=={'p0','p1','p2'}
    assert metrics['new_page_reads']==2 and metrics['incomplete_documents']==1
    complete_narrative_pages(p,[unit('complaint',0,2)],seen,budget=0)
    assert p.calls==['p1','p2']

def test_uncertain_and_evidence_documents_do_not_expand_reads():
    p=Pages();complete_narrative_pages(p,[unit('complaint',0,2,.7),unit('evidence',3,5)],set())
    assert p.calls==[]

def test_cancellation_stops_before_read():
    p=Pages()
    def stop():raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):
        complete_narrative_pages(p,[unit('complaint',1,2)],set(),guard=stop)
    assert p.calls==[]

@pytest.mark.parametrize('category,kind', [('nonlit','legal_work'),('counsel','work_record'),('criminal','indictment')])
def test_business_sources_are_read_inside_existing_budget(category,kind):
    p=Pages();seen=set()
    metrics=complete_narrative_pages(p,[unit(kind,1,2)],seen,budget=2,case_type=category)
    assert p.calls==['p1','p2'] and metrics['completed_documents']==1

def test_long_or_empty_sources_are_explicitly_incomplete():
    p=Pages();p.read=lambda k:''
    metrics=complete_narrative_pages(p,[unit('legal_work',1,2)],set(),budget=2,case_type='nonlit')
    assert metrics['completed_documents']==0
    assert metrics['incomplete_reasons'][0]['reason']=='empty_or_failed_read'

def test_nonfinite_confidence_is_not_read():
    p=Pages()
    complete_narrative_pages(p,[unit('work_record',1,2,float('nan'))],set())
    assert p.calls==[]
