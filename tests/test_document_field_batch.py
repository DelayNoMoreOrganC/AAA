"""Transport packing contracts only; no PDFs, OCR or provider calls."""
from copy import deepcopy
import pytest
import document_field_batch as batch


def job(identity,selection,kind='core'):
    return {'document':{'id':identity},'selection':selection,'compatibility':('standard','trial',kind)}


def test_groups_preserve_identity_order_and_page_budget():
    jobs=[job('d1',['1','2','3','4']),job('d2',['5','6','7','8']),job('d3',['9'])]
    result=list(batch.groups(jobs,batch.POLICY))
    assert [[j['document']['id'] for j in group] for group in result]==[['d1','d2','d3']]
    legacy=list(batch.groups(jobs,batch.LEGACY_POLICY))
    assert [[j['document']['id'] for j in group] for group in legacy]==[['d1','d2']]
    jobs[1]['compatibility']=None
    assert list(batch.groups(jobs,batch.POLICY))==[]


def test_legacy_policy_stays_frozen_and_new_clear_mixed_pages_only_share_transport():
    from types import SimpleNamespace
    unit=SimpleNamespace(doc_type='complaint',confidence=.9)
    doc={'keys':['p'],'role':'standard','stage':'trial'}
    plan={'selected_page_ids':['p']}
    row={'observation':{'quality':'clear','writing':'mixed','suggested_rotation':0}}
    assert batch.validated_policy(batch.LEGACY_POLICY)==batch.LEGACY_POLICY
    assert not batch.eligible(unit,doc,{'p':row},plan,policy=batch.LEGACY_POLICY)
    assert batch.eligible(unit,doc,{'p':row},plan,policy=batch.POLICY)
    for change in ({'writing':'handwritten'},{'quality':'blurred'},{'suggested_rotation':90}, {'writing':'unknown'}):
        altered={**row,'observation':{**row['observation'],**change}}
        assert not batch.eligible(unit,doc,{'p':altered},plan,policy=batch.POLICY)
    assert not batch.eligible(unit,doc,{'p':{**row,'_boundary_unresolved':True}},plan,policy=batch.POLICY)


def test_payload_partitions_preserve_every_image_and_defer_single_members():
    prepared=[]
    for index,images in enumerate((6,6,6,6)):
        prepared.append(dict(job(f'd{index+1}',[f'p{index+1}']),
            messages=[{}, {'content':[{'type':'image_url','image_url':{'url':f'image-{index}-{n}'}} for n in range(images)]}]))
    before=deepcopy(prepared)
    assert batch.messages(prepared,'system') is None
    chunks=batch.payload_partitions(prepared,'system')
    assert [[j['document']['id'] for j in c] for c in chunks]==[['d1','d2'],['d3','d4']]
    assert all(batch.messages(c,'system') for c in chunks) and prepared==before
    prepared[0]['messages'][1]['content']*=3
    chunks=batch.payload_partitions(prepared,'system')
    assert len(chunks[0])==1 and [j for c in chunks for j in c]==prepared


@pytest.mark.parametrize('change',['bool','extra','more_pages'])
def test_policy_cannot_silently_expand_frozen_batch(change):
    policy=dict(batch.POLICY)
    if change=='bool':policy['version']=True
    elif change=='extra':policy['unsafe']=True
    else:policy['field_pages']=9
    with pytest.raises(ValueError):batch.validated_policy(policy)


def test_rendered_payload_limits_fall_back_before_dispatch(monkeypatch):
    prepared=[dict(job('d1',['p1']),messages=[{}, {'content':[{'type':'image_url','image_url':{'url':'x'}}]*13}])]
    assert batch.messages(prepared,'system') is None
    prepared[0]['messages'][1]['content']=[{'type':'text','text':'x'*200}]
    monkeypatch.setattr(batch,'MAX_BATCH_BODY_BYTES',100)
    assert batch.messages(prepared,'system') is None


def test_parser_does_not_mutate_or_accept_unseen_source_pages():
    prepared=[job('d1',['p1']),job('d2',['p2'])]
    response={'tool':'record_documents','documents':[
        {'document_id':key,'action':{'tool':'record_fields','document_id':key,'facts':[]}} for key in ('d1','d2')]}
    before=deepcopy(response)
    assert set(batch.actions(response,prepared))=={'d1','d2'} and response==before
    response['documents'][0]['action']['facts']=[{'page_id':'p2'}]
    with pytest.raises(ValueError,match='SOURCE_SCOPE'):batch.actions(response,prepared)
