"""Protocol-only resume checks; no provider or case accuracy claim."""
from copy import deepcopy
import json
from pathlib import Path

import form_cell_contracts as contracts
import form_synthesis as synthesis
from tests.test_form_synthesis import run, Model, fixture


def again(fields, units, cache, manifest, client=None, **kwargs):
    client = client or Model()
    status = synthesis.generate(client, fields, fields['_provenance'], [], units,
        cache, set(cache), case_type='nonlit', source_manifest=manifest, **kwargs)
    return status, client


def test_unchanged_verified_cells_do_not_call_or_change_proofs(tmp_path):
    fields, _, _, _, units, manifest = run(tmp_path)
    _, cache, _ = fixture(tmp_path)
    before = deepcopy(fields)
    status, client = again(fields, units, cache, manifest)
    assert status['status'] == 'reused' and status['requests'] == 0
    assert not client.calls and fields == before
    assert set(status['fields'].values()) == {'reused'}


def test_one_changed_cell_rewrites_only_it_and_keeps_other_proofs(tmp_path, monkeypatch):
    fields, _, _, _, units, manifest = run(tmp_path)
    _, cache, _ = fixture(tmp_path)
    before = deepcopy(fields)
    business = deepcopy(contracts.BUSINESS)
    business['nonlit']['结案小结'].append('规则修订协议探针')
    monkeypatch.setattr(contracts, 'BUSINESS', business)
    status, client = again(fields, units, cache, manifest)
    assert len(client.calls) == status['requests'] == 2
    assert list(json.loads(client.calls[0][-1]['content'])['rules']) == ['结案小结']
    for key in synthesis.NARRATIVES:
        assert status['fields'][key] == ('generated' if key == '结案小结' else 'reused')
        assert fields[key] == before[key]
        assert synthesis.current_support(fields['_provenance'][key][-1], fields) is not None
        assert fields['_provenance'][key][0] == before['_provenance'][key][0]


def test_target_review_rejection_does_not_discard_other_cells(tmp_path, monkeypatch):
    fields, _, _, _, units, manifest = run(tmp_path)
    _, cache, _ = fixture(tmp_path)
    business = deepcopy(contracts.BUSINESS)
    business['nonlit']['结案小结'].append('规则修订协议探针')
    monkeypatch.setattr(contracts, 'BUSINESS', business)
    before = deepcopy(fields)
    status, client = again(fields, units, cache, manifest, Model(reject=('结案小结',)))
    assert status['status'] == 'review_rejected' and len(client.calls) == 2
    assert fields == before
    assert all(synthesis.current_support(fields['_provenance'][key][-1], fields) is not None
               for key in synthesis.NARRATIVES if key != '结案小结')


def test_changed_cached_reading_scope_cannot_reuse(tmp_path):
    fields, _, _, _, units, manifest = run(tmp_path)
    _, cache, _ = fixture(tmp_path)
    cache[units[0].source_path, 1] += '补充原文。'
    status, client = again(fields, units, cache, manifest)
    assert len(client.calls) == 2 and 'reused' not in status['fields'].values()


def test_stale_manifest_prevents_any_request_and_mutation(tmp_path):
    fields, _, _, _, units, manifest = run(tmp_path)
    _, cache, _ = fixture(tmp_path)
    Path(units[0].source_path).write_bytes(b'modified')
    before = deepcopy(fields)
    status, client = again(fields, units, cache, manifest)
    assert status['status'] == 'source_changed' and not client.calls and fields == before


def test_source_changed_during_writing_never_rebinds_old_text_to_new_hash(tmp_path):
    units, cache, manifest = fixture(tmp_path)
    fields = {'_provenance': {}}
    class ChangingModel(Model):
        def complete(self, messages):
            result = super().complete(messages)
            if len(self.calls) == 2:
                Path(units[0].source_path).write_bytes(b'changed during review')
            return result
    status, client = again(fields, units, cache, manifest, ChangingModel())
    assert status['status'] == 'source_changed' and len(client.calls) == 2
    assert fields == {'_provenance': {}}


def test_manual_blank_not_regenerated_when_another_cell_needs_review(tmp_path, monkeypatch):
    fields, _, _, _, units, manifest = run(tmp_path)
    _, cache, _ = fixture(tmp_path)
    fields['案情简介'] = ''
    monkeypatch.setattr(synthesis, 'REVIEW_SYSTEM', synthesis.REVIEW_SYSTEM + '\n规则修订')
    status, client = again(fields, units, cache, manifest, manual_fields={'案情简介': ''})
    assert fields['案情简介'] == '' and '案情简介' not in status['fields']
    assert '案情简介' not in json.loads(client.calls[0][-1]['content'])['rules']


def test_segment_identity_contains_target_rules(tmp_path):
    units, cache, manifest = fixture(tmp_path)
    class Segments(Model):
        def begin_segment(self, identity): self.identity = identity
    client = Segments()
    again({'_provenance': {}}, units, cache, manifest, client)
    assert client.identity['targets'] == list(synthesis.NARRATIVES)
    assert set(client.identity['cell_contracts']) == set(synthesis.NARRATIVES)


def test_new_input_conflict_prevents_reusing_old_summary(tmp_path):
    fields, _, _, _, units, manifest = run(tmp_path)
    _, cache, _ = fixture(tmp_path)
    client = Model()
    status = synthesis.generate(client, fields, fields['_provenance'], [{'field': '案号'}],
        units, cache, set(cache), case_type='nonlit', source_manifest=manifest)
    assert len(client.calls) == 2 and 'reused' not in status['fields'].values()
    assert json.loads(client.calls[0][-1]['content'])['accepted_identity']['案号'] is None


def test_protected_current_cell_keeps_its_proof_when_another_cell_changes(tmp_path, monkeypatch):
    fields, _, _, _, units, manifest = run(tmp_path)
    _, cache, _ = fixture(tmp_path)
    business = deepcopy(contracts.BUSINESS)
    business['nonlit']['结案小结'].append('规则修订协议探针')
    monkeypatch.setattr(contracts, 'BUSINESS', business)
    value = fields['案情简介']
    status, client = again(fields, units, cache, manifest, manual_fields={'案情简介': value})
    assert fields['案情简介'] == value and '案情简介' not in status['fields']
    assert synthesis.current_support(fields['_provenance']['案情简介'][-1], fields) is not None
