#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EXE / 开发模式统一路径（PyInstaller 兼容）"""

import os
import sys
import shutil


def is_frozen():
    return getattr(sys, "frozen", False)


def get_app_dir():
    """可写目录：EXE 所在文件夹（配置、输出）"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_dir():
    """只读资源：打包内 _MEIPASS 或项目根目录"""
    if is_frozen():
        return getattr(sys, "_MEIPASS", get_app_dir())
    return os.path.dirname(os.path.abspath(__file__))


def get_config_path():
    return os.path.join(get_app_dir(), "config.json")


def get_config_example_path():
    p = os.path.join(get_resource_dir(), "config.json.example")
    if os.path.exists(p):
        return p
    return os.path.join(get_app_dir(), "config.json.example")


def get_outputs_dir():
    d = os.path.join(get_app_dir(), "outputs")
    os.makedirs(d, exist_ok=True)
    return d


def get_templates_dir():
    """优先 EXE 旁 templates/bundled，否则打包内资源"""
    for base in (get_app_dir(), get_resource_dir()):
        d = os.path.join(base, "templates", "bundled")
        if os.path.isdir(d) and any(f.endswith(".doc") for f in os.listdir(d)):
            return d
    return os.path.join(get_resource_dir(), "templates", "bundled")


def get_prompt_path():
    p = os.path.join(get_resource_dir(), "prompts", "extract_prompt.txt")
    if os.path.exists(p):
        return p
    return os.path.join(get_app_dir(), "prompts", "extract_prompt.txt")


def get_template_paths():
    d = get_templates_dir()
    names = ["立案审批表", "送达材料清单", "档案卷宗", "结案报告表", "质量监督卡"]
    paths = {}
    for name in names:
        paths[name] = os.path.join(d, f"{name}.doc")
    return paths


def get_catalog_template_path(case_type: str) -> str:
    """五类卷内目录 Word 模板路径（仅填页码）"""
    try:
        import archive_catalog as ac
        fn = ac.get_catalog_template_filename(case_type)
    except Exception:
        fn = f"卷内目录_{case_type}.doc"
    d = get_templates_dir()
    p = os.path.join(d, fn)
    if os.path.isfile(p):
        return p
    alt = os.path.join(get_app_dir(), "templates", "bundled", fn)
    return alt if os.path.isfile(alt) else p


def get_manifests_dir():
    """单元格映射表：优先 EXE 旁 templates/manifests，否则打包内资源"""
    for base in (get_app_dir(), get_resource_dir()):
        d = os.path.join(base, "templates", "manifests")
        if os.path.isdir(d) and any(f.endswith(".json") for f in os.listdir(d)):
            return d
    return os.path.join(get_resource_dir(), "templates", "manifests")


def ensure_app_dirs():
    os.makedirs(get_outputs_dir(), exist_ok=True)
    os.makedirs(get_templates_dir(), exist_ok=True)


def init_config_if_missing():
    cfg = get_config_path()
    if os.path.exists(cfg):
        return cfg
    ex = get_config_example_path()
    if os.path.exists(ex):
        shutil.copy2(ex, cfg)
    return cfg
