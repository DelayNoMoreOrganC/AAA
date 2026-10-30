"""Per-cell policy repair protocol; fake transport is not recognition evidence."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import form_synthesis as synthesis
from tests.test_form_synthesis import run, Model


def change_rule(monkeypatch):
    original=synthesis._cell_contract
    monkeypatch.setattr(synthesis,'_cell_contract',lambda field,kind:
        {**original(field,kind),'test_revision':2} if field=='结案小结' else original(field,kind))


def test_only_changed_cell_is_written_and_other_proofs_stay_current(tmp_path,monkeypatch):
    fields,_,_,_,units,manifest=run(tmp_path)
    original=deepcopy(fields)
    change_rule(monkeypatch)
    targets=synthesis.policy_repair_targets(fields,{},manifest,units)
    assert targets==['结案小结']
    writer=Model()
    status=synthesis.generate(writer,fields,fields['_provenance'],[],units,{},set(),case_type='nonlit',
        source_manifest=manifest,target_fields=targets,use_saved_sources=True)
    assert status['status']=='generated' and len(writer.calls)==2
    assert set(json.loads(writer.calls[0][-1]['content'])['rules'])=={'结案小结'}
    assert fields[synthesis.KEY]['sources']==original[synthesis.KEY]['sources']
    for key in synthesis.NARRATIVES:
        if key!='结案小结':assert fields[key]==original[key]
        assert synthesis.current_support(fields['_provenance'][key][-1],fields) is not None
    assert not synthesis.policy_repair_targets(fields,{},manifest,units)


def test_stale_cell_cleared_by_projection_can_be_repaired_without_losing_candidate(tmp_path,monkeypatch):
    fields,_,_,_,units,manifest=run(tmp_path);change_rule(monkeypatch)
    synthesis.discard_stale(fields,{},manifest,units)
    assert fields['结案小结']=='' and fields[synthesis.KEY]['fields']['结案小结']['value']
    assert synthesis.policy_repair_targets(fields,{},manifest,units)==['结案小结']


@pytest.mark.parametrize('reason',['manual_blank','human_proof','untracked_edit','input_change','manifest_change','bad_digest'])
def test_automatic_policy_repair_does_not_override_uncertain_or_human_state(tmp_path,monkeypatch,reason):
    fields,_,_,_,units,manifest=run(tmp_path);change_rule(monkeypatch);manual={}
    if reason=='manual_blank':manual['结案小结']='';fields['结案小结']=''
    elif reason=='human_proof':fields['_provenance']['结案小结'].append({'method':'human','value':fields['结案小结']})
    elif reason=='untracked_edit':fields['结案小结']='未知来源的修改'
    elif reason=='input_change':fields['委托人']='另一个主体'
    elif reason=='manifest_change':manifest[0]['sha256']='changed'
    else:fields[synthesis.KEY]['sources'][0]['text']='被改写'
    assert synthesis.policy_repair_targets(fields,manual,manifest,units)==[]


def test_actual_source_change_prevents_paid_writing(tmp_path,monkeypatch):
    fields,_,_,_,units,manifest=run(tmp_path);change_rule(monkeypatch)
    Path(manifest[0]['path']).write_bytes(b'changed');writer=Model()
    status=synthesis.generate(writer,fields,fields['_provenance'],[],units,{},set(),case_type='nonlit',
        source_manifest=manifest,target_fields=['结案小结'],use_saved_sources=True)
    assert status['status']=='source_changed' and not writer.calls


def test_review_rejection_keeps_old_candidate_and_unaffected_values(tmp_path,monkeypatch):
    fields,_,_,_,units,manifest=run(tmp_path);change_rule(monkeypatch);original=deepcopy(fields)
    status=synthesis.generate(Model(reject=['结案小结']),fields,fields['_provenance'],[],units,{},set(),
        case_type='nonlit',source_manifest=manifest,target_fields=['结案小结'],use_saved_sources=True)
    assert status['status']=='review_rejected' and fields==original


def test_legacy_excerpt_only_bundle_never_gains_invented_full_page_coverage(tmp_path):
    fields,_,_,_,units,manifest=run(tmp_path)
    bundle=fields[synthesis.KEY]
    bundle['version']=1;bundle.pop('cell_contracts');bundle['coverage'].pop('documents')
    for refs in fields['_provenance'].values():
        for ref in refs:ref['bundle_digest']=synthesis.digest(bundle)
    sources,coverage=synthesis.saved_source_pool(fields,fields['_provenance'],units,manifest)
    assert sources==bundle['sources']
    assert all(row['complete_pages']==0 and row['missing_or_partial_pages'] for row in coverage['documents'])
    assert 'documents' not in bundle['coverage']
    writer=Model();targets=synthesis.policy_repair_targets(fields,{},manifest,units)
    status=synthesis.generate(writer,fields,fields['_provenance'],[],units,{},set(),case_type='nonlit',
        source_manifest=manifest,target_fields=targets,use_saved_sources=True)
    assert status['status']=='generated'
    assert all('incomplete_source' in row['missing'] for row in fields[synthesis.KEY]['fields'].values())
    assert all('incomplete_source' not in fields[key] for key in synthesis.NARRATIVES)
