#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量案件归档处理

每案 1 个 PDF。
- full_archive=False（默认，V3 行为）：PDF → 5 份 docx，输出 outputs/batch_{ts}/。
- full_archive=True（V4）：每案走 analyze+assemble 完整归档，产出归档 PDF + docx。
  批量无人工闸门，缺失项自动跳过（等价 CLI --skip-missing）。
"""

import json
import os
from datetime import datetime
from typing import Callable, List, Optional

from archive_pipeline import process_archive, process_archive_sources
from archive_pipeline import analyze_archive, assemble_archive
from document_segmenter import DocumentSource


def _run_full_archive_case(
    pdf_path: str,
    case_type: str,
    case_dir: str,
    config: dict,
    log=print,
):
    """单案完整归档（V4），缺失项自动跳过。"""
    analysis = analyze_archive(
        case_type, original_pdf=pdf_path, config=config, log=log
    )
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    output_pdf = os.path.join(case_dir, f"{base_name}_完整归档.pdf")
    missing_seqs = [it["seq"] for it in analysis.missing_items]
    result = assemble_archive(
        analysis,
        output_pdf,
        skipped=missing_seqs,
        config=config,
        log=log,
    )
    return {
        "success": result.success,
        "output_pdf": result.output_pdf,
        "page_count": getattr(result, "page_count", 0),
        "missing": len(missing_seqs),
        "original_pages": getattr(result, "original_pages_included", 0),
    }


def process_batch(
    pdf_paths: List[str],
    max_pages=None,
    log=print,
    on_progress: Optional[Callable[[dict], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    output_options=None,
    *,
    full_archive: bool = False,
    case_type: str = "civil",
):
    """
    批量处理多个案件 PDF（每案 1 个 PDF）。
    输出：outputs/batch_{timestamp}/{序号}_{stem}_{子时间戳}/

    Args:
        full_archive: True 则每案走 V4 完整归档（analyze+assemble），缺失自动跳过。
        case_type: 案件类型（full_archive=True 时生效）。
    """
    if not pdf_paths:
        return {"success": False, "error": "未选择任何 PDF"}

    from app_paths import get_outputs_dir
    from settings import load_config

    batch_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode_tag = "完整归档" if full_archive else "批量"
    batch_root = os.path.join(get_outputs_dir(), f"{mode_tag}_{batch_stamp}")
    os.makedirs(batch_root, exist_ok=True)

    config = load_config() if full_archive else None
    results = []
    ok_count = 0

    for i, pdf_path in enumerate(pdf_paths, 1):
        if cancel_check and cancel_check():
            log(f"[BATCH] 用户取消，跳过剩余 {len(pdf_paths) - i + 1} 个")
            break

        stem = os.path.splitext(os.path.basename(pdf_path))[0]
        sub_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        case_dir = os.path.join(batch_root, f"{i:02d}_{stem}_{sub_stamp}")

        item = {"index": i, "pdf": pdf_path, "status": "running", "output_dir": case_dir}
        if on_progress:
            on_progress(item)

        log(f"\n[{mode_tag} {i}/{len(pdf_paths)}] {os.path.basename(pdf_path)}")
        if not os.path.isfile(pdf_path):
            item.update({"status": "failed", "error": "文件不存在"})
            results.append(item)
            if on_progress:
                on_progress(item)
            continue

        try:
            if full_archive:
                r = _run_full_archive_case(pdf_path, case_type, case_dir, config, log=log)
                if r["success"]:
                    ok_count += 1
                    item.update({"status": "success", "output_pdf": r["output_pdf"],
                                 "page_count": r["page_count"], "missing": r["missing"]})
                else:
                    item.update({"status": "failed", "error": "归档拼装失败"})
            else:
                r = process_archive(
                    pdf_path, output_dir=case_dir, max_pages=max_pages,
                    log=log, output_options=output_options,
                )
                if r.get("success"):
                    ok_count += 1
                    item.update({"status": "success", "field_count": r.get("field_count"),
                                 "verify_issues": r.get("verify_issues", []),
                                 "layout_issues": r.get("layout_issues", [])})
                else:
                    item.update({"status": "failed", "error": r.get("error")})
        except Exception as e:
            item.update({"status": "failed", "error": str(e)})
            log(f"[{mode_tag}] 异常: {e}")
        results.append(item)
        if on_progress:
            on_progress(item)

    summary_path = os.path.join(batch_root, "batch_summary.json")
    summary = {
        "batch_id": batch_stamp,
        "mode": "full_archive" if full_archive else "docx_only",
        "case_type": case_type if full_archive else None,
        "batch_root": batch_root,
        "total": len(pdf_paths),
        "success": ok_count,
        "failed": len(results) - ok_count,
        "cases": results,
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    log(f"\n[{mode_tag}] 完成 {ok_count}/{len(pdf_paths)}，汇总 → {summary_path}")

    return {
        "success": ok_count > 0,
        "batch_root": batch_root,
        "summary_path": summary_path,
        "ok_count": ok_count,
        "total": len(pdf_paths),
        "cases": results,
    }