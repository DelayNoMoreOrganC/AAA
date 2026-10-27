#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 manifest 可填格添加 textbox.shape_name 映射（V2.0.3）"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from template_manifest import TEMPLATE_NAMES, get_fill_cells, load_manifest, manifest_path
from textbox_fill import default_shape_name


def _max_chars_for_placeholder(ph: str) -> int:
    if not ph:
        return 0
    if any(x in ph for x in ("结案小结", "审（办）结果", "审办结果", "案情简介")):
        return 200
    if "法院文件" in ph or "清单" in ph:
        return 120
    if len(ph) > 20:
        return 150
    return 80


def patch_manifest(template_name: str) -> int:
    path = manifest_path(template_name)
    data = load_manifest(template_name)
    count = 0
    for tbl in data.get("tables") or []:
        ti = tbl.get("table_index", 1)
        for cell in tbl.get("cells") or []:
            role = cell.get("role", "")
            if role not in ("fill", "clear", "seq_fill", "header_fill"):
                continue
            shape = default_shape_name(template_name, ti, cell["row"], cell["col"])
            ph = cell.get("placeholder", "")
            cell["textbox"] = {
                "shape_name": shape,
                "max_chars": _max_chars_for_placeholder(ph),
            }
            count += 1
    data["version"] = 3
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return count


def main():
    total = 0
    for name in TEMPLATE_NAMES:
        n = patch_manifest(name)
        print(f"[OK] {name}: {n} 个可填格已添加 textbox 映射")
        total += n
    print(f"\n合计 {total} 个可填格")
    return 0


if __name__ == "__main__":
    sys.exit(main())
