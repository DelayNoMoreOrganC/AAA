"""Real private journal + transport stub, no model/OCR or real case execution."""
from copy import deepcopy
import json
from types import SimpleNamespace as NS
import pytest
from tests.test_form_synthesis_integration import make
from app.services import form_policy_repair as repair
from app.services.task_sources import source_version
from app.services import recognition_checkpoint
from app import config as app_config
import form_synthesis as synthesis


def setup(tmp_path,monkeypatch):
    fields,manifest,units=make(tmp_path)
    fields['_analysis_metrics']={'analysis_status':'snapshot_reused'}
    manifest[0].update(doc_type='default',filename='source.pdf')
    task=NS(id=1,case_id='case1',revision=1,created_by='user1',source_manifest=manifest,
        source_version=source_version(manifest,'nonlit',''),fields=deepcopy(fields),manual_fields={},issues=[],execution_profile={})
    analysis=NS(fields=fields,case_type='nonlit',doc_spans=units)
    cfg={'extraction':{'mode':'visual_agent'},'vision':{'provider':'deepseek','model':'deepseek-flash','workflow':'document_two_stage'},
         'privacy':{'mode':'cloud','cloud_authorized':True}}
    monkeypatch.setattr(app_config,'ORGS_DIR',tmp_path/'orgs')
    original=synthesis._cell_contract
    monkeypatch.setattr(synthesis,'_cell_contract',lambda field,kind:
        {**original(field,kind),'test_revision':2} if field=='结案小结' else original(field,kind))
    return analysis,task,cfg


class Writer:
    def __init__(self,fail=False,field='结案小结'):
        self.calls=[];self.metrics={'model_requests':0};self.fail=fail;self.field=field
    def complete(self,messages):
        from deepseek_vision_client import DeepSeekVisionError
        self.calls.append(messages);self.metrics['model_requests']+=1
        if self.fail:raise DeepSeekVisionError(self.fail if isinstance(self.fail,str) else 'CONNECTION_FAILED')
        payload=json.loads(messages[-1]['content']);source=payload['sources'][0]
        row={'claims':[{'text':'律师核对草稿并协助递交申请，公证处已出具公证书。',
             'evidence':[{'id':source['id'],'quote':source['text']}]}],'missing':[]}
        if 'candidates' in payload:row.update(supported=True,reason='ok')
        return {'fields':{self.field:row}}


def test_reused_analysis_repairs_once_and_restart_replays_without_paid_calls(tmp_path,monkeypatch):
    analysis,task,cfg=setup(tmp_path,monkeypatch);before=deepcopy(analysis)
    writer=Writer();monkeypatch.setattr(repair,'_client',lambda _:writer)
    status=repair.repair_policy_cells(analysis,task,cfg,'org1',{},[])
    assert status['status']=='generated' and len(writer.calls)==2
    assert status['targets']==['结案小结'] and status['new_page_reads']==0
    assert analysis.fields['审（办）结果']==before.fields['审（办）结果']
    assert synthesis.current_support(analysis.fields['_provenance']['审（办）结果'][-1],analysis.fields) is not None
    assert task.fields==before.fields
    resumed=deepcopy(before);writer=Writer()
    monkeypatch.setattr(repair,'_client',lambda _:writer)
    replay=repair.repair_policy_cells(resumed,task,cfg,'org1',{},[])
    assert replay['status']=='generated' and not writer.calls
    assert replay['metrics']['model_requests']==0
    assert resumed.fields['结案小结']==analysis.fields['结案小结']


@pytest.mark.parametrize('reason',['fresh_analysis','manual_blank','identity_conflict','authorization','business_changed','budget_exhausted'])
def test_no_silent_request_for_fresh_job_human_blank_conflict_or_no_authorization(tmp_path,monkeypatch,reason):
    analysis,task,cfg=setup(tmp_path,monkeypatch);manual={};issues=[]
    monkeypatch.setattr(repair,'_client',lambda _:pytest.fail('must not construct provider'))
    if reason=='fresh_analysis':analysis.fields['_analysis_metrics']={'analysis_status':'completed'}
    elif reason=='manual_blank':manual['结案小结']=''
    elif reason=='identity_conflict':analysis.fields['_field_conflicts']=[{'field':'委托人','resolved':False}]
    elif reason=='business_changed':analysis.case_type='civil'
    elif reason=='budget_exhausted':analysis.fields['_request_budget_stop']={'status':'incomplete'}
    else:
        cfg['privacy']['cloud_authorized']=False
        with pytest.raises(recognition_checkpoint.RecognitionCheckpointError):
            repair.repair_policy_cells(analysis,task,cfg,'org1',manual,issues)
        return
    status=repair.repair_policy_cells(analysis,task,cfg,'org1',manual,issues)
    assert status is None or status['requests']==0


