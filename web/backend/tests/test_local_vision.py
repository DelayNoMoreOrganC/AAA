from types import SimpleNamespace
import pytest
from tests.test_file_import_api import upload_context
from app.services import local_vision as engine, execution_profile as profiles
from app.core.config_adapter import build_v4_config
from app.services.safe_errors import SafeTaskError

DIGEST="a"*64


@pytest.mark.parametrize("tier,ram,gpus,expected",[("minimum",32,[16],"meets_tier"),("recommended",64,[32],"meets_tier"),("top",128,[96],"meets_tier"),("minimum",16,[24],"below_tier"),("minimum",32,[8,8],"below_tier"),("unified128",128,[],"needs_verification"),("unified128",64,[],"below_tier")])
def test_fixed_tiers_never_sum_gpus_or_redefine_from_current_pc(tier,ram,gpus,expected):
    assert engine.recommendation({"ram_gb":ram,"gpus":[{"total_gb":g} for g in gpus]},tier)[0]==expected


def test_unowned_engine_never_contacts_local_api(monkeypatch):
    monkeypatch.setattr(engine,"_read",lambda _: {})
    monkeypatch.setattr(engine.requests,"Session",lambda:pytest.fail("must not contact an unowned service"))
    with pytest.raises(engine.LocalEngineUnavailable):engine.guard()


@pytest.mark.parametrize("patch",[{"remote_model":"cloud"},{"remote_host":"https://example.com"},{"capabilities":["completion"]},{"details":{"quantization_level":"F16"}}])
def test_cloud_alias_or_wrong_model_rejected(monkeypatch,patch):
    def api(path,body=None):
        if path=="/api/version":return {"version":"0.12.7"}
        return {"models":[{"name":engine.MODEL,"digest":DIGEST}]} if path=="/api/tags" else {"capabilities":["vision"],"details":{"quantization_level":"Q4_K_M"},**patch}
    monkeypatch.setattr(engine,"_api",api)
    with pytest.raises(engine.LocalEngineUnavailable):engine.guard()


def test_changed_digest_stops_frozen_task(monkeypatch):
    monkeypatch.setattr(engine,"model_identity",lambda model=None:DIGEST)
    with pytest.raises(engine.LocalEngineUnavailable):engine.guard("b"*64)
    assert engine.guard(DIGEST)==DIGEST


@pytest.mark.asyncio
async def test_local_profile_config_no_cloud_keys_and_immutable_across_settings(upload_context,monkeypatch):
    ctx=upload_context
    monkeypatch.setattr(engine,"guard",lambda expected=None,model=None:DIGEST)
    response=await ctx.client.put('/api/settings',json={"processing_mode":"ollama_local","deepseek_api_key":"SYNTHETIC_SECRET","mineru_api_token":"SYNTHETIC_OCR"})
    assert response.status_code==200 and "SYNTHETIC" not in response.text
    async with ctx.sessions() as db:
        profile=await profiles.make_profile(db,"test-user","version1",expected_mode="ollama_local")
        task=SimpleNamespace(case_id='case-a',execution_profile=profile,created_by="test-user",source_version="version1")
        assert profiles.validate_task_authorization(task,"version1")=="ollama_local"
        config=await profiles.task_config(db,task,actual_source_version="version1")
        assert config["privacy"]["mode"]=="local" and not config["privacy"]["cloud_authorized"]
        assert not config["deepseek"] and not config["mineru"] and not config["baidu_ocr"]
        assert config["vision"]["model"]==engine.MODEL
        assert "SYNTHETIC" not in repr(config)
    await ctx.client.put('/api/settings',json={"processing_mode":"deepseek_cloud"})
    async with ctx.sessions() as db:
        config=await profiles.task_config(db,task,actual_source_version="version1")
        assert config["vision"]["provider"]=="ollama"
    task.execution_profile={**profile,"cloud_consent":True}
    with pytest.raises(SafeTaskError):profiles.validate_task_authorization(task)


