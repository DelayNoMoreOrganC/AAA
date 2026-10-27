from __future__ import annotations

import asyncio
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config_adapter import DEFAULTS, load_user_settings
from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import UserSetting
from ..schemas import SystemSettings, SystemSettingsUpdate, CloudPolicyUpdate, LocalVisionSelection
from ..services.readiness import check_readiness
from ..services.safe_errors import ErrorCode, public_error
from ..services.cloud_policy import external_ai_allowed, read_cloud_policy, write_cloud_policy, require_external_ai, CloudPolicyLocked

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/local-vision")
async def local_environment(tier: Literal["minimum", "recommended", "top", "unified128"] = "minimum", user=Depends(get_current_user)):
    from ..services.local_vision import environment
    return await asyncio.to_thread(environment, tier)


async def _local_operation(operation, db):
    from ..services.local_vision import LocalEngineUnavailable
    from ..models import ArchiveTask, TaskStatus
    from ..services.task_manager import task_manager
    busy = await db.scalar(select(ArchiveTask.id).where(ArchiveTask.status.in_([TaskStatus.pending, TaskStatus.running])).limit(1))
    if busy is not None or task_manager.semaphore.locked():
        raise HTTPException(409, "工作站正在归档，请完成后再准备或试跑本地模型")
    async with task_manager.semaphore:
        try:
            return await asyncio.to_thread(operation)
        except LocalEngineUnavailable as exc:
            raise HTTPException(409, str(exc)) from None
        except Exception:
            raise HTTPException(503, "本地引擎操作未完成，请重新检测；没有切换云端") from None


@router.post("/local-vision/prepare")
async def prepare_local(body: LocalVisionSelection, user=Depends(require_admin), db=Depends(get_db)):
    from ..services.local_vision import prepare
    return await _local_operation(lambda: prepare(tier=body.tier), db)


@router.post("/local-vision/download")
async def download_local(body: LocalVisionSelection, user=Depends(require_admin), db=Depends(get_db)):
    from ..services.local_vision import prepare
    return await _local_operation(lambda: prepare(download=True, tier=body.tier), db)


@router.post("/local-vision/benchmark")
async def benchmark_local(body: LocalVisionSelection, user=Depends(require_admin), db=Depends(get_db)):
    from ..services.local_vision import benchmark
    return await _local_operation(lambda: benchmark(body.tier), db)


def _to_schema(merged):
    return SystemSettings(
        local_vision_tier=merged.get("local_vision_tier", "minimum"),
        processing_mode=merged.get("processing_mode", "local"),
        local_llm_base_url=merged.get("local_llm_base_url", "http://127.0.0.1:11434/v1"),
        local_llm_model=merged.get("local_llm_model", ""),
        deepseek_base_url=merged.get("deepseek_base_url", "https://api.deepseek.com"),
        deepseek_model=merged.get("deepseek_model", "deepseek-v4-flash"),
        order_mode=merged.get("order_mode", "catalog"),
        glm_key_configured=bool(merged.get("glm_api_key", "").strip()),
        deepseek_key_configured=bool(merged.get("deepseek_api_key", "").strip()),
        mineru_key_configured=bool(merged.get("mineru_api_token", "").strip()),
        external_ai_allowed=external_ai_allowed(),
    )


@router.get("", response_model=SystemSettings)
async def get_settings_route(user=Depends(get_current_user), db=Depends(get_db)):
    merged = await load_user_settings(db, user.id)
    return _to_schema(merged)


