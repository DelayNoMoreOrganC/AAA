from copy import deepcopy
import pytest

from pleading_parties import roster, current_support, recall, collect_source
from source_fact_recall import recall_cached_source_facts
from pdf_doc_locator import DocumentUnit
from form_drafts import derive_form_drafts

TEXT = ('民事起诉状\n原告：虚构银行，住所地演示路。\n'
        '被告一：虚构公司。被告二：虚构甲。被告三：虚构乙。\n'
        '第三人：虚构丙。\n案由：金融借款合同纠纷。\n'
        '诉讼请求：请求偿还本金并承担连带责任。\n事实与理由：借款到期未还。')


def run(text=TEXT, client='虚构银行', manual=None, extra=None):
    fields = {'案件类别': '民事', **({'委托人': client} if client else {}), **(extra or {})}
    contract = f'委托人（甲方）：{client}。'
    refs = {'委托人': [{'method': 'local_agent', 'value': client, 'quote': contract,
                       'source_path': 'contract.pdf', 'page': 1}]} if client else {}
    cache = {('complaint.pdf', 1): text, ('contract.pdf', 1): contract}
    units = [DocumentUnit(0, 'complaint', 0, 0, '民事起诉状', source_path='complaint.pdf', confidence=.9)]
    conflicts, review = [], []
    metrics = recall_cached_source_facts(fields, refs, conflicts, page_cache=cache, allowed_sources=set(cache),
        document_units=units, manual_fields=manual or {}, fact_review=review)
    fields.update(_provenance=refs, _field_conflicts=conflicts)
    return fields, units, metrics


def test_numbered_defendants_are_complete_and_case_name_follows_pleading_direction():
    fields, units, metrics = run()
    assert fields['当事人'] == '虚构银行'
    assert fields['对方当事人'] == '虚构公司、虚构甲、虚构乙'
    assert fields['案件或项目名称'] == '虚构银行诉虚构公司、虚构甲、虚构乙的金融借款合同纠纷'
    assert metrics['additional_model_requests'] == metrics['additional_page_reads'] == 0
    for key in ('当事人', '对方当事人', '案件或项目名称', '地址'):
        assert current_support(fields['_provenance'][key][0], fields)
    draft = derive_form_drafts(fields, units, source_manifest=[{'path': 'complaint.pdf', 'pages': 1}, {'path': 'contract.pdf', 'pages': 1}])
    assert draft['案件或项目名称'] == fields['案件或项目名称']


def test_defendant_client_keeps_coparties_out_of_opponent_and_case_name_direction():
    fields, _, _ = run(client='虚构甲')
    assert fields['当事人'] == '虚构甲' and fields['对方当事人'] == '虚构银行'
    assert fields['案件或项目名称'].startswith('虚构银行诉虚构公司、虚构甲、虚构乙')


def test_roster_does_not_infer_client_or_treat_third_party_as_opponent():
    fields, _, _ = run(client=None)
    assert '当事人' not in fields and '对方当事人' not in fields
    assert fields['案件或项目名称']
    fields, _, _ = run(client='虚构丙')
    assert '当事人' not in fields and '对方当事人' not in fields


def test_existing_values_and_human_blanks_are_not_replaced():
    fields, _, _ = run(manual={'当事人': ''}, extra={'当事人': ''})
    assert fields['当事人'] == ''
    fields, _, _ = run(extra={'对方当事人': '不同主体'})
    assert fields['对方当事人'] == '不同主体'
    assert any(c['reason_code'] == 'pleading_roster_conflict' for c in fields['_field_conflicts'])


@pytest.mark.parametrize('text', [TEXT.split('诉讼请求')[0], TEXT.replace('虚构乙', '虚构甲'),
    TEXT.replace('虚构甲。', '虚构甲等人。'), '民事判决书\n引述起诉状\n' + TEXT,
    TEXT + '本案存在反诉。', TEXT.replace('被告三：虚构乙。', '被告三：未提供。')])
def test_incomplete_ambiguous_or_quoted_roster_does_not_generate_identity(text):
    fields, _, _ = run(text)
    assert '_pleading_parties_source' not in fields
    assert not fields.get('案件或项目名称') and not fields.get('对方当事人')


def test_unparsed_additional_defendant_cannot_be_silently_omitted():
    fields, _, _ = run(TEXT.replace('案由：', '被告四（曾用名待核）：虚构丁。\n案由：'))
    assert not fields.get('对方当事人') and not fields.get('案件或项目名称')