@pytest.mark.asyncio
async def test_local_management_requires_admin_and_read_is_non_mutating(upload_context,monkeypatch):
    ctx=upload_context
    monkeypatch.setattr(engine,"environment",lambda tier=None:{"ready":False,"issues":["test"]})
    monkeypatch.setattr(engine,"prepare",lambda **_:pytest.fail("ordinary user cannot launch or download"))
    monkeypatch.setattr(engine,"benchmark",lambda:pytest.fail("ordinary user cannot run benchmark"))
    assert (await ctx.client.get('/api/settings/local-vision')).status_code==200
    for action in ("prepare","download","benchmark"):
        assert (await ctx.client.post('/api/settings/local-vision/'+action,json={'tier':'minimum'})).status_code==403


def test_unknown_environment_cannot_look_ready(monkeypatch):
    monkeypatch.setattr(engine,"hardware",lambda:{"ram_gb":16,"available_ram_gb":5,"gpus":[],"gpu_verified":False})
    monkeypatch.setattr(engine,"executable",lambda:"")
    monkeypatch.setattr(engine,"_read",lambda _: {})
    result=engine.environment()
    assert not result["ready"] and not result["engine_ready"] and result["benchmark_required"]
    assert result["recommendation"]=="below_tier" and result["offline_acceptance"]=="not_verified"


@pytest.mark.asyncio
@pytest.mark.parametrize("tier",list(engine.PRESETS))
async def test_each_preset_is_frozen_and_cannot_follow_later_account_choice(upload_context,monkeypatch,tier):
    ctx=upload_context
    calls=[]
    def guarded(expected=None,model=None):
        calls.append(model)
        return DIGEST
    monkeypatch.setattr(engine,"guard",guarded)
    await ctx.client.put('/api/settings',json={"processing_mode":"ollama_local","local_vision_tier":tier})
    async with ctx.sessions() as db:
        profile=await profiles.make_profile(db,"test-user","v1",expected_mode="ollama_local")
    assert profile["model"]==engine.PRESETS[tier]["model"]
    task=SimpleNamespace(case_id='case-a',execution_profile=profile,created_by="test-user",source_version="v1")
    await ctx.client.put('/api/settings',json={"local_vision_tier":"minimum","processing_mode":"deepseek_cloud"})
    async with ctx.sessions() as db:
        config=await profiles.task_config(db,task,actual_source_version="v1")
        config["privacy"]["request_guard"]()
        inherited=await profiles.make_profile(db,"test-user","v2",expected_mode="ollama_local",inherited_task=task)
    assert inherited["model"]==profile["model"] and inherited["local_vision_tier"]==tier
    assert config["vision"]["model"]==profile["model"] and set(calls)=={profile["model"]}


@pytest.mark.asyncio
async def test_unknown_tier_rejected_at_settings_and_diagnostics_boundary(upload_context):
    ctx=upload_context
    assert (await ctx.client.put('/api/settings',json={"local_vision_tier":"arbitrary-cloud-model"})).status_code==422
    assert (await ctx.client.get('/api/settings/local-vision?tier=arbitrary-cloud-model')).status_code==422


def test_selected_model_guard_accepts_only_local_vision_quantization(monkeypatch):
    seen=[]
    def api(path,body=None):
        seen.append((path,body))
        if path=="/api/version":return {"version":"0.23.0"}
        if path=="/api/tags":return {"models":[{"name":engine.PRESETS['top']['model'],"digest":DIGEST}]}
        return {"capabilities":["vision","completion"],"details":{"quantization_level":"Q4_K_M"}}
    monkeypatch.setattr(engine,"_api",api)
    assert engine.guard(model=engine.PRESETS['top']['model'])==DIGEST
    assert seen[-1][1]["model"]==engine.PRESETS['top']['model']
    with pytest.raises(engine.LocalEngineUnavailable):engine.guard(model='qwen3.5:cloud')
