"""Backend policy binding only; no network, OCR or original case access."""
from types import SimpleNamespace as NS
import pytest
from tests.test_form_policy_repair_job import setup
from app.services.recognition_checkpoint import build_checkpoint, RecognitionCheckpointError
from app.services import execution_profile
from app.services.safe_errors import recognition_progress_error_code, ErrorCode
from recognition_journal import RecognitionJournalError


def checkpoint(task,cfg):
    return build_checkpoint(task,None,'org1',cfg,case_type='nonlit',stage='',
        sources=[NS(path=row['path'],doc_type=row['doc_type']) for row in task.source_manifest],
        manual_fields={},parent_snapshot=None,analysis_kind='full')


class Transport:
    def __init__(self):self.calls=0;self.metrics={}
    def complete(self,messages):self.calls+=1;return {'ok':True}


def test_task_budget_survives_changed_journal_scope_and_is_not_a_model_argument(tmp_path,monkeypatch):
    _,task,cfg=setup(tmp_path,monkeypatch)
    task.execution_profile['_request_budget']={'version':1,'max_requests':1}
    first=checkpoint(task,cfg);model=Transport();client=first.bind(model)
    messages=[{'role':'user','content':'protocol'}]
    client.complete(messages)
    assert model.calls==1 and messages==[{'role':'user','content':'protocol'}]
    task.revision+=1
    second=checkpoint(task,cfg);assert second.scope_sha256!=first.scope_sha256
    other=Transport()
    with pytest.raises(RecognitionJournalError) as e:second.bind(other).complete(messages)
    assert e.value.code=='REQUEST_BUDGET_EXHAUSTED' and other.calls==0
    assert recognition_progress_error_code(e.value)==ErrorCode.MODEL_REQUEST_BUDGET_EXHAUSTED


@pytest.mark.parametrize('policy',[{'version':1,'max_requests':True},{'version':1,'max_requests':-1},
    {'version':1,'max_requests':2,'reset':True},None,{'version':True,'max_requests':2}])
def test_bad_frozen_policy_cannot_enable_requests(tmp_path,monkeypatch,policy):
    _,task,cfg=setup(tmp_path,monkeypatch);task.execution_profile['_request_budget']=policy
    with pytest.raises(RecognitionCheckpointError):checkpoint(task,cfg)


def test_old_profiles_have_no_invented_counter_or_new_budget(tmp_path,monkeypatch):
    _,task,cfg=setup(tmp_path,monkeypatch)
    cp=checkpoint(task,cfg)
    assert 'request_budget' not in cp.scope
    assert cp.bind(Transport())._request_budget is None


def test_batching_is_frozen_and_checkpoint_rejects_unbound_configuration(tmp_path,monkeypatch):
    from document_field_batch import POLICY
    _,task,cfg=setup(tmp_path,monkeypatch)
    cfg['vision']['batch_policy']=dict(POLICY)
    with pytest.raises(RecognitionCheckpointError):checkpoint(task,cfg)
    task.execution_profile['_visual_batch_policy']=dict(POLICY)
    cp=checkpoint(task,cfg)
    assert cp.scope['configuration']['batch_policy']==POLICY
    cfg['vision']['batch_policy']['classification_pages']=16
    with pytest.raises(RecognitionCheckpointError):checkpoint(task,cfg)
    assert task.execution_profile['_visual_batch_policy']==POLICY


@pytest.mark.asyncio
async def test_new_visual_task_freezes_deployment_limit_without_authorizing_cloud(monkeypatch):
    settings=NS(model_request_limit=3,deepseek_request_limit=20)
    async def account(*args):return {'processing_mode':'deepseek_cloud'}
    monkeypatch.setattr(execution_profile,'load_user_settings',account)
    monkeypatch.setattr(execution_profile,'get_settings',lambda:settings)
    monkeypatch.setattr(execution_profile,'external_ai_allowed',lambda:True)
    from app.services.safe_errors import SafeTaskError
    with pytest.raises(SafeTaskError):
        await execution_profile.make_profile(None,'user','source',expected_mode='deepseek_cloud')
    profile=await execution_profile.make_profile(None,'user','source',cloud_consent=True,expected_mode='deepseek_cloud')
    settings.model_request_limit=10
    assert profile['_request_budget']=={'version':1,'max_requests':3}
    assert profile['cloud_consent'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('generic,deepseek,expected',[(None,20,20),(100,20,20),(5,20,5),(None,8,8),(0,20,0)])
async def test_deepseek_user_ceiling_cannot_be_relaxed_by_generic_setting(monkeypatch,generic,deepseek,expected):
    from app.config import Settings
    settings=Settings(_env_file=None,model_request_limit=generic,deepseek_request_limit=deepseek)
    async def account(*args):return {'processing_mode':'deepseek_cloud'}
    monkeypatch.setattr(execution_profile,'load_user_settings',account)
    monkeypatch.setattr(execution_profile,'get_settings',lambda:settings)
    monkeypatch.setattr(execution_profile,'external_ai_allowed',lambda:True)
    inherited=NS(execution_profile={'processing_mode':'deepseek_cloud','_request_budget':{'version':1,'max_requests':None}})
    profile=await execution_profile.make_profile(None,'user','source',cloud_consent=True,
        expected_mode='deepseek_cloud',inherited_task=inherited)
    assert profile['_request_budget']=={'version':1,'max_requests':expected}
    assert inherited.execution_profile['_request_budget']['max_requests'] is None


def test_deepseek_setting_rejects_unapproved_higher_limit():
    from app.config import Settings
    from pydantic import ValidationError
    with pytest.raises(ValidationError):Settings(_env_file=None,deepseek_request_limit=21)


@pytest.mark.asyncio
async def test_cloud_ceiling_does_not_apply_to_local_ollama(monkeypatch):
    from app.config import Settings
    from app.services import local_vision
    settings=Settings(_env_file=None,model_request_limit=None,deepseek_request_limit=20)
    async def account(*args):return {'processing_mode':'ollama_local'}
    monkeypatch.setattr(execution_profile,'load_user_settings',account)
    monkeypatch.setattr(execution_profile,'get_settings',lambda:settings)
    monkeypatch.setattr(local_vision,'guard',lambda *args:'a'*64)
    profile=await execution_profile.make_profile(None,'user','source',expected_mode='ollama_local')
    assert profile['_request_budget']=={'version':1,'max_requests':None}
    assert profile['cloud_consent'] is False
