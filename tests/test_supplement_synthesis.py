"""Bounded supplement writing protocol; no provider/recognition benchmark."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
import hashlib, json
import pytest
import form_synthesis as fs
from supplement_synthesis import SupplementSynthesisContext
from tests.test_form_synthesis import run, Model


def setup(tmp_path, manual=None):
    fields, _, _, _, old_units, old_manifest = run(tmp_path)
    path = tmp_path/'addition.pdf'; path.write_bytes(b'supplement protocol')
    manifest = old_manifest + [{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'pages':1,'file_id':'addition'}]
    unit = NS(source_path=str(path),start_page=0,end_page=0,doc_type='legal_work',doc_id=0,confidence=.95)
    cache = {(str(path),1):'补充工作记录：公证处已出具公证书。'}
    context = SupplementSynthesisContext(case_type='nonlit', fields=fields, units=old_units,
        previous_manifest=old_manifest,current_manifest=manifest,manual=manual or {})
    combined = deepcopy(old_units)+[deepcopy(unit)]; combined[-1].doc_id=3
    return fields, context, [unit], cache, manifest, combined


def test_combined_read_sources_written_once_and_adopted_with_rebound_ids(tmp_path):
    fields, context, units, cache, manifest, combined = setup(tmp_path)
    original = deepcopy(fields); client=Model()
    status=context.generate(client,{}, {}, [],units,cache,set(cache),case_type='nonlit')
    assert len(client.calls)==2 and status['scope']=='combined_read_sources_after_supplement'
    payload=json.loads(client.calls[0][-1]['content'])
    assert len(payload['sources'])==3 and set(s['doc_id'] for s in payload['sources'])=={'1','2','3'}
    assert all('source_path' not in s for s in payload['sources'])
    assert fields==original
    assert context.apply(fields,combined,manifest)
    assert fs.scope_supported(fields,manifest,combined)
    assert all(fs.current_support(fields['_provenance'][key][-1],fields) is not None for key in fs.NARRATIVES)
    assert set(fields[fs.KEY]['source_hashes'])=={fs._path(r['path']) for r in manifest}


def test_manual_blank_is_retained_across_combined_generation(tmp_path):
    fields, context, units, cache, manifest, combined=setup(tmp_path,{'案情简介':''})
    client=Model();context.generate(client,{}, {}, [],units,cache,set(cache),case_type='nonlit')
    fields['案情简介']=''
    assert context.apply(fields,combined,manifest) and fields['案情简介']==''
    assert '案情简介' not in json.loads(client.calls[0][-1]['content'])['rules']


def test_real_identity_conflict_blocks_combined_writer(tmp_path):
    fields, context, units, cache, manifest, combined=setup(tmp_path)
    client=Model();status=context.generate(client,{'委托人':'不同主体'}, {}, [],units,cache,set(cache),case_type='nonlit')
    assert status['status']=='identity_conflict' and not client.calls
    assert not context.apply(fields,combined,manifest)


@pytest.mark.parametrize('change',['source','input','classification'])
def test_changes_after_generation_prevent_adoption(tmp_path,change):
    fields,context,units,cache,manifest,combined=setup(tmp_path)
    context.generate(Model(),{}, {}, [],units,cache,set(cache),case_type='nonlit')
    if change=='source':Path(units[0].source_path).write_bytes(b'replaced')
    elif change=='input':fields['委托人']='编辑后的主体'
    else:combined[-1].doc_type='evidence'
    before=deepcopy(fields)
    assert not context.apply(fields,combined,manifest)
    assert all(fields[key]==before[key] for key in fs.NARRATIVES)
    assert fields['_form_synthesis_status']['status']=='supplement_context_changed'


def test_failed_provider_keeps_reason_and_never_retries(tmp_path):
    fields,context,units,cache,manifest,combined=setup(tmp_path)
    context.failed({'status':'provider_failed','requests':1,'fields':{'结案小结':'provider_failed'}})
    assert not context.apply(fields,combined,manifest)
    assert fields['_form_synthesis_status']['status']=='provider_failed'
    from form_drafts import derive_form_drafts
    projected=derive_form_drafts(fields,combined,source_manifest=manifest)
    assert projected['_form_synthesis_status']['fields']['结案小结']=='provider_failed'
    assert projected['_form_synthesis_status']['refresh_status']=='provider_failed'
    assert projected['结案小结']==''


def test_context_cannot_be_reused_for_an_extra_paid_round(tmp_path):
    _,context,units,cache,_,_=setup(tmp_path)
    client=Model();context.generate(client,{}, {}, [],units,cache,set(cache),case_type='nonlit')
    with pytest.raises(ValueError,match='CONTEXT_INVALID'):
        context.generate(client,{}, {}, [],units,cache,set(cache),case_type='nonlit')
    assert len(client.calls)==2


def test_other_case_source_cannot_be_injected(tmp_path):
    _,context,units,cache,_,_=setup(tmp_path)
    units[0].source_path=str(tmp_path/'foreign.pdf')
    with pytest.raises(ValueError,match='SCOPE_INVALID'):
        context.generate(Model(),{}, {}, [],units,cache,set(cache),case_type='nonlit')


def test_partial_historical_excerpts_are_not_reconstructed_as_full_pages(tmp_path):
    fields, _, units, cache, manifest, combined=setup(tmp_path)
    bundle=fields[fs.KEY]
    bundle['coverage']['documents'][0]['missing_or_partial_pages']=[1]
    for refs in fields['_provenance'].values():refs[-1]['bundle_digest']=fs.digest(bundle)
    context=SupplementSynthesisContext(case_type='nonlit',fields=fields,units=combined[:-1],
        previous_manifest=manifest[:-1],current_manifest=manifest,manual={})
    assert (combined[0].source_path,1) not in context._prior_cache()


def test_replacing_prior_file_is_not_an_additive_context(tmp_path):
    fields, _, _, _, manifest, combined=setup(tmp_path)
    changed=deepcopy(manifest);changed[0]['sha256']='changed'
    with pytest.raises(ValueError,match='SCOPE_INVALID'):
        SupplementSynthesisContext(case_type='nonlit',fields=fields,units=combined[:-1],
            previous_manifest=manifest[:-1],current_manifest=changed,manual={})


def test_prior_unresolved_identity_issue_blocks_writer_even_without_field_metadata(tmp_path):
    fields, _, units, cache, manifest, combined=setup(tmp_path)
    context=SupplementSynthesisContext(case_type='nonlit',fields=fields,units=combined[:-1],
        previous_manifest=manifest[:-1],current_manifest=manifest,manual={},pending_conflicts=[{'field':'委托人'}])
    client=Model()
    status=context.generate(client,{}, {}, [],units,cache,set(cache),case_type='nonlit')
    assert status['status']=='identity_conflict' and not client.calls


def test_missing_old_reading_pool_is_disclosed_in_generated_quality_metadata(tmp_path):
    fields, _, units, cache, manifest, combined=setup(tmp_path)
    fields.pop(fs.KEY)
    context=SupplementSynthesisContext(case_type='nonlit',fields=fields,units=combined[:-1],
        previous_manifest=manifest[:-1],current_manifest=manifest,manual={})
    class PartialModel:
        def complete(self,messages):
            payload=json.loads(messages[-1]['content']);source=payload['sources'][0]
            row={'claims':[{'text':'公证处已出具公证书。','evidence':[{'id':source['id'],'quote':source['text']}]}],'missing':[]}
            if 'candidates' in payload:row.update(supported=True,reason='ok')
            return {'fields':{'结案小结':row}}
    context.generate(PartialModel(),{}, {}, [],units,cache,set(cache),case_type='nonlit')
    assert context.apply(fields,combined,manifest)
    assert 'incomplete_source' in fields[fs.KEY]['fields']['结案小结']['missing']
    assert 'incomplete_source' not in fields['结案小结']


def test_independent_readings_supply_old_sources_when_previous_writer_has_no_bundle(tmp_path):
    from tests.test_form_synthesis import fixture
    from page_reading_store import PageReadingStore, path_key
    from agent_trace import source_identity
    fields, _, units, cache, manifest, combined = setup(tmp_path)
    _, old_cache, _ = fixture(tmp_path)
    fields.pop(fs.KEY)
    old = manifest[0]
    sources = [{'path_sha256':path_key(old['path']),'sha256':old['sha256'],'pages':old['pages']}]
    args = (tmp_path/'readings',tmp_path,{'org_id':'org','case_id':'case','task_id':1},sources,'a'*64)
    store = PageReadingStore(*args)
    identity=source_identity(old['path'],old['pages'])
    for (_,page),text in old_cache.items():
        store.save(identity,page,0,text=text,blocks=[],view={'method':'text_layer'})
        store.mark_eligible(identity,page,0)
    context=SupplementSynthesisContext(case_type='nonlit',fields=fields,units=combined[:-1],
        previous_manifest=manifest[:-1],current_manifest=manifest,manual={},
        prior_readings=PageReadingStore(*args,readonly=True))
    writer=Model()
    status=context.generate(writer,{}, {}, [],units,cache,set(cache),case_type='nonlit')
    assert status['prior_read_pages']==2 and len(writer.calls)==2
    assert context.apply(fields,combined,manifest)
    assert '核对草稿' in fields['结案小结']
    assert fs.current_support(fields['_provenance']['结案小结'][-1],fields) is not None
    assert not fields[fs.KEY]['coverage']['documents'][0]['missing_or_partial_pages']


def test_ambiguous_readings_do_not_fall_back_to_old_narrative_excerpt(tmp_path):
    from page_reading_store import PageReadingStore, path_key
    from agent_trace import source_identity
    fields,_,_,_,manifest,combined=setup(tmp_path)
    old=manifest[0]
    args=(tmp_path/'readings',tmp_path,{'org_id':'org','case_id':'case','task_id':1},
          [{'path_sha256':path_key(old['path']),'sha256':old['sha256'],'pages':old['pages']}],'a'*64)
    store=PageReadingStore(*args);identity=source_identity(old['path'],old['pages'])
    for rotation in (0,90):
        store.save(identity,1,rotation,text=f'不同方向的文字{rotation}',blocks=[],view={})
        store.mark_eligible(identity,1,rotation)
    context=SupplementSynthesisContext(case_type='nonlit',fields=fields,units=combined[:-1],
        previous_manifest=manifest[:-1],current_manifest=manifest,manual={},
        prior_readings=PageReadingStore(*args,readonly=True))
    assert (old['path'],1) in context._bundle_cache()
    assert (old['path'],1) not in context._prior_cache()
