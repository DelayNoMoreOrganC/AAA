#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置加载（EXE / CLI 共用，不依赖 Flask）"""

import json
import os
import threading

from app_paths import get_config_path, init_config_if_missing

_config_override = threading.local()


def push_config(config: dict | None) -> None:
    """临时注入运行时配置（V5 Web 从 SQLite 传入，覆盖 config.json）。"""
    _config_override.value = config


def pop_config() -> None:
    if hasattr(_config_override, "value"):
        del _config_override.value


def load_config():
    override = getattr(_config_override, "value", None)
    if override is not None:
        return _merge_defaults(dict(override))
    init_config_if_missing()
    path = get_config_path()
    if not os.path.exists(path):
        return _default_config()
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return _merge_defaults(cfg)


def save_config(config):
    with open(get_config_path(), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _default_config():
    return {
        "ocr": {"engine": "baidu"},
        "deepseek": {
            "api_key": "",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
        },
        "baidu_ocr": {
            "app_id": "",
            "api_key": "",
            "secret_key": "",
            "mode": "basic",
        },
        "mineru": {
            "quality": "ultra",
            "backend": "hybrid-auto-engine",
            "method": "ocr",
            "lang": "ch",
            "force_ocr": True,
            "gpu_device": "0",
            "render_threads": 8,
            "timeout_seconds": 7200,
            "fallback_baidu": False,
            "api_token": "",
            "api_model_version": "vlm",
        },
        "local_ocr": {"max_pages": 0},
        "output": {
            "custom_path": "",
            "docx_only": True,
        },
        "fill": {
            "mode": "textbox",
        },
        "extraction": {
            "mode": "segmented",
        },
    }


def _merge_defaults(cfg):
    d = _default_config()
    for k, v in cfg.items():
        if isinstance(v, dict) and k in d and isinstance(d[k], dict):
            d[k].update(v)
        else:
            d[k] = v
    return d


def get_ocr_engine(config=None) -> str:
    cfg = config or load_config()
    eng = (cfg.get("ocr") or {}).get("engine", "").strip().lower()
    if eng in ("mineru", "baidu", "mineru_api", "local_onnx"):
        return eng
    if cfg.get("mineru", {}).get("enabled"):
        return "mineru"
    return "baidu"


def get_page_ocr_engine(config=None) -> str:
    """V4: 获取页级 OCR 引擎配置"""
    cfg = config or load_config()
    eng = (cfg.get("ocr") or {}).get("page_engine", "").strip().lower()
    if eng in ("rapidocr", "paddle", "tesseract", "reuse"):
        return eng
    return "rapidocr"  # 默认


def get_archive_order_mode(config=None) -> str:
    """V4: 完整归档正文排序模式。

    - ``catalog``（默认）：按标准案卷目录序号重排正文。
    - ``original``：保持源 PDF 原始页序输出正文（卷首/卷末系统模板与卷内目录照旧）。
    """
    cfg = config or load_config()
    mode = (cfg.get("archive") or {}).get("order_mode", "").strip().lower()
    if mode in ("catalog", "original"):
        return mode
    return "catalog"  # 默认


_PLACEHOLDER_MARKERS = ("在此填写", "YOUR_", "你的 ", "请填写", "填写 DeepSeek", "填写百度")


def is_valid_api_key(key) -> bool:
    """HTTP Authorization 仅支持 latin-1；占位中文会被误判为已配置。"""
    key = (key or "").strip()
    if not key:
        return False
    try:
        key.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return not any(m in key for m in _PLACEHOLDER_MARKERS)


def require_api_key(key, label="API Key") -> str:
    """校验 API Key 可用于 HTTP 头，否则抛出明确错误。"""
    key = (key or "").strip()
    if not key:
        raise RuntimeError(f"请在 config.json 中配置 {label}")
    try:
        key.encode("latin-1")
    except UnicodeEncodeError:
        raise RuntimeError(
            f"{label} 含非 ASCII 字符（多为未替换的中文占位文字），"
            f"请填入真实的 Key"
        )
    if any(m in key for m in _PLACEHOLDER_MARKERS):
        raise RuntimeError(f"{label} 仍为示例占位文字，请填入真实的 Key")
    return key


def get_deepseek_config():
    config = load_config()
    c = config.get("deepseek", {})
    return {
        "api_key": (c.get("api_key") or "").strip(),
        "base_url": c.get("base_url", "https://api.deepseek.com").rstrip("/"),
        "model": c.get("model", "deepseek-v4-flash"),
        # The privacy policy remains authoritative even if an older caller
        # omitted the per-provider flag while building its configuration.
        "local_only": bool(c.get("local_only", False)) or (
            config.get("privacy", {}).get("mode") == "local"
        ),
    }


def get_baidu_config():
    c = load_config().get("baidu_ocr", {})
    return {
        "APP_ID": str(c.get("app_id", "")),
        "API_KEY": c.get("api_key", ""),
        "SECRET_KEY": c.get("secret_key", ""),
        "OCR_MODE": c.get("mode", "basic"),
    }


def parse_llm_output(text):
    """解析 LLM 输出为字段字典。

    依次尝试：
    1. JSON 对象（含 ```json 代码块包裹）→ 直接取键值；
    2. 逐行「字段名: 值」/「字段名：值」（兼容中英文冒号），仅按首个冒号切分，
       保留值中后续的冒号（如地址、时间段）。
    重复键时后者覆盖前者，但保留首个非空值优先。
    """
    raw = (text or "").strip()
    if not raw:
        return {}

    # 1) JSON 优先：剥离 ```json ... ``` 围栏后尝试解析
    json_candidate = raw
    if json_candidate.startswith("```"):
        import re as _re
        json_candidate = _re.sub(r"^```[a-zA-Z]*\n?", "", json_candidate)
        json_candidate = _re.sub(r"\n?```$", "", json_candidate).strip()
    if json_candidate.startswith("{") and json_candidate.endswith("}"):
        try:
            import json as _json
            obj = _json.loads(json_candidate)
            if isinstance(obj, dict):
                return {
                    str(k).strip(): ("" if v is None else str(v).strip())
                    for k, v in obj.items()
                }
        except (ValueError, TypeError):
            pass

    # 2) 逐行解析（兼容中文冒号；跳过 markdown 标题/分隔行）
    field_data = {}
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "```", "---")):
            continue
        idx_half = stripped.find(":")
        idx_full = stripped.find("：")
        candidates = [i for i in (idx_half, idx_full) if i != -1]
        if not candidates:
            continue
        sep = min(candidates)
        key = stripped[:sep].strip().lstrip("-*").strip()
        value = stripped[sep + 1:].strip()
        if not key:
            continue
        # 重复键：仅当新值非空且旧值为空时覆盖，否则保留首个
        if key in field_data and field_data[key] and not value:
            continue
        field_data[key] = value
    return field_data