@pytest.mark.parametrize('change', ['client', 'quote', 'bundle', 'conflict', 'client_ref', 'value'])
def test_stale_derived_parties_fail_validation(change):
    fields, _, _ = run(); ref = deepcopy(fields['_provenance']['对方当事人'][0])
    if change == 'client': fields['委托人'] = '虚构甲'
    if change == 'quote': ref['quote'] += '改写'
    if change == 'bundle': fields['_pleading_parties_source']['pages'][0]['quote'] = TEXT.replace('虚构乙', '虚构丁')
    if change == 'conflict': fields['_field_conflicts'] = [{'field': '委托人'}]
    if change == 'client_ref': fields['_provenance']['委托人'] = []
    if change == 'value': fields['对方当事人'] = '虚构公司'
    assert current_support(ref, fields) is None


def test_joint_party_lists_keep_all_names():
    fields, _, _ = run(TEXT.replace('被告一：虚构公司。被告二：虚构甲。被告三：虚构乙。', '被告：虚构公司、虚构甲、虚构乙。'))
    assert fields['对方当事人'] == '虚构公司、虚构甲、虚构乙'


def test_client_foundation_outside_current_source_scope_cannot_link_party():
    fields, units, _ = run()
    for key in ('当事人', '对方当事人', '案件或项目名称', '地址'):
        fields.pop(key, None); fields['_provenance'].pop(key, None)
    recall(fields, fields['_provenance'], [], page_cache={('complaint.pdf', 1): TEXT},
           allowed_sources={('complaint.pdf', 1)}, document_units=units, manual_fields={},
           method='local_agent', fact_review=[])
    assert '当事人' not in fields and '对方当事人' not in fields
    assert not fields.get('地址')
    assert fields['案件或项目名称']


def test_multiple_pleadings_do_not_select_a_roster_arbitrarily():
    fields, units, _ = run()
    collect_source(fields, units * 2, {('complaint.pdf', 1): TEXT}, {('complaint.pdf', 1)})
    assert '_pleading_parties_source' not in fields


def test_pleading_residence_reaches_forms_with_two_source_identity_link():
    fields, units, _ = run()
    assert fields['地址'] == '演示路'
    ref = fields['_provenance']['地址'][0]
    assert {p['source_path'] for p in current_support(ref, fields)} == {'complaint.pdf', 'contract.pdf'}
    draft = derive_form_drafts(fields, units, source_manifest=[{'path': 'complaint.pdf', 'pages': 1}, {'path': 'contract.pdf', 'pages': 1}])
    assert draft['地址'] == '演示路'


def test_represented_defendant_gets_own_address_and_not_plaintiff_address():
    text = TEXT.replace('被告二：虚构甲。', '被告二：虚构甲，住址：示例市测试路9号。')
    fields, _, _ = run(text, client='虚构甲')
    assert fields['地址'] == '示例市测试路9号'
    fields, _, _ = run(client='虚构甲')
    assert not fields.get('地址')


@pytest.mark.parametrize('details', [
    '法定代表人：虚构乙，住所地演示路。',
    '委托诉讼代理人：虚构乙，地址演示路。',
    '原住所地演示路，现住所地另一路。',
    '住所地演示路，住所地另一路。',
    '住所地待核。', '住所地不详。', '住所地演示市，示例区9号。',
    '住所地演示路？', '住所地演示路，已迁出。',
])
def test_qualified_competing_and_other_person_addresses_are_not_guessed(details):
    fields, _, _ = run(TEXT.replace('住所地演示路。', details))
    assert not fields.get('地址')


def test_address_human_blank_conflict_and_source_changes():
    fields, _, _ = run(manual={'地址': ''}, extra={'地址': ''})
    assert fields['地址'] == ''
    fields, _, _ = run(extra={'地址': '另一地址'})
    assert fields['地址'] == '另一地址'
    assert any(c['field'] == '地址' for c in fields['_field_conflicts'])
    fields, _, _ = run()
    ref = deepcopy(fields['_provenance']['地址'][0])
    fields['委托人'] = '虚构甲'
    assert current_support(ref, fields) is None
    fields, _, _ = run()
    fields['_pleading_parties_source']['pages'][0]['quote'] += '\n修订'
    assert current_support(ref, fields) is None