def test_failed_provider_is_not_retried_on_same_job_resume(tmp_path,monkeypatch):
    from recognition_journal import RecognitionJournalError
    analysis,task,cfg=setup(tmp_path,monkeypatch);before=deepcopy(analysis)
    writer=Writer(fail=True);monkeypatch.setattr(repair,'_client',lambda _:writer)
    with pytest.raises(RecognitionJournalError) as error:
        repair.repair_policy_cells(analysis,task,cfg,'org1',{},[])
    assert error.value.code=='REQUEST_UNCERTAIN' and len(writer.calls)==1
    assert analysis.fields==before.fields
    with pytest.raises(RecognitionJournalError):
        repair.repair_policy_cells(deepcopy(before),task,cfg,'org1',{},[])
    assert len(writer.calls)==1


def test_known_provider_rejection_is_reported_without_erasing_old_candidate(tmp_path,monkeypatch):
    analysis,task,cfg=setup(tmp_path,monkeypatch);before=deepcopy(analysis)
    writer=Writer(fail='QUOTA_EXHAUSTED');monkeypatch.setattr(repair,'_client',lambda _:writer)
    status=repair.repair_policy_cells(analysis,task,cfg,'org1',{},[])
    assert status['status']=='provider_failed' and len(writer.calls)==1
    assert analysis.fields[synthesis.KEY]==before.fields[synthesis.KEY]


def test_partial_repair_preserves_rejected_candidate_history_not_stale_visible_value(tmp_path,monkeypatch):
    analysis,task,cfg=setup(tmp_path,monkeypatch);before=deepcopy(analysis)
    current=synthesis._cell_contract
    monkeypatch.setattr(synthesis,'_cell_contract',lambda field,kind:{**current(field,kind),'second_change':True})
    writer=Writer();monkeypatch.setattr(repair,'_client',lambda _:writer)
    status=repair.repair_policy_cells(analysis,task,cfg,'org1',{},[])
    assert status['status']=='partially_repaired' and status['unaccepted_targets']==['审（办）结果']
    assert analysis.fields['审（办）结果']=='' and analysis.fields['结案小结']
    assert analysis.fields['_form_policy_history'][0]['bundle']==before.fields[synthesis.KEY]
    assert synthesis.current_support(analysis.fields['_provenance']['结案小结'][-1],analysis.fields) is not None


def test_partial_repair_can_update_only_rejected_cell_after_its_rule_changes(tmp_path,monkeypatch):
    analysis,task,cfg=setup(tmp_path,monkeypatch)
    original_contract=synthesis._cell_contract
    monkeypatch.setattr(synthesis,'_cell_contract',lambda field,kind:{**original_contract(field,kind),'revision':2})
    first=Writer();monkeypatch.setattr(repair,'_client',lambda _:first)
    repair.repair_policy_cells(analysis,task,cfg,'org1',{},[])
    assert synthesis.policy_repair_targets(analysis.fields,{},task.source_manifest,analysis.doc_spans)==[]
    accepted=analysis.fields['结案小结']
    before=deepcopy(analysis.fields)
    # New rule is the only new input. The failed cell's old record is retained
    # in history, not copied back into the form or used as a source quote.
    monkeypatch.setattr(synthesis,'_cell_contract',lambda field,kind:{**original_contract(field,kind),
        'revision':3 if field=='审（办）结果' else 2})
    assert synthesis.policy_repair_targets(analysis.fields,{},task.source_manifest,analysis.doc_spans)==['审（办）结果']
    assert analysis.fields==before
    from app.services.task_workflow import mark_snapshot_metrics_reused
    mark_snapshot_metrics_reused(analysis)
    assert analysis.fields['_form_policy_attempts']==before['_form_policy_attempts']
    child=deepcopy(task);child.id=2;child.fields=deepcopy(analysis.fields)
    second=Writer(field='审（办）结果');monkeypatch.setattr(repair,'_client',lambda _:second)
    result=repair.repair_policy_cells(analysis,child,cfg,'org1',{},[])
    assert result['targets']==['审（办）结果'] and result['status']=='generated'
    assert len(second.calls)==2 and set(json.loads(second.calls[0][-1]['content'])['rules'])=={'审（办）结果'}
    assert analysis.fields['结案小结']==accepted and analysis.fields['审（办）结果']
    for key in ['结案小结','审（办）结果']:
        assert synthesis.current_support(analysis.fields['_provenance'][key][-1],analysis.fields) is not None
    assert not synthesis.policy_repair_targets(analysis.fields,{},task.source_manifest,analysis.doc_spans)
    assert len(analysis.fields['_form_policy_attempts'])==2


