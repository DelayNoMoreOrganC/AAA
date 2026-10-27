"""Check actual local prerequisites without transmitting any case material."""
import importlib.util
import asyncio
import ipaddress
from urllib.parse import urlsplit

import httpx

from ..config import get_settings
from ..core.config_adapter import load_user_settings
from .cloud_policy import external_ai_allowed


def validate_local_url(url: str) -> str:
    parsed = urlsplit(url)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        valid = address.is_loopback
    except ValueError:
        valid = False
    if not valid or parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("本地保密模式的模型地址必须是工作站回环 IP（127.0.0.1 或 ::1），且不能包含账号或查询参数")
    # Avoid environment proxy settings and redirects at every request boundary.
    return url.rstrip("/")


async def check_readiness(db, user_id: str, *, probe=True, overrides=None):
    cfg = await load_user_settings(db, user_id)
    cfg.update(overrides or {})
    settings = get_settings()
    mode = cfg.get("processing_mode", "local")
    issues = []
    local_environment = None
    if mode == "ollama_local":
        from .local_vision import environment
        local_environment = await asyncio.to_thread(environment, cfg.get("local_vision_tier", "minimum"))
        issues.extend(local_environment["issues"])
        if local_environment["benchmark_required"]:
            issues.append("请由管理员完成本地视觉试跑后再开始归档")
        from ..core.v4_bridge import init_v4_path
        init_v4_path()
        try:
            from local_ocr import bundled_model_paths
            bundled_model_paths()
        except Exception:
            issues.append("本地 OCR 模型包未就绪")
    elif mode == "local":
        try:
            url = validate_local_url(cfg["local_llm_base_url"])
        except ValueError as exc:
            issues.append(str(exc))
            url = ""
        model = cfg.get("local_llm_model", "").strip()
        if not model:
            issues.append("工作站尚未选择本地模型，请由管理员完成一次配置")
        if importlib.util.find_spec("rapidocr_onnxruntime") is None:
            issues.append("工作站缺少本地 OCR 组件，请由部署人员安装")
        else:
            from ..core.v4_bridge import init_v4_path
            init_v4_path()
            from local_ocr import bundled_model_paths
            try:
                bundled_model_paths()
            except Exception:
                issues.append("工作站本地 OCR 模型包不完整，请由部署人员修复")
        if probe and url and model:
            try:
                async with httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False) as client:
                    response = await client.get(url + "/models")
                    response.raise_for_status()
                    available = {item.get("id") for item in response.json().get("data", [])}
                    if model not in available:
                        issues.append("配置的本地模型尚未加载，请在工作站加载后重试")
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                issues.append("本地模型服务未就绪，请由管理员启动模型服务")
    elif mode in ("cloud", "glm_cloud", "deepseek_cloud"):
        if not external_ai_allowed(settings):
            issues.append("工作站已禁止外部 AI，云端模式不能启动；请使用本地模式")
        if mode == "glm_cloud" and not cfg.get("glm_api_key", "").strip():
            issues.append("未配置 GLM 标准 API 密钥；Coding Plan 额度不能用于本工作站")
        if mode == "deepseek_cloud" and not cfg.get("deepseek_api_key", "").strip():
            issues.append("未配置 DeepSeek 标准 API 密钥")
        if mode == "cloud" and not cfg.get("deepseek_api_key", "").strip():
            issues.append("未配置云端模型密钥")
        if mode == "cloud" and not cfg.get("mineru_api_token", "").strip():
            issues.append("未配置云端 OCR 密钥")
    else:
        issues.append("处理模式无效")
    from .original_template_readiness import original_form_readiness
    forms = original_form_readiness()
    issues.extend(forms["issues"])
    return {"ready": not issues, "mode": mode, "issues": issues,
            "external_ai_allowed": external_ai_allowed(settings), "original_forms": forms,
            **({"local_environment": local_environment} if local_environment is not None else {})}
