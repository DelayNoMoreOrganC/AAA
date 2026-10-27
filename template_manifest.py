#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模板单元格映射表：加载、校验、可填格枚举"""

import json
import os
import re

PLACEHOLDER_RE = re.compile(r"【([^】]+)】")
CLEAR_PLACEHOLDER_HINTS = ("留空", "字体格式要求")

TEMPLATE_NAMES = (
    "立案审批表",
    "送达材料清单",
    "档案卷宗",
    "结案报告表",
    "质量监督卡",
)


def get_manifests_dir():
    try:
        from app_paths import get_manifests_dir as _d

        return _d()
    except ImportError:
        return os.path.join(os.path.dirname(__file__), "templates", "manifests")


def manifest_path(template_name: str) -> str:
    return os.path.join(get_manifests_dir(), f"{template_name}.json")


def load_manifest(template_name: str) -> dict:
    path = manifest_path(template_name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"缺少映射表: {path}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("template", template_name)
    data.setdefault("version", 1)
    data.setdefault("tables", [])
    data.setdefault("paragraphs", [])
    return data


def _is_clear_placeholder(name: str) -> bool:
    return any(h in (name or "") for h in CLEAR_PLACEHOLDER_HINTS)


def classify_placeholder(name: str) -> str:
    if _is_clear_placeholder(name):
        return "clear"
    return "fill"


def get_fill_cells(manifest: dict):
    """返回需写入的表格单元格（fill/clear/seq_fill/header_fill）"""
    out = []
    for tbl in manifest.get("tables") or []:
        ti = tbl.get("table_index", 1)
        for cell in tbl.get("cells") or []:
            role = cell.get("role", "")
            if role in ("fill", "clear", "seq_fill", "header_fill"):
                out.append({**cell, "table_index": ti})
    return out


def get_fixed_cells(manifest: dict):
    out = []
    for tbl in manifest.get("tables") or []:
        ti = tbl.get("table_index", 1)
        for cell in tbl.get("cells") or []:
            if cell.get("role") == "fixed":
                out.append({**cell, "table_index": ti})
    return out


def get_paragraph_fills(manifest: dict):
    out = []
    for p in manifest.get("paragraphs") or []:
        role = p.get("role", "fill")
        if role in ("fill", "clear", "header_fill"):
            out.append(p)
    return out


def group_cell_offset_hints(fill_cells) -> dict:
    """{(ti, row, col): {placeholder_name: {start, len}}}"""
    hints = {}
    for cell in fill_cells:
        ph = cell.get("placeholder")
        off = cell.get("offset")
        if not ph or not off:
            continue
        key = (cell["table_index"], cell["row"], cell["col"])
        hints.setdefault(key, {})[ph] = off
    return hints


def group_cell_patches(fill_cells, field_patch: dict) -> dict:
    """
    按 (table_index, row, col) 合并占位符补丁。
    返回 {(ti, row, col): {placeholder: value, ...}}
    """
    grouped = {}
    # 调试日志
    debug_template = any("送达材料清单" in str(cell.get("template", "")) for cell in fill_cells) or len(fill_cells) > 50

    for cell in fill_cells:
        ph = cell.get("placeholder")
        if not ph:
            continue
        # 调试日志
        if debug_template and "律师" in ph:
            print(f"  [DEBUG group] 处理占位符: {ph}")
        key = (cell["table_index"], cell["row"], cell["col"])
        val = field_patch.get(ph)
        if cell.get("role") == "clear":
            val = ""
        if val is None and cell.get("role") != "clear":
            continue
        grouped.setdefault(key, {})[ph] = "" if val is None else str(val)
    return grouped


def build_field_patch(field_data: dict) -> dict:
    """field_data 已为 expand_fields_for_template 结果"""
    patch = {}
    for k, v in (field_data or {}).items():
        if k.startswith("__seq__"):
            continue
        if v is None:
            continue
        patch[k] = str(v)
    return patch


def validate_manifest_against_doc(doc, manifest: dict) -> list:
    """校验 fill 格是否仍含对应【占位符】；返回错误信息列表"""
    errors = []
    for cell in get_fill_cells(manifest):
        if cell.get("role") == "seq_fill":
            continue
        ph = cell.get("placeholder", "")
        bracketed = f"【{ph}】"
        try:
            ti = cell["table_index"]
            if ti < 1 or ti > doc.Tables.Count:
                errors.append(f"table_index={ti} 不存在")
                continue
            table = doc.Tables(ti)
            row = table.Rows(cell["row"])
            text = row.Cells(cell["col"]).Range.Text or ""
            if bracketed not in text and cell.get("role") != "clear":
                preview = text.replace("\r", "")[:40]
                errors.append(
                    f"T{ti} R{cell['row']} C{cell['col']} 缺少 {bracketed[:30]}… 当前:{preview!r}"
                )
        except Exception as e:
            errors.append(f"T{cell.get('table_index')} R{cell.get('row')} C{cell.get('col')}: {e}")
    return errors