def config_is_ready(ocr_engine=None):
    """检查当前 OCR 引擎 + DeepSeek 是否可运行"""
    cfg = load_config()
    engine = ocr_engine or get_ocr_engine(cfg)
    ds = get_deepseek_config()
    if not is_valid_api_key(ds.get("api_key")):
        return False
    if engine == "mineru_api":
        from mineru_api import check_mineru_api_available

        ok, _ = check_mineru_api_available(cfg)
        return ok
    if engine == "mineru":
        from mineru_ocr import check_mineru_available

        ok, _ = check_mineru_available(cfg)
        return ok
    bd = get_baidu_config()
    return bool(
        is_valid_api_key(bd.get("APP_ID"))
        and is_valid_api_key(bd.get("API_KEY"))
        and is_valid_api_key(bd.get("SECRET_KEY"))
    )


def config_is_ready_v2():
    return config_is_ready(ocr_engine="mineru")


def apply_ocr_engine(
    engine: str,
    mineru_cli_path: str = None,
    max_pages: int = None,
    api_token: str = None,
):
    """GUI 切换 OCR 时写入 config.json（合并写入，不覆盖未改动的 mineru 字段）"""
    cfg = load_config()
    cfg.setdefault("ocr", {})["engine"] = (engine or "baidu").strip().lower()
    mu = cfg.setdefault("mineru", {})
    if mineru_cli_path is not None:
        mu["cli_path"] = mineru_cli_path.strip()
    if api_token is not None:
        from mineru_api import normalize_mineru_api_token

        mu["api_token"] = normalize_mineru_api_token(api_token)
    if max_pages is not None:
        try:
            cfg.setdefault("local_ocr", {})["max_pages"] = int(max_pages)
        except (TypeError, ValueError):
            cfg.setdefault("local_ocr", {})["max_pages"] = 0
    save_config(cfg)
    return cfg


def output_docx_only(config=None) -> bool:
    """V2 默认仅输出 5 份 docx，不生成 zip/pdf/json"""
    cfg = config or load_config()
    return bool((cfg.get("output") or {}).get("docx_only", True))


def get_fill_mode(config=None) -> str:
    """表格填充模式：textbox | atomic"""
    cfg = config or load_config()
    mode = (cfg.get("fill") or {}).get("mode", "textbox").strip().lower()
    return mode if mode in ("textbox", "atomic") else "textbox"


def get_extraction_mode(config=None) -> str:
    """字段提取模式：segmented | legacy"""
    cfg = config or load_config()
    mode = (cfg.get("extraction") or {}).get("mode", "segmented").strip().lower()
    return mode if mode in ("segmented", "legacy") else "segmented"


def config_status_message(ocr_engine=None) -> str:
    """返回当前配置状态简述（供状态栏）"""
    cfg = load_config()
    engine = ocr_engine or get_ocr_engine(cfg)
    ds = get_deepseek_config()
    if not is_valid_api_key(ds.get("api_key")):
        return "待配置 DeepSeek API Key"
    if engine == "mineru_api":
        from mineru_api import check_mineru_api_available

        ok, msg = check_mineru_api_available(cfg)
        if ok:
            return "MinerU API 已连通"
        return f"MinerU API: {msg}"
    if engine == "mineru":
        from mineru_ocr import check_mineru_available

        ok, msg = check_mineru_available(cfg)
        if ok:
            short = msg[:40] + "…" if len(msg) > 40 else msg
            return f"MinerU 就绪 · {short}"
        return f"MinerU: {msg}"
    bd = get_baidu_config()
    if bd.get("APP_ID") and bd.get("API_KEY") and bd.get("SECRET_KEY"):
        return "百度 OCR 已配置"
    return "待配置百度 OCR 密钥"
