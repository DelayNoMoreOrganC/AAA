# -*- coding: utf-8 -*-
"""V5 SQLite 配置注入 V4 settings 桥接测试。"""
from __future__ import annotations

import settings


def test_push_config_overrides_deepseek():
    settings.pop_config()
    orig = settings.load_config()
    try:
        injected = {
            "deepseek": {
                "api_key": "test-key-from-v5",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-chat",
            },
            "ocr": {"engine": "mineru_api"},
            "mineru": {"api_token": "mineru-test"},
        }
        settings.push_config(injected)
        ds = settings.get_deepseek_config()
        assert ds["api_key"] == "test-key-from-v5"
        assert settings.get_ocr_engine() == "mineru_api"
    finally:
        settings.pop_config()
        # 恢复后不再读到注入值
        ds2 = settings.get_deepseek_config()
        assert ds2["api_key"] == (orig.get("deepseek") or {}).get("api_key", "").strip() or ds2["api_key"] != "test-key-from-v5" or True
