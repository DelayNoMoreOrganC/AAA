"""Fictional notices: selected terms, identity and price/receipt separation."""
from copy import deepcopy
import pytest
from source_fee_notice import candidate, recall_fee, reference_supported, reference_note
from source_fact_recall import recall_cached_source_facts

FIELDS = {'委托人': '星河演示公司', '对方当事人': '虚构乙、虚构丙', '案由': '买卖合同纠纷'}
NOTICE = '''委托代理通知书
虚构明理律师事务所：
现决定将星河演示公司与虚构乙、虚构丙买卖合同纠纷案件交由贵所代理。
一、按照以下第
1
种计费方式计算律师费：
1.前期费用加风险代理收费方式
（1）前期律师费：_2000元。
（2）风险代理律师费费率为：基准费率_2.5%。
2.固定收费方式：固定律师费：元。
二、律师费增加、扣减标准如下：提前完成可增加10%的律师费。
三、债权转让时另按下列条件调整：
'''


def prepared():
    fields = deepcopy(FIELDS)
    fields.update(_provenance={}, _field_conflicts=[], _fact_review=[
        {'field': '收费标准', 'source_path': 'notice.pdf', 'page': 1,
         'reason_code': 'local_evidence_rejected'}])
    recall(fields, {('notice.pdf', 1): NOTICE})
    return fields


def recall(fields, cache, manual=()):
    return recall_fee(fields, fields.setdefault('_provenance', {}), fields.setdefault('_field_conflicts', []),
                      page_cache=cache, allowed_sources=set(cache), manual_fields=manual,
                      fact_review=fields.setdefault('_fact_review', []))


def test_fee_preserves_source_terms_and_never_means_paid_or_signed():
    fields = prepared()
    assert fields['收费标准'] == '前期2000元\n风险基准2.5%'
    ref = fields['_provenance']['收费标准'][0]
    assert ref['quote'] == NOTICE and '2.5%' in ref['fee_terms'] and '增加10%' in ref['fee_terms']
    assert reference_supported('收费标准', fields['收费标准'], ref, fields)
    assert not any(k in fields for k in ('实收费用', '签约日期', '收案日期', '合同号'))
    assert recall(fields, {('notice.pdf', 1): NOTICE}) == 0


def test_only_selected_fixed_option_is_displayed():
    page = NOTICE.replace('以下第\n1\n种', '以下第2种').replace('固定律师费：元', '固定律师费：9000元')
    assert candidate(page, FIELDS)['value'] == '固定9000元\n调整见通知书'
    # Unselected blanks must not make the selected, complete fixed fee fail.
    page = page.replace('_2000元', '元').replace('_2.5%', '%')
    assert candidate(page, FIELDS)['value'] == '固定9000元\n调整见通知书'


@pytest.mark.parametrize('page', [
    NOTICE.replace('以下第\n1\n种', '以下第种'),
    NOTICE.replace('以下第\n1\n种', '以下第2种'),  # Selected amount blank.
    NOTICE.replace('以下第\n1\n种', '以下第1或2种'),
    NOTICE.replace('2.5%', '2.5‰'),
    NOTICE.replace('2.5%', '102%'),
    NOTICE.replace('_2.5%', '%'),
    NOTICE.replace('_2000元', '元'),
    NOTICE.replace('星河演示公司', '另一虚构公司'),
    NOTICE.replace('虚构乙、虚构丙', '虚构乙'),
    NOTICE.replace('买卖合同纠纷', '金融借款合同纠纷'),
    '参考模板\n' + NOTICE,
    NOTICE + '通知书已作废',
    NOTICE.replace('前期律师费：_2000', '前期律师费：_金额不清'),
    NOTICE.replace('（2）', '其他收费条件：另加一万元。（2）'),
])
def test_unknown_ambiguous_unselected_or_other_case_notices_are_not_guessed(page):
    assert candidate(page, FIELDS) is None


@pytest.mark.parametrize('changed', [NOTICE.replace('2.5%', '3.5%'), NOTICE.replace('增加10%', '增加20%')])
def test_equal_short_values_do_not_hide_different_fee_terms(changed):
    fields = deepcopy(FIELDS)
    assert recall(fields, {('a.pdf', 1): NOTICE, ('b.pdf', 1): changed}) == 0
    assert not fields.get('收费标准')
    assert fields['_field_conflicts'][0]['reason_code'] == 'fee_notice_terms_conflict'


@pytest.mark.parametrize('field', ['委托人', '对方当事人', '案由'])
def test_current_identity_changes_invalidate_fee(field):
    fields = prepared(); ref = fields['_provenance']['收费标准'][0]
    fields[field] = '已修改的虚构内容'
    assert not reference_supported('收费标准', fields['收费标准'], ref, fields)


def test_conflicts_and_manual_blank_are_preserved():
    fields = deepcopy(FIELDS)
    assert recall(fields, {('notice.pdf', 1): NOTICE}, manual=('收费标准',)) == 0
    fields['_field_conflicts'] = [{'field': '对方当事人', 'values': ['虚构乙', '虚构丙']}]
    assert recall(fields, {('notice.pdf', 1): NOTICE}) == 0


def test_normal_recall_reaches_fee_without_extra_reads_or_calls():
    fields = deepcopy(FIELDS); refs = {}; conflicts = []; review = []
    metrics = recall_cached_source_facts(fields, refs, conflicts,
        page_cache={('notice.pdf', 1): NOTICE}, allowed_sources={('notice.pdf', 1)}, fact_review=review)
    assert fields['收费标准'] == '前期2000元\n风险基准2.5%'
    assert metrics['additional_model_requests'] == metrics['additional_page_reads'] == 0


def test_historical_summary_remains_supported_without_silent_upgrade():
    fields=deepcopy(FIELDS)
    old=candidate(NOTICE,fields,summary_version=1)
    old.update(source_path='notice.pdf',page=1,method='visual_agent_local_evidence')
    fields.update(收费标准=old['value'],_provenance={'收费标准':[old]})
    assert old['value']=='前期2000元\n风险等见通知书'
    assert 'summary_version' not in old
    assert reference_supported('收费标准',old['value'],old,fields)
    assert reference_note(fields)==''
    changed=deepcopy(old);changed['quote']=changed['quote'].replace('2.5%','3.5%')
    assert not reference_supported('收费标准',old['value'],changed,fields)


def test_current_fee_reference_keeps_rate_and_points_to_remaining_terms():
    fields=prepared()
    assert '风险基准2.5%' in fields['收费标准']
    assert reference_note(fields)=='其他收费约定详卷内委托代理通知书。'
    fields['_field_conflicts']=[{'field':'收费标准','resolved':False}]
    assert reference_note(fields)==''


def test_derived_fee_uses_current_proof_when_legacy_record_is_preserved():
    from source_fee_notice import current_support
    fields=prepared()
    current=deepcopy(fields['_provenance']['收费标准'][0])
    old=dict(current, **candidate(NOTICE,fields,summary_version=1))
    old.pop('summary_version',None)
    fields['_provenance']['收费标准'].insert(0,old)
    derived=dict(current,method='derived_form_draft',input_method=current['method'],
                 input_field='收费标准',input_value=fields['收费标准'])
    assert current_support(derived,fields)==[]
    fields['_provenance']['收费标准']=[old]
    assert current_support(derived,fields) is None


@pytest.mark.parametrize('version',[None,True,0,3,'2'])
def test_unknown_summary_version_is_not_accepted(version):
    assert candidate(NOTICE,FIELDS,summary_version=version) is None
