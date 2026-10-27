import pytest
from case_timeline import events_for, summaries

NUMBER = '（2026）粤0000民初123号'
HEADER = f'虚构区人民法院\n民事判决书\n{NUMBER}\n原告：虚构甲。被告：虚构乙。\n'
HEARING = '本院于2026年5月20日公开开庭审理本案，原告委托代理人到庭。'
ORDER = '判决：被告偿还借款本金100000元及利息3000元；驳回其他诉讼请求。'


def codes(body):
    return {e['code'] for e in events_for({'kind': 'judgment', 'source_path': 'fictional.pdf',
        'start_page': 1, 'end_page': 1, 'pages': [{'page': 1, 'quote': HEADER + body}]}, {'案号': NUMBER})}


def test_concise_court_disposition_and_dated_hearing_are_distinct_documented_events():
    assert codes(HEARING + ORDER) == {'trial_hearing', 'repayment_judgment'}


def test_process_summary_keeps_amount_and_adverse_partial_outcome():
    events = events_for({'kind': 'judgment', 'source_path': 'fictional.pdf', 'start_page': 1,
        'end_page': 1, 'pages': [{'page': 1, 'quote': HEADER + HEARING + ORDER}]}, {'案号': NUMBER})
    result = summaries(events)
    for key in ('结案小结', '审（办）结果'):
        assert '100000元' in result[key] and '3000元' in result[key]
        assert '驳回其他诉讼请求' in result[key] and '开庭审理' in result[key]
        assert '已履行' not in result[key] and '已生效' not in result[key]


@pytest.mark.parametrize('prefix', ['原告诉称：请求法院', '引用案例：', '本院拟作出'])
def test_concise_disposition_cannot_turn_claim_or_reference_into_result(prefix):
    assert codes(prefix + ORDER) == set()


@pytest.mark.parametrize('hearing', [HEARING.replace('公开', '拟公开'),
    '原告诉称：' + HEARING, HEARING.replace('本院于', '本院拟于')])
def test_future_or_quoted_hearing_is_not_a_completed_step(hearing):
    assert 'trial_hearing' not in codes(hearing + ORDER)


def test_standard_operative_heading_retains_all_short_clauses_and_excludes_appeal_notice():
    body='判决如下：一、被告偿还借款本金100000元及利息3000元。二、驳回其他诉讼请求。如不服本判决，可上诉。'
    events=events_for({'kind':'judgment','source_path':'fictional.pdf','start_page':1,'end_page':1,
        'pages':[{'page':1,'quote':HEADER+body}]},{'案号':NUMBER})
    result=summaries(events)
    for value in result.values():
        assert '100000元' in value and '3000元' in value and '驳回其他诉讼请求' in value
        assert '可上诉' not in value


@pytest.mark.parametrize('prefix',['原告诉称：请求法院','引用案例：','本院拟作出'])
def test_standard_disposition_also_rejects_claims_and_other_case_quotes(prefix):
    assert codes(prefix+ORDER.replace('判决：','判决如下：'))==set()
