"""Source-grounded regressions; no model, OCR, credentials or real case data."""
import pytest

from complaint_brief import summarize
from fact_evidence import validate_fact


def pleading(pointer='事实与理由详见下一页。', continuation=True):
    header = '民事材料测试用页眉'
    pages = [{'source_path': 'fictional.pdf', 'page': 2, 'quote':
              '民事起诉状\n' + header + '\n原告：虚构银行。被告：虚构甲。\n'
              '诉讼请求：判令被告偿还本金100000元及利息3000元。\n' + pointer}]
    if continuation:
        pages.append({'source_path': 'fictional.pdf', 'page': 3, 'quote':
                      '事实与理由（续）\n' + header + '\n双方订立借款合同，金额100000元。'
                      '原告主张已放款。借款到期后被告未还款，催收无果。此致虚构法院。'})
    return {'pages': pages}


@pytest.mark.parametrize('pointer', ['事实与理由详见下一页。', '事实与理由：参见下一页。', '事实与理由见续页。'])
def test_cross_reference_is_replaced_by_same_pleading_continuation(pointer):
    value = summarize(pleading(pointer))
    assert value and '借款到期后被告未还款，催收无果' in value
    assert '本金100000元及利息3000元' in value
    assert '原告诉称' in value and '已放款' in value
    assert not any(word in value for word in ('详见', '页眉', '参见', '（续）'))
    assert len(value) <= 260


def test_missing_continuation_is_not_filled_by_a_pointer():
    assert summarize(pleading(continuation=False)) is None


def test_continuation_from_another_source_or_nonconsecutive_page_is_rejected():
    data = pleading(); data['pages'][1]['source_path'] = 'judgment.pdf'
    assert summarize(data) is None
    data = pleading(); data['pages'][1]['page'] = 5
    assert summarize(data) is None


def test_facts_after_first_period_are_retained_without_cropping_amount():
    data = pleading(); data['pages'][1]['quote'] = data['pages'][1]['quote'].replace(
        '原告主张已放款。', '原告主张尚未足额放款。')
    value = summarize(data)
    assert '尚未足额放款' in value and '催收无果' in value
    assert '100000元' in value


def test_numbered_fact_paragraph_does_not_duplicate_the_first_sentence_tail():
    data = pleading()
    data['pages'][1]['quote'] = data['pages'][1]['quote'].replace('双方订立', '一、双方订立')
    assert summarize(data) == summarize(pleading())


@pytest.mark.parametrize('label', ['委托人（甲方）', '委托方(甲方)', '委托单位（甲方）'])
def test_explicit_parenthesized_client_role(label):
    page = label + '：虚构银行。受托人（乙方）：虚构律所。'
    assert validate_fact('委托人', '虚构银行', page, page)
    assert not validate_fact('委托人', '虚构律所', page, page)


@pytest.mark.parametrize('page,quote', [
    ('受委托人（甲方）：虚构银行。', '委托人（甲方）：虚构银行。'),
    ('不是委托人（甲方）：虚构银行。', '委托人（甲方）：虚构银行。'),
    ('拟委托人（甲方）：虚构银行。', '委托人（甲方）：虚构银行。'),
    ('委托人（甲方之父）：虚构银行。', '委托人（甲方之父）：虚构银行。'),
    ('委托人（甲方）：虚构银行分行。', '委托人（甲方）：虚构银行'),
    ('委托人（甲方）：虚构银行、虚构甲。', '委托人（甲方）：虚构银行'),
])
def test_client_role_does_not_lose_agency_negation_or_name_boundary(page, quote):
    assert not validate_fact('委托人', '虚构银行', quote, page)
