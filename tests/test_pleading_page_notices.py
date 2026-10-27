"""Page-use notices are not facts; allegations and source bytes stay intact."""
from copy import deepcopy
import pytest
from complaint_brief import summarize, _body_text
from case_timeline import events_for

def source(notice):
    return {'pages': [
        {'source_path':'fiction.pdf','page':1,'quote':'民事起诉状\n'+notice+'\n原告：甲银行。被告：乙公司。\n诉讼请求：判令被告偿还本金1000元及利息。\n事实与理由详见下一页。'},
        {'source_path':'fiction.pdf','page':2,'quote':'事实与理由（续）\n'+notice+'\n双方签订借款合同，约定借款1000元。原告主张已放款，被告到期未偿还。此致示例法院。'}]}

@pytest.mark.parametrize('notice',[
    '完全虚构验收材料，无真实身份或印章。',
    '本材料仅供内部培训使用。',
    '此文档仅用于系统测试，不涉及真实个人信息。',
    '模拟演示材料。',
    '仅供排版校验使用。',
])
def test_standalone_page_use_notices_do_not_consume_fact_space(notice):
    data=source(notice); original=deepcopy(data)
    value=summarize(data)
    assert value and notice not in value
    assert '约定借款1000元' in value and '被告到期未偿还' in value
    assert '偿还本金1000元及利息' in value and '原告诉称' in value
    doc=dict(kind='complaint',source_path='fiction.pdf',start_page=1,end_page=2,pages=data['pages'])
    events=events_for(doc,{'委托人':'甲银行','对方当事人':'乙公司'})
    assert events and notice not in events[0]['summary']
    assert '到期未偿还' in events[0]['summary']
    assert data==original

@pytest.mark.parametrize('text',[
    '原告主张被告提交虚构材料，隐瞒实际用途。',
    '借款仅供内部培训使用，不得挪作他用。',
    '本合同仅用于系统测试，被告仍应支付测试服务费用。',
    '完全虚构验收材料导致原告遭受损失。',
    '本材料仅供内部培训使用，但被告擅自对外销售。',
    '原告尚未履行放款义务。',
    '被告已偿还500元，原告仅主张剩余款项。',
])
def test_fact_lines_with_similar_words_and_negation_are_preserved(text):
    pages=source(text)['pages']
    assert text in _body_text(pages)

def test_notice_inline_with_fact_is_not_silently_deleted():
    text='本材料仅供内部培训使用。双方约定测试服务费1000元。'
    assert text in _body_text(source(text)['pages'])

def test_document_notice_inside_body_is_not_page_furniture():
    pages=[{'quote':'民事起诉状\n原告：甲。\n被告：乙。\n事实与理由：\n本材料仅供内部培训使用。\n被告违反该约定。'}]
    assert '本材料仅供内部培训使用。' in _body_text(pages)

def test_filtering_notice_does_not_invent_missing_facts():
    data=source('本材料仅供内部培训使用。')
    data['pages'][1]['quote']='事实与理由（续）\n本材料仅供内部培训使用。\n此致示例法院。'
    assert summarize(data) is None
