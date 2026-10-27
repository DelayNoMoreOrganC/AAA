#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 MinerU V2 运行环境"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from settings import load_config, config_is_ready_v2, get_ocr_engine
from mineru_ocr import (
    check_mineru_available,
    check_pipeline_dependencies,
    get_mineru_settings,
    python_for_mineru_cli,
)


def main():
    print("=== MinerU V2 环境检查 ===\n")
    cfg = load_config()
    print(f"OCR 引擎: {get_ocr_engine(cfg)}")
    ok, msg = check_mineru_available(cfg)
    print(f"MinerU CLI: {'OK' if ok else 'FAIL'} — {msg}")
    m = get_mineru_settings(cfg)
    print(f"精细度: {m['quality']} ({m['backend']} / {m['method']})")
    print(f"GPU: cuda:{m['gpu_device']}, 渲染线程: {m['render_threads']}")
    print(f"DeepSeek + MinerU 可归档: {config_is_ready_v2()}")
    py = python_for_mineru_cli(m.get("cli_path", ""))
    print(f"MinerU Python: {py or '未定位'}")
    dep_ok, dep_msg = check_pipeline_dependencies(m.get("cli_path", ""))
    print(f"Pipeline 依赖: {'OK' if dep_ok else 'FAIL'} — {dep_msg}")
    print("\n详见 MINERU_V2_SETUP.md")


if __name__ == "__main__":
    main()
