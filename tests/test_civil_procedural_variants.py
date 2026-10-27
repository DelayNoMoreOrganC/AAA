"""Independent fictional procedural variants: scope must survive synthesis."""
from copy import deepcopy
import pytest
from case_timeline import collect, current_support, events_for, summaries
from document_title_review import title_evidence
from pdf_doc_locator import DocumentUnit
import archive_catalog
import archive_pipeline
import original_catalog

NUMBER='(2026)粤0999民初5901号'
IDENTITY={'案号':NUMBER,'委托人':'虚构甲银行','对方当事人':'虚构乙公司、虚构丙',
          '案由':'金融借款合同纠纷','律师事务所':'虚构甲律师事务所','承办律师':'虚构律师甲'}
CONTRACT=('委托代理合同\n委托人（甲方）：虚构甲银行。受托人（乙方）：虚构甲律师事务所。'
          '甲方委托乙方代理其诉虚构乙公司、虚构丙金融借款合同纠纷一审案件。')
HEADER=f'虚构区人民法院\n民事裁定书\n{NUMBER}\n原告：虚构甲银行。被告：虚构乙公司、虚构丙。\n'
CASES=[
    ('dismiss','驳回原告虚构甲银行的起诉。'),
    ('withdraw','准许原告虚构甲银行撤回起诉。'),
    ('withdraw_alternate','准予原告虚构甲银行撤回起诉。'),
    ('partial_dismiss','一、驳回原告虚构甲银行对被告虚构乙公司的起诉；二、原告对被告虚构丙的诉讼继续审理。'),
    ('partial_withdraw','准许原告虚构甲银行撤回对被告虚构乙公司的起诉。原告对被告虚构丙的诉讼继续审理。'),
    ('withdraw_refused','不准许原告虚构甲银行撤回起诉。本案继续审理。'),
    ('counterclaim','准许被告虚构乙公司撤回反诉。本诉继续审理。'),
]

def doc(text,kind='ruling',page=2):
    return dict(kind=kind,doc_id=str(page),source_path='fictional.pdf',start_page=page,end_page=page,
                pages=[dict(page=page,quote=text)])

@pytest.mark.parametrize('name,operative',CASES)
@pytest.mark.parametrize('heading',['裁定如下：','裁定：'])
def test_short_civil_ruling_keeps_scope_and_continuing_proceedings(name,operative,heading):
    text=HEADER+heading+operative+'如不服本裁定，可依法上诉。审判员：虚构审判员。'
    title=title_evidence(text,case_type='civil')
    assert title['verified'] and title['doc_type']=='ruling'
    events=events_for(doc(text),IDENTITY)
    result=summaries(events)
    assert result is not None
    for value in result.values():
        assert operative.replace('；',';') in value
        assert '如不服' not in value and '虚构审判员' not in value
        assert not any(word in value for word in ('全案终结','已生效','已履行','已结案','已经撤诉'))
    # A procedural ruling is not execution material and cannot enable row 18.
    units=[DocumentUnit(0,title['doc_type'],1,1,source_path='fictional.pdf',confidence=.95)]
    found=archive_pipeline.compute_found_seqs(archive_catalog.get_catalog('civil'),units,{})
    assert 14 in found and 15 not in found
    assert len(original_catalog.row_mapping('civil',15 in found))==17

@pytest.mark.parametrize('prefix',['原告诉称：请求法院','引用案例：','本院拟作出'])
def test_proposed_requested_or_other_case_disposition_is_not_an_actual_result(prefix):
    assert not events_for(doc(HEADER+prefix+'裁定如下：准予原告虚构甲银行撤回起诉。'),IDENTITY)

def test_contract_and_partial_order_produce_source_bound_summary_without_erasing_scope():
    text=HEADER+'裁定如下：'+dict(CASES)['partial_withdraw']
    fields=deepcopy(IDENTITY);refs={}
    cache={('fictional.pdf',1):CONTRACT,('fictional.pdf',2):text}
    units=[DocumentUnit(0,'contract',0,0,source_path='fictional.pdf',confidence=.95),
           DocumentUnit(1,'ruling',1,1,source_path='fictional.pdf',confidence=.95)]
    assert collect(fields,refs,[],page_cache=cache,allowed_sources=set(cache),document_units=units)==2
    assert '一审代理事项' in fields['结案小结']
    assert '对被告虚构乙公司' in fields['结案小结'] and '虚构丙的诉讼继续审理' in fields['结案小结']
    assert '代理事项' not in fields['审（办）结果']
    assert current_support(refs['结案小结'][-1],fields)
    fields['案号']='(2026)粤0999民初999号'
    assert current_support(refs['结案小结'][-1],fields) is None

def test_unrelated_case_cannot_supply_procedural_result():
    assert not events_for(doc(HEADER.replace(NUMBER,'(2026)粤0999民初999号')+'裁定如下：准许撤诉。'),IDENTITY)

def test_competing_rulings_or_judgments_are_not_silently_reduced_to_the_last_result():
    first=events_for(doc(HEADER+'裁定如下：'+dict(CASES)['withdraw_refused']),IDENTITY)
    second=events_for(doc(HEADER+'裁定如下：'+dict(CASES)['withdraw']),IDENTITY)
    assert summaries(first+second) is None
    assert summaries(second+first) is None
    assert summaries(first+first) is not None
    for code in ('judgment','repayment_judgment'):
        assert summaries([{'code':code,'summary':'原告全部请求获支持。'},
                          {'code':code,'summary':'驳回其余请求。'}]) is None

def test_long_or_repeated_dispositions_cannot_be_truncated_into_a_whole_case_withdrawal():
    body='准许原告撤回对被告虚构乙公司的起诉。'+('本诉继续审理。'*40)
    assert not events_for(doc(HEADER+'裁定如下：'+body),IDENTITY)
    assert not events_for(doc(HEADER+'裁定如下：准许撤诉。裁定如下：不准许撤诉。'),IDENTITY)

@pytest.mark.parametrize('execution_present',[False,True])
def test_actual_execution_document_not_a_mention_selects_eighteen_row_catalog(execution_present):
    number='(2026)粤0999执5901号'
    if execution_present:
        text=f'虚构区人民法院\n民事裁定书\n{number}\n裁定如下：终结本次执行程序。'
    else:
        text=HEADER.replace('民事裁定书','民事判决书')+'判决如下：被告虚构乙公司偿还借款本金1000元。如未履行可申请执行。'
    title=title_evidence(text,case_type='civil')
    assert title['verified']
    assert title['doc_type']==('execution' if execution_present else 'judgment')
    units=[DocumentUnit(0,title['doc_type'],0,0,source_path='fictional.pdf',confidence=.95)]
    found=archive_pipeline.compute_found_seqs(archive_catalog.get_catalog('civil'),units,{})
    assert (15 in found) is execution_present
    assert len(original_catalog.row_mapping('civil',15 in found))==(18 if execution_present else 17)
    if execution_present:
        events=events_for(doc(text,kind='execution',page=1),{**IDENTITY,'执行案号':number})
        result=summaries(events)
        assert '终结本次执行' in result['结案小结'] and '不据终本认定债务已清偿' in result['结案小结']
        assert '已执行完毕' not in result['结案小结']

