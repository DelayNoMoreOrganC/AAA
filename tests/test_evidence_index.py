from evidence_index import parse_index,reconcile
from pdf_doc_locator import DocumentUnit

def blocks():
    def b(text,x,y,w=.12):return dict(text=text,normalized_box=[x-w/2,y-.01,x+w/2,y+.01])
    return [b('证据名称',.25,.1),b('页码',.85,.1,.04),
        b('身份证',.25,.2),b('1',.85,.2,.02),
        b('借款合同',.25,.3),b('2-3',.85,.3,.04),
        b('系统截图',.25,.4),b('4-',.85,.39,.04),b('5',.85,.415,.02),
        b('委托代理合同',.25,.55),b('6',.85,.55,.02),
        b('证明委托合同存在',.6,.2,.2)]

def test_columns_and_wrapped_ranges_not_proof_prose():
    rows=parse_index(blocks())
    assert [r['title'] for r in rows]==['身份证','借款合同','系统截图','委托代理合同']
    assert rows[2]['printed_end']==5

def test_index_stops_at_court_document_and_does_not_prove_unlocated_contract():
    def u(i,title,a,b,kind='evidence',confidence=.95):
        return DocumentUnit(i,kind,a,b,title=title,confidence=confidence,catalog_seq=7 if kind=='evidence' else 5,source_path='fictional.pdf')
    units=[u(0,'证据材料清单',0,0),u(1,'身份证',1,1),u(2,'借款合同',2,3),
        u(3,'借据信息截图',4,5,confidence=.75),u(4,'受理通知书',6,6,kind='acceptance_notice')]
    cache={('fictional.pdf',1):'清单',('fictional.pdf',5):'银行借据信息'}
    groups,reviews=reconcile(units,layouts={('fictional.pdf',1):blocks()},page_cache=cache,allowed_sources=set(cache))
    assert groups[0]['end_page']==6 and groups[0]['entries'][-1]['status']=='listed_not_located'
    assert groups[0]['attachment_completeness_verified'] is False
    assert units[3].confidence==.85 and reviews[0]['fields_verified'] is False
    assert [(u.start_page,u.end_page) for u in units]==[(0,0),(1,1),(2,3),(4,5),(6,6)]
