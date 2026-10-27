"""An explicit court outcome is not proof of receipt or counsel's closure date."""
import pytest
from fact_evidence import validate_fact

VALUE='本案已执行完毕。'


def test_accepts_existing_literal_completion_candidate_on_a_continuation_page():
    page='拍卖款足以覆盖本案债务。\n本案已执行完毕。\n特此通知。'
    assert validate_fact('结案小结',VALUE,VALUE,page)
    assert not validate_fact('结案小结','本案已执行完毕，款项全部到账。',VALUE,page)
    for field in ('实收款','已收业务费','结案日期','履行情况'):
        assert not validate_fact(field,VALUE,VALUE,page)


@pytest.mark.parametrize('page',[
    '如果本案已执行完毕。',
    '不代表本案已执行完毕。',
    '申请人声称本案已执行完毕。',
    '另案材料记载：本案已执行完毕。',
    '尚未确认本案已执行完毕。',
    '未记载本案已执行完毕。',
    '是否本案已执行完毕。',
    '本案尚未执行完毕。',
])
def test_cropped_conditions_allegations_references_or_missing_information_are_not_results(page):
    assert not validate_fact('结案小结',VALUE,VALUE,page)
