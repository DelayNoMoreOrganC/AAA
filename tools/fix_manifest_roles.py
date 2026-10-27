#!/usr/bin/env python3
"""修正映射表：含 placeholder 的格不应标为 header"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from template_manifest import TEMPLATE_NAMES, classify_placeholder, get_manifests_dir


def fix_manifest(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    changed = 0
    for tbl in data.get("tables", []):
        for cell in tbl.get("cells", []):
            ph = cell.get("placeholder")
            if not ph:
                continue
            want = classify_placeholder(ph)
            if "PDF" in ph and "法院" in ph and want == "fill":
                want = "seq_fill"
            if cell.get("role") != want:
                cell["role"] = want
                changed += 1
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return changed


def main():
    d = get_manifests_dir()
    for name in TEMPLATE_NAMES:
        p = os.path.join(d, f"{name}.json")
        if os.path.isfile(p):
            n = fix_manifest(p)
            print(f"{name}: {n} 处已修正")


if __name__ == "__main__":
    main()
