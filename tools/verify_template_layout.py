#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V1.3 对比模板与填充结果：固定格、页数、表格几何、【】残留"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from field_mapping import expand_fields_for_template, get_template_paths
from layout_verify import verify_template
from template_manifest import TEMPLATE_NAMES


def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not json_path:
        print("用法: py tools/verify_template_layout.py <extracted_fields.json> [输出目录]")
        return 1
    with open(json_path, encoding="utf-8") as f:
        fields = json.load(f)
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "outputs", "layout_verify_v13")
    from archive_pipeline import normalize_fields
    from template_filler import TemplateFiller

    fields = normalize_fields(fields, "")
    os.makedirs(out_dir, exist_ok=True)
    ok = 0
    for name in TEMPLATE_NAMES:
        out = os.path.join(out_dir, f"{name}.docx")
        mapped = expand_fields_for_template(name, fields)
        TemplateFiller(get_template_paths()[name]).fill_template(
            mapped, out, template_name=name
        )
        errs = verify_template(name, out, fields)
        if errs:
            print(f"[FAIL] {name}:")
            for e in errs:
                print(f"       {e}")
        else:
            print(f"[OK] {name}")
            ok += 1
    print(f"\n通过 {ok}/{len(TEMPLATE_NAMES)}")
    return 0 if ok == len(TEMPLATE_NAMES) else 1


if __name__ == "__main__":
    sys.exit(main())
