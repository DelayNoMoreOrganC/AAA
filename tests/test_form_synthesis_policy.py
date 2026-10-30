"""Per-cell rule invalidation; existing metadata writer fixture, no provider."""
from copy import deepcopy
import form_synthesis as synthesis
import form_cell_contracts as contracts
from tests.test_form_synthesis import run


def references(fields):
    return {key: refs[-1] for key, refs in fields['_provenance'].items()
            if refs and refs[-1].get('binding') == synthesis.BINDING}


def test_unrelated_global_policy_version_does_not_clear_current_cell_contract(tmp_path, monkeypatch):
    fields, _, _, _, _, _ = run(tmp_path)
    monkeypatch.setattr(synthesis, 'VERSION', synthesis.VERSION + 1)
    assert all(synthesis.current_support(ref, fields) is not None for ref in references(fields).values())


def test_changed_cell_rule_only_invalidates_that_cell_and_retains_prior_text(tmp_path, monkeypatch):
    fields, _, _, _, units, manifest = run(tmp_path)
    before = deepcopy(fields)
    rules = deepcopy(contracts.BUSINESS)
    rules['nonlit']['结案小结'].append('新增规则协议探针')
    monkeypatch.setattr(contracts, 'BUSINESS', rules)
    refs = references(fields)
    assert synthesis.current_support(refs['结案小结'], fields) is None
    assert all(synthesis.current_support(ref, fields) is not None for key, ref in refs.items() if key != '结案小结')
    synthesis.discard_stale(fields, {}, manifest, units)
    assert fields['结案小结'] == ''
    assert all(fields[key] == before[key] for key in refs if key != '结案小结')
    assert fields[synthesis.KEY] == before[synthesis.KEY] and fields['_provenance'] == before['_provenance']
    assert fields['_form_synthesis_status']['fields']['结案小结'] == 'policy_review_required'


def test_shared_semantic_instruction_change_still_requires_all_cells_review(tmp_path, monkeypatch):
    fields, _, _, _, _, _ = run(tmp_path)
    monkeypatch.setattr(synthesis, 'REVIEW_SYSTEM', synthesis.REVIEW_SYSTEM + '\nNew semantic instruction')
    assert all(synthesis.current_support(ref, fields) is None for ref in references(fields).values())


def test_old_bundle_cannot_invent_missing_cell_contracts(tmp_path):
    fields, _, _, _, units, manifest = run(tmp_path)
    bundle = fields[synthesis.KEY]
    bundle.pop('cell_contracts'); bundle['version'] = 1
    for ref in references(fields).values(): ref['bundle_digest'] = synthesis.digest(bundle)
    originals = deepcopy(bundle['fields'])
    synthesis.discard_stale(fields, {}, manifest, units)
    assert all(fields[key] == '' for key in originals)
    assert bundle['fields'] == originals and 'cell_contracts' not in bundle
    assert all(code == 'policy_review_required' for code in fields['_form_synthesis_status']['fields'].values())


def test_actual_material_change_is_not_reported_as_rule_change(tmp_path):
    fields, _, _, _, units, manifest = run(tmp_path)
    synthesis.discard_stale(fields, {}, [{**manifest[0], 'sha256': 'changed'}], units)
    assert all(code == 'source_review_required' for code in fields['_form_synthesis_status']['fields'].values())


def test_human_blank_and_text_survive_policy_update(tmp_path, monkeypatch):
    fields, _, _, _, units, manifest = run(tmp_path)
    monkeypatch.setattr(synthesis, 'SYSTEM', synthesis.SYSTEM + '\nChanged rule')
    fields['结案小结'] = ''; fields['审（办）结果'] = '人工填写'
    synthesis.discard_stale(fields, {'结案小结': '', '审（办）结果': '人工填写'}, manifest, units)
    assert fields['结案小结'] == '' and fields['审（办）结果'] == '人工填写'
    assert '结案小结' not in fields['_form_synthesis_status']['fields']


def test_rule_change_with_stale_visual_sources_requires_source_review(tmp_path, monkeypatch):
    fields, _, _, _, units, manifest = run(tmp_path)
    monkeypatch.setattr(synthesis, 'SYSTEM', synthesis.SYSTEM + '\nChanged rule')
    monkeypatch.setattr(synthesis.visual_sources, 'current_sources', lambda *a, **k: False)
    synthesis.discard_stale(fields, {}, manifest, units)
    assert all(code == 'source_review_required' for code in fields['_form_synthesis_status']['fields'].values())


def test_business_alias_matches_but_new_business_invalidates(tmp_path):
    fields, _, _, _, _, _ = run(tmp_path)
    fields['案件类别'] = '非诉'
    assert all(synthesis.current_support(ref, fields) is not None for ref in references(fields).values())
    fields['案件类别'] = '刑事'
    assert all(synthesis.current_support(ref, fields) is None for ref in references(fields).values())


def test_malformed_cell_contract_never_falls_back_to_global_version(tmp_path):
    fields, _, _, _, _, _ = run(tmp_path)
    fields[synthesis.KEY]['cell_contracts'] = None
    for ref in references(fields).values():ref['bundle_digest'] = synthesis.digest(fields[synthesis.KEY])
    assert all(synthesis.current_support(ref, fields) is None for ref in references(fields).values())
