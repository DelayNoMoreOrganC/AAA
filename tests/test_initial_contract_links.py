"""Structural tool protocol only; no model or case accuracy benchmark."""
from copy import deepcopy
from types import SimpleNamespace as NS
import json
import pytest

from visual_boundary_review import boundary_doubts, continuation_links, CONTINUATION_INSTRUCTION
from visual_document_workflow import classify_pages, CLASSIFY_SYSTEM

TITLE = '房屋抵押借款合同'

def row(page, title, start):
    return {'page_id':f'f1p{page}','doc_type':'evidence','confidence':.95,'document_start':start,
        'document_role':'standard','procedure_stage':'trial','title':title,
        'observation':{'visible_title':title,'layout':'form','quality':'clear','writing':'mixed','suggested_rotation':None},
        'field_relevance':{'purpose':'supporting','fields':['案情简介']}}

def fixture():
    rows=[row(1,TITLE,True),row(2,'抵押财产清单',False),row(3,'个人贷款借据',True)]
    raw={'page_id':'f1p2','parent_page_id':'f1p1','kind':'explicit_contract_component','parent_title':TITLE,
        'citations':[{'page_id':'f1p1','quote':TITLE,'box':[.1,.1,.9,.2]},
                     {'page_id':'f1p2','quote':f'本清单为《{TITLE}》项下附件。','box':[.1,.8,.9,.9]}]}
    pages=NS(pages={f'f1p{i}':('source.pdf',i-1) for i in (1,2,3)},read_pages=set(),texts={})
    return rows,raw,pages

def validate(rows,raw,pages,**kwargs):
    return continuation_links([raw],rows,boundary_doubts(rows),set(pages.pages),pages,initial=True,**kwargs)

def test_initial_clear_two_page_relation_is_a_structural_candidate_only():
    rows,raw,pages=fixture();links=validate(rows,raw,pages)
    assert len(links)==1 and links[0]['submission_stage']=='initial'
    assert not links[0]['independently_verified'] and links[0]['does_not_prove_signature_or_performance']
    assert CONTINUATION_INSTRUCTION in CLASSIFY_SYSTEM

@pytest.mark.parametrize('title',['个人贷款借据','不动产登记证明','他项权证','银行流水','法院裁定书'])
def test_independent_documents_cannot_be_absorbed_by_attachment_claim(title):
    rows,raw,pages=fixture();rows[1]['observation']['visible_title']=title
    assert validate(rows,raw,pages)==[]

@pytest.mark.parametrize('quality',['blurred','small_text','unknown','occluded'])
def test_unclear_initial_page_still_requires_review(quality):
    rows,raw,pages=fixture();rows[1]['observation']['quality']=quality
    assert validate(rows,raw,pages)==[]

def test_initial_parent_must_also_be_clear():
    rows,raw,pages=fixture();rows[0]['observation']['quality']='blurred'
    assert validate(rows,raw,pages)==[]

def test_screenshot_is_not_merged_as_a_contract_component():
    rows,raw,pages=fixture();rows[1]['observation']['layout']='screenshot'
    assert validate(rows,raw,pages)==[]

@pytest.mark.parametrize('quote',[f'本清单不是《{TITLE}》项下附件。',f'本清单与《{TITLE}》有关。',f'本清单为《其他借款合同》项下附件。'])
def test_negated_or_unspecified_or_other_contract_relation_stays_unresolved(quote):
    rows,raw,pages=fixture();raw['citations'][1]['quote']=quote
    assert validate(rows,raw,pages)==[]

def test_available_text_disagreement_is_not_ignored():
    rows,raw,pages=fixture();pages.read_pages={'f1p2'};pages.texts={'source.pdf':['','未记载所称附件关系','']}
    assert validate(rows,raw,pages)==[]

def test_cross_file_relation_cannot_authorize_physical_merging():
    rows,raw,pages=fixture();pages.pages['f1p1']=('other.pdf',0)
    with pytest.raises(ValueError,match='INVALID_CONTINUATION_LINK'):validate(rows,raw,pages)

def test_foreign_reference_page_is_rejected():
    rows,raw,pages=fixture();raw['parent_page_id']='f2p1'
    with pytest.raises(ValueError,match='INVALID_CONTINUATION_LINK'):validate(rows,raw,pages)

class Pages:
    def __init__(self,source):
        self.pages=source.pages;self.read_pages=source.read_pages;self.texts=source.texts
        self.groups=[list(self.pages)];self.images=[]
    def image(self,key,**kwargs):
        self.images.append(key)
        return {'type':'image_url','image_url':{'url':'data:image/png;base64,protocol-only'}}

class Client:
    def __init__(self,replies):self.replies=replies;self.calls=[]
    def complete(self,messages):
        self.calls.append(deepcopy(messages))
        assert len(self.calls)<=len(self.replies),'Unexpected extra model request'
        return deepcopy(self.replies[len(self.calls)-1])

def action(rows,links=None):
    result={'tool':'record_batch','pages':rows,'facts':[]}
    if links is not None:result['continuation_links']=links
    return result

def test_first_submission_relation_avoids_additional_boundary_call_and_keeps_receipt_independent():
    rows,raw,source=fixture();client=Client([action(rows,[raw])]);pages=Pages(source)
    decisions,_,_,_,reviews=classify_pages(pages,client,'civil',lambda *_:None)
    assert len(client.calls)==1 and len(decisions)==3 and decisions[2]['document_start']
    assert reviews[0]['attempts']==0 and reviews[0]['status']=='resolved'
    assert reviews[0]['resolution_method']=='initial_visual_relation'
    assert pages.images==list(source.pages)

@pytest.mark.parametrize('initial_links',[None,'malformed'])
def test_missing_or_malformed_initial_link_uses_only_existing_single_review(initial_links):
    rows,raw,source=fixture();client=Client([action(rows,initial_links),action(rows,[raw])])
    decisions,_,_,failures,reviews=classify_pages(Pages(source),client,'civil',lambda *_:None)
    assert len(client.calls)==2 and len(decisions)==3
    assert reviews[0]['attempts']==1 and reviews[0]['status']=='resolved'
    if initial_links is not None:assert sum(failures['classification'].values())==1

def test_unsupported_relation_does_not_silently_resolve_after_review():
    rows,raw,source=fixture();raw['citations'][1]['quote']=f'本清单与《{TITLE}》有关。'
    client=Client([action(rows,[raw]),action(rows,[raw])])
    _,_,_,_,reviews=classify_pages(Pages(source),client,'civil',lambda *_:None)
    assert len(client.calls)==2 and reviews[0]['status']=='unresolved'
    assert [r['page_id'] for r in reviews[0]['remaining_issues']]==['f1p2']