@router.put("", response_model=SystemSettings)
async def update_settings(body: SystemSettingsUpdate, user=Depends(get_current_user), db=Depends(get_db)):
    previous = await load_user_settings(db, user.id)
    mapping = {
        "local_vision_tier": body.local_vision_tier,
        "processing_mode": body.processing_mode,
        "local_llm_base_url": body.local_llm_base_url,
        "local_llm_model": body.local_llm_model,
        "deepseek_api_key": body.deepseek_api_key,
        "deepseek_base_url": body.deepseek_base_url,
        "deepseek_model": body.deepseek_model,
        "mineru_api_token": body.mineru_api_token,
        "order_mode": body.order_mode,
        "glm_api_key": body.glm_api_key,
    }
    mapping = {key: value for key, value in mapping.items()
               if key in body.model_fields_set and value is not None}
    for key in ("glm_api_key", "deepseek_api_key", "mineru_api_token"):
        if key in mapping:
            mapping[key] = mapping[key].strip()
    # Materialize only this account's effective settings before its first save:
    # an omitted legacy key must not vanish when another setting is edited.
    mapping = {**{key: previous[key] for key in DEFAULTS}, **mapping}
    for key, value in mapping.items():
        res = await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == user.id, UserSetting.key == key
            )
        )
        row = res.scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.add(UserSetting(user_id=user.id, key=key, value=value))
    await db.commit()
    merged = await load_user_settings(db, user.id)
    return _to_schema(merged)


@router.get("/readiness")
async def readiness(user=Depends(get_current_user), db=Depends(get_db)):
    return await check_readiness(db, user.id)


@router.get("/cloud-policy")
async def get_cloud_policy(user=Depends(require_admin)):
    return read_cloud_policy()


@router.put("/cloud-policy")
async def update_cloud_policy(body: CloudPolicyUpdate, user=Depends(require_admin)):
    if body.allowed and not body.confirm_external_processing:
        raise HTTPException(409, "启用前须明确确认：本工作站获授权的案件页面和必要文字将发送至所选云端服务。")
    try:
        return write_cloud_policy(allowed=body.allowed, actor_id=user.id)
    except CloudPolicyLocked:
        raise HTTPException(409, "部署策略已锁定外部 AI；页面开关不能解除。") from None
    except OSError:
        raise HTTPException(503, "工作站云功能设置未能保存；请稍后重试。") from None


def _probe_glm(key):
    require_external_ai()
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    from glm_vision_client import probe
    return probe(key)


@router.post("/glm/check")
async def check_glm(user=Depends(get_current_user), db=Depends(get_db)):
    """Explicit account connection check; no case or material is ever loaded."""
    if not external_ai_allowed():
        raise HTTPException(409, public_error(ErrorCode.CLOUD_DISABLED))
    cfg = await load_user_settings(db, user.id)
    key = cfg.get("glm_api_key", "").strip()
    if not key:
        raise HTTPException(409, public_error(ErrorCode.GLM_KEY_UNCONFIGURED))
    try:
        result = await asyncio.to_thread(_probe_glm, key)
        if not isinstance(result, dict) or result.get("ready") is not True:
            raise RuntimeError()
    except Exception:
        raise HTTPException(503, public_error(ErrorCode.GLM_CHECK_FAILED)) from None
    return {"ready": True, "message": "GLM 标准 API 连接检查通过；本次未发送案件材料。"}


def _probe_deepseek(key):
    require_external_ai()
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    from deepseek_vision_client import probe
    return probe(key)


@router.post("/deepseek/check")
async def check_deepseek(user=Depends(get_current_user), db=Depends(get_db)):
    """Explicit, text-only account probe; never reads a case or its files."""
    if not external_ai_allowed():
        raise HTTPException(409, public_error(ErrorCode.CLOUD_DISABLED))
    cfg = await load_user_settings(db, user.id)
    key = cfg.get("deepseek_api_key", "").strip()
    if not key:
        raise HTTPException(409, public_error(ErrorCode.DEEPSEEK_KEY_UNCONFIGURED))
    try:
        result = await asyncio.to_thread(_probe_deepseek, key)
        if not isinstance(result, dict) or result.get("ready") is not True:
            raise RuntimeError()
    except Exception as exc:
        from ..services.safe_errors import deepseek_error_code
        raise HTTPException(503, public_error(deepseek_error_code(exc, ErrorCode.DEEPSEEK_CHECK_FAILED))) from None
    return {"ready": True, "message": "DeepSeek 标准 API 连接检查通过；本次未发送案件材料。"}
