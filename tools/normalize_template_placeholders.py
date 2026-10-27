#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫描模板中【】是否跨多个 Run；报告需人工在 Word 中重键入的单元格。
可选 --fix：在单格内将占位符重设为连续文本（仅当该格仅含占位符时安全）。
"""

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pythoncom
import win32com.client

from field_mapping import get_template_paths
from template_manifest import PLACEHOLDER_RE, TEMPLATE_NAMES


def _plain(raw):
    return (raw or "").replace("\x07", "").replace("\r", "")


def _runs_span_placeholder(cell_rng, token: str) -> tuple:
    """返回 (run_count_covering_token, ok)"""
    try:
        runs = cell_rng.Runs
        if runs.Count <= 1:
            return 1, True
        plain = _plain(cell_rng.Text)
        idx = plain.find(token)
        if idx < 0:
            return 0, False
        end = idx + len(token)
        pos = 0
        touched = 0
        for i in range(1, runs.Count + 1):
            t = _plain(runs(i).Text)
            r_start, r_end = pos, pos + len(t)
            if r_end > idx and r_start < end:
                touched += 1
            pos = r_end
        return touched, touched <= 1
    except Exception:
        return -1, False


def scan_doc(path: str, name: str, fix: bool = False) -> list:
    subprocess.run(
        ["taskkill", "/F", "/IM", "WINWORD.EXE"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    issues = []
    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Open(os.path.abspath(path))
        try:
            for ti in range(1, doc.Tables.Count + 1):
                table = doc.Tables(ti)
                for ri in range(1, table.Rows.Count + 1):
                    row = table.Rows(ri)
                    for ci in range(1, row.Cells.Count + 1):
                        try:
                            rng = row.Cells(ci).Range
                            raw = rng.Text or ""
                            for ph in PLACEHOLDER_RE.findall(raw):
                                token = f"【{ph}】"
                                n, ok = _runs_span_placeholder(rng, token)
                                if not ok:
                                    issues.append(
                                        f"{name} T{ti} R{ri} C{ci} {token} 跨 {n} 个 Run"
                                    )
                                    if fix:
                                        plain = _plain(raw)
                                        if plain.strip() == token:
                                            rng.Text = token
                        except Exception:
                            pass
            if fix and issues:
                doc.Save()
        finally:
            doc.Close(False)
    finally:
        try:
            word.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="尝试修复仅含单个占位符的格")
    args = ap.parse_args()
    paths = get_template_paths()
    all_issues = []
    for name in TEMPLATE_NAMES:
        path = paths.get(name)
        if not path or not os.path.isfile(path):
            print(f"[SKIP] {name}")
            continue
        print(f"[SCAN] {name}")
        issues = scan_doc(path, name, fix=args.fix)
        all_issues.extend(issues)
        for i in issues:
            print(f"       {i}")
    if not all_issues:
        print("\n[OK] 未发现跨 Run 占位符")
        return 0
    print(f"\n[WARN] 共 {len(all_issues)} 项，建议在 Word 中重键入【】后运行 generate_template_manifest.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
