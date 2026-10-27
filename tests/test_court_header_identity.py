"""Court headers must bind outcomes to a case, without adopting citations."""
import pytest
from document_title_review import title_evidence

NUMBER = '(2026)粤0999民初5301号'
COURT = '虚构市示例区人民法院'

@pytest.mark.parametrize('header', [COURT+'  '+NUMBER, COURT+' 案号：'+NUMBER,
    COURT+'\t'+NUMBER.replace('(', '（').replace(')', '）')])
@pytest.mark.parametrize('before', [True, False])
def test_combined_court_header_keeps_identity(header, before):
    lines = [header, '民事判决书'] if before else ['民事判决书', header]
    result = title_evidence('\n'.join(lines)+'\n原告：虚构甲。被告：虚构乙。\n判决：驳回全部诉讼请求。')
    assert result and result['verified']
    assert result['_identity'] == NUMBER
    assert result['procedure_stage'] == 'trial'

@pytest.mark.parametrize('header', ['引用'+COURT+NUMBER, '根据'+COURT+NUMBER,
    '参照'+COURT+NUMBER, '另案'+COURT+NUMBER, '原告诉称'+COURT+NUMBER,
    COURT+'《'+NUMBER+'》', COURT+NUMBER+'判决认定如下'])
def test_cited_or_body_case_number_is_not_adopted(header):
    result = title_evidence('民事判决书\n'+header+'\n判决：驳回全部诉讼请求。')
    assert not result.get('_identity')

def test_same_stage_competing_header_numbers_need_review():
    result = title_evidence('民事判决书\n'+COURT+NUMBER+'\n'+NUMBER.replace('5301', '5302')+'\n判决：驳回诉讼请求。')
    assert result['verified'] is False
    assert result['reason_code'] == 'conflicting_leading_case_numbers'

def test_repeated_same_header_number_is_not_conflict():
    result = title_evidence('民事判决书\n'+COURT+NUMBER+'\n'+NUMBER+'\n判决：驳回诉讼请求。')
    assert result['verified'] and result['_identity'] == NUMBER

def test_number_deep_in_body_is_not_header_identity():
    text = '民事判决书\n'+COURT+'\n原告：虚构甲。\n被告：虚构乙。\n'+COURT+NUMBER+'\n判决：驳回诉讼请求。'
    assert not title_evidence(text)['_identity']
