"""Short judicial outcomes retain all clauses, including adverse decisions."""
import pytest
from case_timeline import events_for, summaries

NUMBER='(2026)粤0999民初6001号'
IDENTITY={'案号':NUMBER,'委托人':'虚构甲银行','对方当事人':'虚构乙公司'}
HEADER=f'虚构区人民法院\n民事判决书\n{NUMBER}\n原告：虚构甲银行。被告：虚构乙公司。\n'

def document(text):
    return dict(kind='judgment',source_path='fictional.pdf',start_page=1,end_page=1,
                pages=[dict(page=1,quote=text)])

@pytest.mark.parametrize('heading',['判决如下：','判决：'])
@pytest.mark.parametrize('body',[
    '驳回原告虚构甲银行的全部诉讼请求。案件受理费由原告负担。',
    '一、解除双方合同；二、被告虚构乙公司返还设备；三、驳回原告其他诉讼请求。',
    '被告虚构乙公司偿还借款本金1000元。驳回原告关于违约金的诉讼请求。',
])
def test_complete_disposition_in_both_summaries(heading,body):
    text=HEADER+heading+body+'如不服本判决，可依法提起上诉。审判员：虚构审判员。'
    result=summaries(events_for(document(text),IDENTITY))
    assert result is not None
    for value in result.values():
        assert body.replace('；',';') in value
        assert '具体权利义务以判决为准' not in value
        assert '如不服' not in value and '虚构审判员' not in value
        assert not any(word in value for word in ('已生效','已履行','已回款'))

@pytest.mark.parametrize('body',[
    '判决：被告偿还借款1000元。判决：驳回全部请求。',
    '判决如下：被告偿还借款1000元。判决如下：驳回全部请求。',
    '原告诉称：请求法院判决：被告偿还借款1000元。',
    '本院拟判决：被告偿还借款1000元。',
    '引用案例：判决：被告偿还借款1000元。',
])
def test_ambiguous_proposed_or_quoted_order_cannot_be_summarized_as_this_outcome(body):
    assert summaries(events_for(document(HEADER+body),IDENTITY)) is None


def test_multiline_multi_page_order_retains_all_parts():
    first=HEADER+'判决：被告虚构乙公司偿还借款本金1000元。'
    second='驳回原告其他诉讼请求。\n审判员：虚构审判员。'
    doc=document(first)
    doc['end_page']=2
    doc['pages'].append(dict(page=2,quote=second))
    result=summaries(events_for(doc,IDENTITY))
    assert result is not None
    assert '本金1000元。驳回原告其他诉讼请求。' in result['结案小结']
