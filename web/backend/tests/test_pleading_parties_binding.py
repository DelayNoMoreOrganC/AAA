from copy import deepcopy
from app.core.v4_bridge import init_v4_path
from app.services.field_assurance import field_assurance
from app.services.party_binding_state import reconcile_party_bindings
from app.services.evidence_links import supporting_refs

init_v4_path()
from pleading_parties import recall
from pdf_doc_locator import DocumentUnit


def fixture(text_override=None):
    text = '民事起诉状\n原告：虚构银行，住所地示例市样例路8号。\n被告一：虚构甲。被告二：虚构乙。\n案由：借款合同纠纷。\n诉讼请求：偿还借款。'
    if text_override is not None:
        text = text_override
    contract = '委托人（甲方）：虚构银行。'
    fields = {'委托人': '虚构银行'}
    refs = {'委托人': [{'method': 'local_agent', 'value': '虚构银行', 'quote': contract, 'source_path': 'contract.pdf', 'page': 1}]}
    conflicts = []
    cache = {('pleading.pdf', 1): text, ('contract.pdf', 1): contract}
    units = [DocumentUnit(0, 'complaint', 0, 0, '民事起诉状', source_path='pleading.pdf', confidence=.95)]
    recall(fields, refs, conflicts, page_cache=cache, allowed_sources=set(cache), document_units=units,
           manual_fields={}, method='local_agent', fact_review=[])
    fields.update(_provenance=refs, _field_conflicts=conflicts)
    manifest = [{'path': name, 'pages': 1, 'file_id': name} for name in ('pleading.pdf', 'contract.pdf')]
    return fields, manifest


def test_short_credit_code_label_address_reaches_original_form_and_linked_sources():
    from app.services.original_template_service import _values
    text = ('民事起诉状\n原告：虚构银行，住所：示例路8号901-910室、6号首层9-12号，'
        '统一信用代码：DEMO000001，负责人：虚构丁。\n被告：虚构乙。\n诉讼请求：偿还借款。')
    fields, manifest = fixture(text)
    address = '示例路8号901-910室、6号首层9-12号'
    assert _values('立案审批表', fields, '', {})['地址'] == address
    badge = field_assurance('地址', address, fields, source_manifest=manifest)
    assert badge['status'] == 'source_supported' and badge['source_count'] == 2
    assert reconcile_party_bindings(fields, {}, manifest[:1])['地址'] == ''
    fields['委托人'] = '虚构乙'
    assert reconcile_party_bindings(fields, {}, manifest)['地址'] == ''


def test_source_badges_require_both_pleading_and_client_foundation_in_case_scope():
    fields, manifest = fixture()
    badge = field_assurance('对方当事人', fields['对方当事人'], fields, source_manifest=manifest)
    assert badge['status'] == 'source_supported' and badge['source_count'] == 2
    ref = fields['_provenance']['对方当事人'][0]
    assert supporting_refs(ref, fields, manifest[:1]) is None
    assert reconcile_party_bindings(fields, {}, manifest) == fields


def test_client_change_clears_automatic_parties_but_keeps_litigation_direction():
    fields, manifest = fixture(); fields['委托人'] = '虚构甲'
    result = reconcile_party_bindings(fields, {}, manifest)
    assert result['当事人'] == result['对方当事人'] == ''
    assert result['案件或项目名称'] == fields['案件或项目名称']
    assert result['_provenance']['对方当事人'] == fields['_provenance']['对方当事人']


def test_removed_pleading_clears_case_name_and_human_values_remain():
    fields, manifest = fixture()
    result = reconcile_party_bindings(fields, {}, manifest[1:])
    assert result['案件或项目名称'] == result['对方当事人'] == ''
    manual = reconcile_party_bindings(fields, {'案件或项目名称': '人工标题', '对方当事人': ''}, manifest[1:])
    assert manual['案件或项目名称'] == '人工标题' and manual['对方当事人'] == ''


def test_changed_bundle_cannot_certify_an_old_name():
    fields, manifest = fixture()
    fields['_pleading_parties_source']['pages'][0]['quote'] = fields['_pleading_parties_source']['pages'][0]['quote'].replace('虚构乙', '虚构丙')
    assert field_assurance('案件或项目名称', fields['案件或项目名称'], fields, source_manifest=manifest)['status'] == 'unverified'
    assert reconcile_party_bindings(fields, {}, manifest)['案件或项目名称'] == ''


def test_address_source_scope_client_change_and_human_override():
    fields, manifest = fixture()
    assert fields['地址'] == '示例市样例路8号'
    badge = field_assurance('地址', fields['地址'], fields, source_manifest=manifest)
    assert badge['status'] == 'source_supported' and badge['source_count'] == 2
    assert reconcile_party_bindings(fields, {}, manifest)['地址'] == fields['地址']
    for scope in (manifest[:1], manifest[1:]):
        assert reconcile_party_bindings(fields, {}, scope)['地址'] == ''
    changed = deepcopy(fields); changed['委托人'] = '虚构甲'
    assert reconcile_party_bindings(changed, {}, manifest)['地址'] == ''
    changed = deepcopy(fields); changed['_pleading_parties_source']['pages'][0]['quote'] += '\n修订'
    assert reconcile_party_bindings(changed, {}, manifest)['地址'] == ''
    assert reconcile_party_bindings(changed, {'地址': '人工地址'}, manifest)['地址'] == '人工地址'
    assert reconcile_party_bindings(changed, {'地址': ''}, manifest)['地址'] == ''
