from copy import deepcopy
from app.core.v4_bridge import init_v4_path
from app.services.evidence_links import supporting_refs
from app.services.field_assurance import field_assurance
from app.services.party_binding_state import reconcile_party_bindings

init_v4_path()
from fee_settlement_evidence import FIELDS
from source_fact_recall import recall_cached_source_facts


def fixture():
    number = '（2026）粤0999民初6801号'
    client = '委托人（甲方）：虚构银行。'
    case = '本案案号：' + number + '。'
    settlement = ('律师费结算单\n委托人：虚构银行\n案号：' + number + '\n'
        '应收业务费：5000元\n已收业务费：2000元\n尚欠业务费：3000元\n应退业务费：0元')
    fields = {'委托人': '虚构银行', '案号': number}
    refs = {key: [{'method': 'local_agent', 'value': fields[key], 'quote': text, 'source_path': path, 'page': 1}]
        for key, text, path in [('委托人', client, 'contract.pdf'), ('案号', case, 'judgment.pdf')]}
    cache = {('contract.pdf',1):client, ('judgment.pdf',1):case, ('fees.pdf',1):settlement}
    conflicts = []
    recall_cached_source_facts(fields, refs, conflicts, page_cache=cache, allowed_sources=set(cache), fact_review=[])
    fields.update(_provenance=refs, _field_conflicts=conflicts)
    manifest = [{'path': path, 'pages': 1, 'file_id': path} for path in ('contract.pdf','judgment.pdf','fees.pdf')]
    return fields, manifest


def test_all_balances_have_case_and_client_anchors():
    fields, manifest = fixture()
    for key in FIELDS:
        result = field_assurance(key, fields[key], fields, source_manifest=manifest)
        assert result['status'] == 'source_supported' and result['source_count'] == 3
        assert supporting_refs(fields['_provenance'][key][-1], fields, manifest) is not None
    assert reconcile_party_bindings(fields, {}, manifest) == fields


def test_removed_fee_or_identity_sources_clear_automatic_balances_only():
    fields, manifest = fixture()
    for missing in manifest:
        current = [row for row in manifest if row != missing]
        out = reconcile_party_bindings(fields, {}, current)
        assert all(out[key] == '' for key in FIELDS)
        manual = reconcile_party_bindings(fields, {'已收业务费': '人工值', '尚欠业务费': ''}, current)
        assert manual['已收业务费'] == '人工值' and manual['尚欠业务费'] == ''
        assert out['_provenance'] == fields['_provenance']


def test_identity_change_or_target_conflict_cannot_keep_verified_amount_badges():
    fields, manifest = fixture()
    changed = deepcopy(fields); changed['案号'] = '（2026）粤0999民初999号'
    assert all(reconcile_party_bindings(changed, {}, manifest)[key] == '' for key in FIELDS)
    changed = deepcopy(fields); changed['_field_conflicts'] = [{'field':'已收业务费','values':['2000元','2500元']}]
    assert field_assurance('已收业务费', '2000元', changed, source_manifest=manifest)['status'] == 'conflict'


def test_provisional_model_quote_cannot_bypass_stale_bound_fee_source():
    fields, manifest = fixture()
    for field in FIELDS:
        ref = fields['_provenance'][field][0]
        raw = {k: ref[k] for k in ('source_path','page','quote','value','method')}
        fields['_provenance'][field].insert(0, raw)
    fields['委托人'] = '虚构另一银行'
    out = reconcile_party_bindings(fields, {}, manifest)
    assert all(out[key] == '' for key in FIELDS)
    assert field_assurance('已收业务费', '2000元', fields, source_manifest=manifest)['status'] == 'unverified'


def test_unbound_model_amount_is_not_a_current_source_badge():
    fields, manifest = fixture()
    bound = fields['_provenance']['已收业务费'][0]
    fields['_provenance']['已收业务费'] = [{k: bound[k] for k in ('source_path','page','quote','value','method')}]
    assert field_assurance('已收业务费', fields['已收业务费'], fields, source_manifest=manifest)['status'] == 'unverified'


def review_issues(fields, manifest):
    from types import SimpleNamespace
    from app.services.task_workflow import analysis_issues
    fields = deepcopy(fields)
    fields['_fact_review'] = [dict(field='已收业务费', source_path='fees.pdf', page=1,
        resolution='field_supported_by_cached_source', reason='原候选引用不足')]
    analysis = SimpleNamespace(fields=fields, doc_spans=[], case_type='civil')
    manifest = [dict(row, filename=row['path']) for row in manifest]
    return [row for row in analysis_issues(analysis, manifest) if row['kind'] == 'fact_review']


def test_current_settlement_recheck_removes_only_obsolete_refusal():
    fields, manifest = fixture()
    assert review_issues(fields, manifest) == []
    assert review_issues(fields, [])  # Source removal invalidates the resolution.
    for key, value in [('委托人', '虚构另一银行'), ('案号', '（2026）粤0999民初99号'), ('已收业务费', '9000元')]:
        changed = deepcopy(fields); changed[key] = value
        assert review_issues(changed, manifest)
    changed = deepcopy(fields)
    changed['_field_conflicts'] = [dict(field='已收业务费', values=['2000元', '9000元'])]
    assert review_issues(changed, manifest)
    changed = deepcopy(fields)
    for ref in changed['_provenance']['已收业务费']:
        ref.pop('binding', None)
    assert review_issues(changed, manifest)  # A resolution flag alone proves nothing.


def test_recheck_does_not_hide_a_different_page_or_unresolved_receipt():
    fields, manifest = fixture()
    for ref in fields['_provenance']['已收业务费']:
        ref['page'] = 2
    assert review_issues(fields, [dict(row, pages=2) for row in manifest])
