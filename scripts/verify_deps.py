#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依赖验证脚本 - 检查 V4 所需依赖是否已安装

缺失时给出 pip 安装命令，方便用户一键补齐。
"""

import importlib.util
import sys


# (import 名, pip 显示名) - import 名与 pip 包名不一致的（如 rapidocr_onnxruntime）
# 以 import 名为准，这样 verify 通过 = 代码能跑。
V4_DEPS = [
    ("rapidocr_onnxruntime", "rapidocr-onnxruntime"),
    ("fitz", "PyMuPDF"),
    ("win32com", "pywin32"),
    ("PIL", "Pillow"),
    ("onnxruntime", "onnxruntime"),
    ("docx", "python-docx"),
    ("requests", "requests"),
    ("tkinterdnd2", "tkinterdnd2"),
]


def check_deps():
    """检查所有依赖，返回 (是否齐全, 缺失 pip 包名列表)"""
    missing = []
    ok = []
    for module_name, pip_name in V4_DEPS:
        if importlib.util.find_spec(module_name) is not None:
            ok.append(pip_name)
        else:
            missing.append(pip_name)

    print(f"[OK] 已安装: {', '.join(ok)}")
    if missing:
        print(f"[FAIL] 缺失依赖: {', '.join(missing)}")
        py = sys.executable
        print(f"[HINT] 安装: {py} -m pip install {' '.join(missing)}")
        return False, missing
    print("[OK] 所有 V4 依赖已安装")
    return True, missing


if __name__ == "__main__":
    success, _ = check_deps()
    sys.exit(0 if success else 1)
