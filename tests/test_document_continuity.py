"""Fictional continuity evidence; source order and independent identities matter."""
from copy import deepcopy
import pytest
from document_title_review import review_visual_titles
from tests.test_document_title_review import FakePages,row
from tests.test_visual_document_workflow import pdf,mock_client,classified,extracted,run,coverage,offline_only


def contract(n,total=3,number='SYNTHETIC-73',title='借款合同'):
    return f'{title}\n合同编号：{number}\n借款人：虚构甲。贷款人：虚构乙。\n本页为虚构合同条款。\n第{n}页 共{total}页'


def review(texts):
    pages=FakePages(texts)
    out,audit=review_visual_titles([row(k,True,'evidence') for k in pages.pages],pages)
    return out,audit,pages


def test_numbered_contract_pages_are_one_document_without_extra_reads():
    texts=[contract(n) for n in (1,2,3)]
    out,audit,pages=review(texts)
    assert [r['document_start'] for r in out]==[True,False,False]
    assert pages.reads==['p1','p2','p3']
    assert len([a for a in audit if a['reason_code']=='numbered_continuation_verified'])==2
    assert 'SYNTHETIC-73' not in str(audit)
    assert [r['page_id'] for r in out]==list(pages.pages)


@pytest.mark.parametrize('second',[
    contract(2,number='OTHER-73'),contract(2,total=4),contract(3),contract(1),
    contract(2,title='保证合同'),contract(2).replace('第2页 共3页','见第2页 共3页的约定'),
    contract(2).replace('合同编号：SYNTHETIC-73','引用合同编号：SYNTHETIC-73'),
    contract(2)+'\n第1页 共2页',contract(2).replace('合同编号：SYNTHETIC-73',''),
])
def test_ambiguous_or_changed_document_stays_separate(second):
    out,_,_=review([contract(1),second])
    assert [r['document_start'] for r in out]==[True,True]


def test_does_not_cross_files_or_unread_pages_or_rewrite_input():
    original=[row('p1',True,'evidence'),row('p2',True,'evidence')]
    before=deepcopy(original)
    pages=FakePages([contract(1),contract(2)]);pages.pages['p2']=('other.pdf',0)
    assert all(r['document_start'] for r in review_visual_titles(original,pages)[0])
    assert original==before
    pages=FakePages([contract(1),contract(2)])
    assert all(r['document_start'] for r in review_visual_titles(original,pages,max_new_reads=1)[0])


def test_completed_document_does_not_swallow_next_numbered_document():
    out,_,_=review([contract(1,2),contract(2,2),contract(1,2,number='NEW'),contract(2,2,number='NEW')])
    assert [r['document_start'] for r in out]==[True,False,True,False]


def test_two_stage_extraction_reads_whole_group_and_reduces_fragment_requests(tmp_path,monkeypatch):
    source=pdf(tmp_path,3,texts=[contract(n) for n in (1,2,3)])
    def respond(ctx,messages,_):
        if ctx['phase']=='classification':return classified(ctx,starts=tuple(ctx['本批页面']))
        assert ctx['本份允许页面']==['f1p1','f1p2','f1p3']
        assert ctx['本组选读页面']==['f1p1','f1p2','f1p3']
        return extracted(ctx)
    client=mock_client(monkeypatch,respond)
    units,_,metadata,_=run([source],title_review_budget=24)
    assert [(u.start_page,u.end_page) for u in units]==[(0,2)]
    assert all(n==1 for n in coverage(units).values()) and len(coverage(units))==3
    assert client.metrics['model_requests']==2


def test_verified_court_heading_number_and_counter_join_but_different_case_does_not():
    def judgment(n,number='1'):
        return f'虚构区人民法院\n民事判决书\n(2026)虚0101民初{number}号\n本页为裁判正文。\n第{n}页/共2页'
    out,_,_=review([judgment(1),judgment(2)])
    assert [r['document_start'] for r in out]==[True,False]
    out,_,_=review([judgment(1),judgment(2,'2')])
    assert [r['document_start'] for r in out]==[True,True]


def test_partial_run_does_not_claim_numbered_page_two_is_a_complete_document():
    out,audit,_=review([contract(2),contract(3)])
    assert [r['document_start'] for r in out]==[True,True]
    assert not any(a['reason_code']=='numbered_continuation_verified' for a in audit)


def test_repaired_evidence_boundary_allows_index_range_link_without_claiming_completeness(tmp_path,monkeypatch):
    from evidence_index import reconcile
    texts=['证据材料清单\n证据名称 页码\n身份证 1\n借款合同 2-4', '身份证\n虚构身份证明',
           *[contract(n) for n in (1,2,3)], '虚构区人民法院\n民事裁定书\n(2026)虚0101民初2号\n本院裁定驳回起诉。']
    source=pdf(tmp_path,len(texts),texts=texts)
    def respond(ctx,messages,_):
        if ctx['phase']=='classification':
            action=classified(ctx,starts=tuple(ctx['本批页面']))
            for item in action['pages']:
                item['title']='身份证' if item['page_id']=='f1p2' else ''
            return action
        return extracted(ctx)
    mock_client(monkeypatch,respond)
    units,_,_,_=run([source],title_review_budget=24)
    assert [(u.start_page,u.end_page) for u in units]==[(0,0),(1,1),(2,4),(5,5)]
    def b(text,x,y,w=.12):return dict(text=text,normalized_box=[x-w/2,y-.01,x+w/2,y+.01])
    blocks=[b('证据名称',.25,.1),b('页码',.85,.1,.04),b('身份证',.25,.2),b('1',.85,.2,.02),b('借款合同',.25,.3),b('2-4',.85,.3,.04)]
    key=(source.path,1)
    groups,_=reconcile(units,layouts={key:blocks},page_cache={key:texts[0]},allowed_sources={key})
    assert len(groups)==1 and groups[0]['end_page']==5
    assert [r['status'] for r in groups[0]['entries']]==['matched_range','matched_range']
    assert not groups[0]['attachment_completeness_verified']
    assert len(coverage(units))==6 and all(v==1 for v in coverage(units).values())
