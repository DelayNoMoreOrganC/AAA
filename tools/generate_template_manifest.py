#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Word 模板扫描生成 templates/manifests/*.json 初稿"""

import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pythoncom
import win32com.client

from field_mapping import get_template_paths
from template_manifest import PLACEHOLDER_RE, classify_placeholder, TEMPLATE_NAMES

PLAIN_TOKEN_RE = re.compile(r"(=[\w\u4e00-\u9fff+]+)")


def _cell_preview(text: str, max_len=60) -> str:
    t = (text or "").replace("\x07", "").replace("\r", " ").strip()
    if len(t) > max_len:
        return t[: max_len - 3] + "..."
    return t


def _plain_cell(raw: str) -> str:
    return (raw or "").replace("\x07", "").replace("\r", "").replace("\n", "")


def _offset_for_token(plain: str, ph: str) -> dict:
    token = f"【{ph}】"
    idx = plain.find(token)
    if idx < 0:
        return {}
    return {"start": idx, "len": len(token)}


def _scan_table(table, table_index: int) -> list:
    cells = []
    for ri in range(1, table.Rows.Count + 1):
        row = table.Rows(ri)
        for ci in range(1, row.Cells.Count + 1):
            try:
                raw = row.Cells(ci).Range.Text or ""
            except Exception:
                continue
            plain = _plain_cell(raw)
            plain_stripped = plain.strip()
            placeholders = PLACEHOLDER_RE.findall(raw)
            plain_tokens = PLAIN_TOKEN_RE.findall(plain_stripped)

            if placeholders:
                for ph in placeholders:
                    role = classify_placeholder(ph)
                    entry = {
                        "row": ri,
                        "col": ci,
                        "role": role,
                        "placeholder": ph,
                        "preview": _cell_preview(plain_stripped),
                    }
                    off = _offset_for_token(plain, ph)
                    if off:
                        entry["offset"] = off
                    if role == "fill" and "PDF" in ph and "法院" in ph:
                        entry["role"] = "seq_fill"
                    cells.append(entry)
            elif plain_tokens:
                for tok in plain_tokens:
                    entry = {
                        "row": ri,
                        "col": ci,
                        "role": "fill",
                        "placeholder": tok,
                        "preview": _cell_preview(plain_stripped),
                    }
                    idx = plain.find(tok)
                    if idx >= 0:
                        entry["offset"] = {"start": idx, "len": len(tok)}
                    cells.append(entry)
            elif plain:
                note = _cell_preview(plain, 30)
                # 仅无占位符的首行表头列为 header
                role = "header" if ri == 1 and len(plain) <= 8 else "fixed"
                cells.append(
                    {
                        "row": ri,
                        "col": ci,
                        "role": role,
                        "note": note,
                        "preview": _cell_preview(plain),
                    }
                )
    return cells


def _scan_paragraphs(doc, table_start) -> list:
    paragraphs = []
    for i in range(1, min(doc.Paragraphs.Count + 1, 80)):
        try:
            para = doc.Paragraphs(i)
            if table_start and para.Range.Start >= table_start:
                break
            raw = para.Range.Text or ""
            if "\x07" in raw and "【" not in raw:
                continue
            placeholders = PLACEHOLDER_RE.findall(raw)
            plain = raw.replace("\r", "").strip()
            if not placeholders and not plain.strip():
                continue
            for ph in placeholders:
                paragraphs.append(
                    {
                        "index": i,
                        "role": classify_placeholder(ph),
                        "placeholder": ph,
                        "preview": _cell_preview(plain),
                    }
                )
            if placeholders:
                continue
            if plain and len(plain) < 120:
                paragraphs.append(
                    {
                        "index": i,
                        "role": "fixed",
                        "note": _cell_preview(plain, 40),
                        "preview": _cell_preview(plain),
                    }
                )
        except Exception:
            pass
    return paragraphs


def _manifest_from_doc(doc, name: str, doc_path: str) -> dict:
    table_start = doc.Tables(1).Range.Start if doc.Tables.Count else None
    tables = []
    for ti in range(1, doc.Tables.Count + 1):
        tables.append(
            {
                "table_index": ti,
                "rows": doc.Tables(ti).Rows.Count,
                "cells": _scan_table(doc.Tables(ti), ti),
            }
        )
    return {
        "template": name,
        "version": 2,
        "source_doc": os.path.basename(doc_path),
        "tables": tables,
        "paragraphs": _scan_paragraphs(doc, table_start),
    }


def _scan_one(name: str, path: str) -> dict:
    subprocess.run(
        ["taskkill", "/F", "/IM", "WINWORD.EXE"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Open(os.path.abspath(path))
        try:
            return _manifest_from_doc(doc, name, path)
        finally:
            doc.Close(False)
    finally:
        try:
            word.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def main():
    out_dir = os.path.join(ROOT, "templates", "manifests")
    os.makedirs(out_dir, exist_ok=True)
    paths = get_template_paths()
    for name in TEMPLATE_NAMES:
        path = paths.get(name)
        if not path or not os.path.isfile(path):
            print(f"[SKIP] {name}: 模板不存在")
            continue
        print(f"[SCAN] {name} ...")
        manifest = _scan_one(name, path)
        out_path = os.path.join(out_dir, f"{name}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        n_fill = sum(
            1
            for t in manifest["tables"]
            for c in t["cells"]
            if c.get("role") in ("fill", "clear", "seq_fill", "header_fill")
        )
        print(f"       -> {out_path} ({n_fill} 可填格)")
    print("\n[完成] 请人工核对 JSON 中 fixed/header 与 fill 划分。")


if __name__ == "__main__":
    main()