@pytest.mark.parametrize('change',['manual_blank','history_tamper','other_source','untracked_edit','human_proof'])
def test_partial_history_never_overrides_human_or_changed_source(tmp_path,monkeypatch,change):
    analysis,task,cfg=setup(tmp_path,monkeypatch);manual={}
    original_contract=synthesis._cell_contract
    monkeypatch.setattr(synthesis,'_cell_contract',lambda field,kind:{**original_contract(field,kind),'revision':2})
    monkeypatch.setattr(repair,'_client',lambda _:Writer())
    repair.repair_policy_cells(analysis,task,cfg,'org1',{},[])
    monkeypatch.setattr(synthesis,'_cell_contract',lambda field,kind:{**original_contract(field,kind),
        'revision':3 if field=='审（办）结果' else 2})
    if change=='manual_blank':manual['审办结果']=''
    elif change=='history_tamper':analysis.fields['_form_policy_history'][0]['bundle']['fields']['审（办）结果']['value']='tampered'
    elif change=='other_source':task.source_manifest[0]['sha256']='changed'
    elif change=='untracked_edit':analysis.fields['审（办）结果']='human text without receipt'
    else:analysis.fields['_provenance']['审（办）结果'].append({'method':'human','value':''})
    assert not synthesis.policy_repair_targets(analysis.fields,manual,task.source_manifest,analysis.doc_spans)


def test_known_failure_receipt_survives_restart_and_blocks_unchanged_paid_retry(tmp_path,monkeypatch):
    analysis,task,cfg=setup(tmp_path,monkeypatch)
    writer=Writer(fail='QUOTA_EXHAUSTED');monkeypatch.setattr(repair,'_client',lambda _:writer)
    repair.repair_policy_cells(analysis,task,cfg,'org1',{},[])
    from app.services.task_workflow import mark_snapshot_metrics_reused
    mark_snapshot_metrics_reused(analysis)
    assert not synthesis.policy_repair_targets(analysis.fields,{},task.source_manifest,analysis.doc_spans)
    assert repair.repair_policy_cells(analysis,task,cfg,'org1',{},[]) is None
    assert len(writer.calls)==1


def test_legacy_failure_without_rule_receipts_never_becomes_free_retry_after_restore(tmp_path,monkeypatch):
    analysis,task,cfg=setup(tmp_path,monkeypatch)
    analysis.fields['_form_policy_repair']={'status':'provider_failed','targets':['结案小结']}
    from app.services.task_workflow import mark_snapshot_metrics_reused, merge_manual_fields
    mark_snapshot_metrics_reused(analysis)
    receipt=deepcopy(analysis.fields['_form_policy_attempts'])
    assert receipt[0]['rules']=={} and receipt[0]['legacy_unknown_rules'] is True
    merge_manual_fields(analysis,{'_form_policy_attempts':[]})
    assert analysis.fields['_form_policy_attempts']==receipt
    monkeypatch.setattr(repair,'_client',lambda _:pytest.fail('legacy request boundary must survive restore'))
    assert repair.repair_policy_cells(analysis,task,cfg,'org1',{},[]) is None


def test_budget_exhaustion_keeps_unaffected_form_and_records_incomplete_state(tmp_path,monkeypatch):
    analysis,task,cfg=setup(tmp_path,monkeypatch);before=deepcopy(analysis.fields)
    task.execution_profile['_request_budget']={'version':1,'max_requests':0}
    writer=Writer();monkeypatch.setattr(repair,'_client',lambda _:writer)
    result=repair.repair_policy_cells(analysis,task,cfg,'org1',{},[])
    assert result['status']=='task_budget_exhausted' and not writer.calls
    assert analysis.fields['审（办）结果']==before['审（办）结果']
    assert analysis.fields['结案小结']==''
    assert analysis.fields['_request_budget_stop']['status']=='incomplete'
    assert analysis.fields[synthesis.KEY]==before[synthesis.KEY]
