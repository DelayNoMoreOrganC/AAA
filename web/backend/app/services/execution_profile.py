"""Server-owned processing choice and per-input-version cloud authorization.

Profiles never contain credentials. Legacy jobs always remain local; changing
account settings cannot grant authority to transmit an existing task's material.
"""
from ..config import get_settings
from ..core.config_adapter import load_user_settings, build_v4_config
from .safe_errors import ErrorCode, SafeTaskError
from .cloud_policy import external_ai_allowed

CLOUD_MODES = {"cloud", "glm_cloud", "deepseek_cloud"}
MODES = {"local", "ollama_local", *CLOUD_MODES}
PUBLIC_KEYS = ("version", "processing_mode", "provider", "model", "workflow", "cloud_consent", "authorized_source_version")


def public_profile(task):
    profile = getattr(task, "execution_profile", None)
    return {key: profile.get(key) for key in PUBLIC_KEYS} if isinstance(profile, dict) else None


def frozen_mode(task):
    profile = getattr(task, "execution_profile", None)
    if profile is None:
        return "local"
    if not isinstance(profile, dict) or profile.get("processing_mode") not in MODES:
        raise SafeTaskError(ErrorCode.EXECUTION_PROFILE_INVALID)
    return profile["processing_mode"]


def profile_overrides(task):
    mode = frozen_mode(task)
    profile = getattr(task, "execution_profile", None) or {}
    result = {"processing_mode": mode}
    if mode == "ollama_local":
        result["ollama_model_digest"] = profile.get("model_digest")
        result["ollama_model"] = profile.get("model")
        result["local_vision_tier"] = profile.get("local_vision_tier", "minimum")
    if mode == "local" and profile:
        result.update(local_llm_model=profile.get("model", ""), local_llm_base_url=profile.get("base_url", ""))
    elif mode == "cloud":
        result.update(deepseek_model=profile.get("model", ""), deepseek_base_url=profile.get("base_url", ""))
    return result


def validate_task_authorization(task, actual_source_version=None):
    mode = frozen_mode(task)
    profile = getattr(task, "execution_profile", None)
    if profile is not None and (profile.get("version") != 1 or not isinstance(profile.get("model"), str)):
        raise SafeTaskError(ErrorCode.EXECUTION_PROFILE_INVALID)
    if actual_source_version is not None and actual_source_version != task.source_version:
        raise SafeTaskError(ErrorCode.SOURCE_CHANGED)
    if mode == "ollama_local":
        import re
        from .local_vision import ALLOWED_MODELS, PRESETS
        if (profile.get("provider") != "ollama" or profile.get("model") not in ALLOWED_MODELS
                or profile.get("local_vision_tier", "minimum") not in PRESETS
                or (profile.get("model") != "qwen3-vl:8b" and profile.get("model") != PRESETS[profile.get("local_vision_tier", "minimum")]["model"])
                or profile.get("workflow") != "document_two_stage" or profile.get("cloud_consent") is not False
                or not isinstance(profile.get("model_digest"), str)
                or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", profile["model_digest"])):
            raise SafeTaskError(ErrorCode.EXECUTION_PROFILE_INVALID)
    if mode in CLOUD_MODES:
        if not external_ai_allowed():
            raise SafeTaskError(ErrorCode.CLOUD_DISABLED)
        if (profile.get("cloud_consent") is not True or not task.source_version
                or profile.get("authorized_source_version") != task.source_version
                or profile.get("authorized_by") != task.created_by):
            raise SafeTaskError(ErrorCode.CLOUD_CONSENT_REQUIRED)
        if mode == "glm_cloud" and (profile.get("provider") != "zhipu" or profile.get("model") != "glm-5.3-flash"):
            raise SafeTaskError(ErrorCode.EXECUTION_PROFILE_INVALID)
        if mode == "deepseek_cloud" and (profile.get("provider") != "deepseek" or profile.get("model") != "deepseek-flash"
                                          or profile.get("workflow") != "document_two_stage"):
            raise SafeTaskError(ErrorCode.EXECUTION_PROFILE_INVALID)
    return mode


async def make_profile(db, user_id, version, *, cloud_consent=False, expected_mode=None, inherited_task=None):
    settings = await load_user_settings(db, user_id)
    mode = frozen_mode(inherited_task) if inherited_task is not None else settings.get("processing_mode", "local")
    if mode not in MODES:
        raise SafeTaskError(ErrorCode.PROCESSING_MODE_INVALID)
    if expected_mode is not None and expected_mode != mode:
        raise SafeTaskError(ErrorCode.EXECUTION_PROFILE_INVALID)
    cloud = mode in CLOUD_MODES
    if cloud and not external_ai_allowed():
        raise SafeTaskError(ErrorCode.CLOUD_DISABLED)
    if cloud and (cloud_consent is not True or expected_mode != mode or not version):
        raise SafeTaskError(ErrorCode.CLOUD_CONSENT_REQUIRED)
    inherited = getattr(inherited_task, "execution_profile", None) or {}
    if mode == "ollama_local":
        import asyncio
        from .local_vision import guard, preset, LocalEngineUnavailable
        tier = inherited.get("local_vision_tier", settings.get("local_vision_tier", "minimum"))
        model = inherited.get("model") or preset(tier)["model"]
        try:
            digest = await asyncio.to_thread(guard, inherited.get("model_digest"), model)
        except LocalEngineUnavailable:
            raise SafeTaskError(ErrorCode.LOCAL_MODEL_UNAVAILABLE) from None
        return {"version": 1, "processing_mode": mode, "provider": "ollama", "model": model, "local_vision_tier": tier,
                "workflow": "document_two_stage", "model_digest": digest, "cloud_consent": False,
                "authorized_source_version": None, "authorized_by": None}
    profile = {"version": 1, "processing_mode": mode,
               "provider": "zhipu" if mode == "glm_cloud" else "deepseek" if mode == "deepseek_cloud" else "deepseek_mineru" if cloud else "local",
               "model": "glm-5.3-flash" if mode == "glm_cloud" else "deepseek-flash" if mode == "deepseek_cloud" else inherited.get("model", settings.get("deepseek_model" if cloud else "local_llm_model", "")),
               "cloud_consent": cloud, "authorized_source_version": version if cloud else None,
               "authorized_by": user_id if cloud else None}
    if mode == "deepseek_cloud":
        profile["workflow"] = "document_two_stage"
    if mode not in ("glm_cloud", "deepseek_cloud"):
        profile["base_url"] = inherited.get("base_url", settings.get("deepseek_base_url" if cloud else "local_llm_base_url", ""))
    return profile


async def task_config(db, task, *, actual_source_version):
    mode = validate_task_authorization(task, actual_source_version)
    config = await build_v4_config(db, task.created_by, overrides=profile_overrides(task), cloud_authorized=mode in CLOUD_MODES)
    if mode == "glm_cloud" and not config["vision"]["api_key"].strip():
        raise SafeTaskError(ErrorCode.GLM_KEY_UNCONFIGURED)
    if mode == "deepseek_cloud" and not config["vision"]["api_key"].strip():
        raise SafeTaskError(ErrorCode.DEEPSEEK_KEY_UNCONFIGURED)
    return config
