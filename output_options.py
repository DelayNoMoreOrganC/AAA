#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归档输出模式与模板选择"""

OUTPUT_MODE_ALL = "all_docx"
OUTPUT_MODE_SELECT = "select_docx"

ALL_TEMPLATES = (
    "立案审批表",
    "送达材料清单",
    "档案卷宗",
    "结案报告表",
    "质量监督卡",
)

# 各模板生成 PDF 时的页数预算（质量监督卡含委托人须知 + 质量监督卡，共 2 页）
TEMPLATE_PAGE_BUDGET = {
    "档案卷宗": 1,
    "结案报告表": 1,
    "立案审批表": 1,
    "送达材料清单": 1,
    "质量监督卡": 2,
}


def normalize_output_options(options=None) -> dict:
    """返回 {mode, templates}"""
    opts = dict(options or {})
    mode = (opts.get("mode") or OUTPUT_MODE_ALL).strip()
    # 兼容旧配置 merged_pdf → 自选 docx
    if mode == "merged_pdf":
        mode = OUTPUT_MODE_SELECT
    if mode not in (OUTPUT_MODE_ALL, OUTPUT_MODE_SELECT):
        mode = OUTPUT_MODE_ALL
    selected = opts.get("templates")
    if selected is None:
        selected = list(ALL_TEMPLATES)
    else:
        selected = [t for t in selected if t in ALL_TEMPLATES]
    if mode == OUTPUT_MODE_SELECT and not selected:
        selected = list(ALL_TEMPLATES)
    return {"mode": mode, "templates": selected}


def templates_to_fill(options=None) -> list:
    """需要生成 docx 的模板名列表"""
    opts = normalize_output_options(options)
    if opts["mode"] == OUTPUT_MODE_ALL:
        return list(ALL_TEMPLATES)
    return list(opts["templates"])


def mode_label(mode: str) -> str:
    return {
        OUTPUT_MODE_ALL: "全部 5 份 docx",
        OUTPUT_MODE_SELECT: "自选 docx",
    }.get(mode, mode)
