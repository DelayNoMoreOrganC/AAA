"""Build the V4 config dict from per-account API settings."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Role, Setting, User, UserSetting
from ..config import get_settings
from ..services.cloud_policy import external_ai_allowed, require_external_ai


DEFAULTS: dict[str, str] = {
    "processing_mode": "local",
    "local_llm_base_url": "http://127.0.0.1:11434/v1",
    "local_llm_model": "",
    "local_vision_tier": "minimum",
    "deepseek_api_key": "",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-v4-flash",
    "mineru_api_token": "",
    "glm_api_key": "",
    "order_mode": "catalog",
}


async def load_user_settings(db: AsyncSession, user_id: str) -> dict[str, str]:
    """Load one account's settings without falling back to another account."""
    result = await db.execute(select(UserSetting).where(UserSetting.user_id == user_id))
    user_rows = result.scalars().all()
    rows = {r.key: r.value for r in user_rows}

    # Preserve an existing installation's global configuration for the admin
    # account only. Ordinary accounts always start from clean defaults.
    if not user_rows:
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user and user.role == Role.admin:
            legacy_result = await db.execute(select(Setting))
            rows.update({r.key: r.value for r in legacy_result.scalars().all() if r.key != "glm_api_key"})

    merged = dict(DEFAULTS)
    merged["local_llm_base_url"] = get_settings().local_llm_base_url
    merged["local_llm_model"] = get_settings().local_llm_model
    merged.update(rows)
    return merged


async def build_v4_config(db: AsyncSession, user_id: str, *, overrides=None, cloud_authorized=False) -> dict:
    """Translate V6 account settings into the config dict core modules expect."""
    s = await load_user_settings(db, user_id)
    s.update(overrides or {})
    preview_only = get_settings().preview_only
    mode = s.get("processing_mode", "local")
    if mode not in ("local", "ollama_local", "cloud", "glm_cloud", "deepseek_cloud"):
        raise ValueError("处理模式无效")
    if mode not in ("local", "ollama_local") and not external_ai_allowed():
        raise ValueError("工作站已禁止外部 AI")
    local = s.get("processing_mode", "local") == "local"
    config = {
        "debug": {"match_details": False},
        "ocr": {
            "engine": "local_onnx" if local else "mineru_api",
            "page_engine": "local_onnx" if local else "mineru_api",
            "cache": False,
        },
        "deepseek": {
            "api_key": "local-workstation" if local else s["deepseek_api_key"],
            "base_url": s["local_llm_base_url"] if local else s["deepseek_base_url"],
            "model": s["local_llm_model"] if local else s["deepseek_model"],
            "local_only": local,
        },
        "mineru": {
            "api_token": s["mineru_api_token"],
            "api_model_version": "vlm",
            "backend": "hybrid-auto-engine",
            "method": "ocr",
            "lang": "ch",
            "force_ocr": True,
            "quality": "ultra",
        },
        "local_ocr": {
            "max_pages": 0,
        },
        "output": {
            "custom_path": "",
            "docx_only": False,
            "preview_only": preview_only,
        },
        "fill": {
            "mode": "textbox",
        },
        "extraction": {
            "mode": "workstation_agent" if local else "visual_agent" if mode in ("glm_cloud", "deepseek_cloud") else "segmented",
        },
        "archive": {
            "order_mode": s["order_mode"],
        },
        "baidu_ocr": {},
        "privacy": {"mode": "local" if local else "cloud", "cloud_authorized": bool(cloud_authorized and not local)},
    }
    if mode in ("glm_cloud", "deepseek_cloud"):
        # In-memory callable only; never persisted in profiles or snapshots.
        config["privacy"]["request_guard"] = require_external_ai
        # The visual branch must not fall back to another provider or OCR API.
        config["ocr"] = {"engine": "native_vision", "page_engine": "native_vision", "cache": False}
        config["deepseek"] = {}
        config["mineru"] = {}
        if mode == "glm_cloud":
            config["vision"] = {"provider": "zhipu", "model": "glm-5.3-flash",
                                "api_key": s.get("glm_api_key", ""),
                                "endpoint": "https://open.bigmodel.cn/api/paas/v4/chat/completions"}
        else:
            config["vision"] = {"provider": "deepseek", "model": "deepseek-flash",
                                "api_key": s.get("deepseek_api_key", ""),
                                "workflow": "document_two_stage",
                                "endpoint": "https://api.deepseek.com/chat/completions"}
    if mode == "ollama_local":
        from ..services.local_vision import guard, BASE_URL, preset
        model = s.get("ollama_model") or preset(s.get("local_vision_tier", "minimum"))["model"]
        config["privacy"] = {"mode": "local", "cloud_authorized": False,
                             "request_guard": lambda: guard(s.get("ollama_model_digest"), model)}
        config["extraction"] = {"mode": "visual_agent"}
        config["ocr"] = {"engine": "native_vision", "page_engine": "native_vision", "cache": False}
        config["deepseek"], config["mineru"], config["baidu_ocr"] = {}, {}, {}
        config["vision"] = {"provider": "ollama", "model": model, "endpoint": BASE_URL + "/api/chat",
                            "workflow": "document_two_stage", "batch_pages": 1}
    return config
