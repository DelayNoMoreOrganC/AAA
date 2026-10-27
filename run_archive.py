#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行：一份 PDF → 归档资料；支持批量与分类多文件

V4 新增：--catalog / --skip-missing 完整归档支持
V4 优化：简化参数、智能默认、进度显示
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from archive_pipeline import process_archive, process_archive_sources
from archive_pipeline import (  # V4
    analyze_archive,
    assemble_archive,
    write_archive_report,
    apply_adjustments,
)
from batch_processor import process_batch
from document_segmenter import DocumentSource, guess_doc_type_from_filename
from settings import load_config

# V4 新增
try:
    import archive_catalog as ac
except ImportError:
    ac = None


class ProgressIndicator:
    """运行进度指示器"""

    STAGES = {
        "init": "初始化系统...",
        "ocr": "OCR 文字识别中...",
        "segment": "文档切分中...",
        "extract": "信息提取中...",
        "fill": "模板填充中...",
        "merge": "PDF 合并中...",
        "complete": "处理完成"
    }

    def __init__(self, enabled=True, quiet=False):
        self.enabled = enabled
        self.quiet = quiet
        self.current_stage = None
        self.start_time = None

    def show_stage(self, stage):
        """显示当前处理阶段"""
        if not self.enabled or self.quiet:
            return

        if self.current_stage != stage:
            self.current_stage = stage
            message = self.STAGES.get(stage, f"处理阶段: {stage}")

            if self.start_time:
                elapsed = time.time() - self.start_time
                print(f"[{elapsed:.1f}s] {message}")
            else:
                print(f"[启动] {message}")
                self.start_time = time.time()

    def complete(self, success=True, message=""):
        """完成处理"""
        if not self.enabled or self.quiet:
            return

        if self.start_time:
            elapsed = time.time() - self.start_time
            status = "成功" if success else "失败"
            print(f"[完成] 处理{status} - 用时 {elapsed:.1f}秒")
            if message:
                print(f"      {message}")

    def error(self, message):
        """显示错误"""
        if not self.quiet:
            print(f"[错误] {message}")


def parse_sources(items):
    sources = []
    for item in items:
        if ":" in item:
            path, doc_type = item.rsplit(":", 1)
        else:
            path, doc_type = item, guess_doc_type_from_filename(item)
        sources.append(DocumentSource(path=path.strip(), doc_type=doc_type.strip()))
    return sources


def parse_supplements(items):
    """解析 --supplement SEQ:FILE 列表 → {seq: [文件路径]}"""
    supplements = {}
    for item in items or []:
        if ":" not in item:
            print(f"[WARN] 忽略无效 --supplement（应为 SEQ:FILE）: {item}")
            continue
        seq_str, path = item.split(":", 1)
        seq_str, path = seq_str.strip(), path.strip()
        if not seq_str.isdigit():
            print(f"[WARN] 忽略无效 seq: {item}")
            continue
        if not os.path.exists(path):
            print(f"[WARN] 补充文件不存在，忽略: {path}")
            continue
        supplements.setdefault(int(seq_str), []).append(path)
    return supplements


def main():
    parser = argparse.ArgumentParser(
        description="案件档案一键归档 V4 - 智能归档系统",
        epilog="""
使用示例:
  # 简单归档（使用智能默认参数）
  python run_archive.py 案件.pdf

  # 完整归档（民事案件）
  python run_archive.py 案件.pdf --catalog civil

  # 批量处理
  python run_archive.py --batch 案件1.pdf 案件2.pdf 案件3.pdf

  # 查看详细帮助
  python run_archive.py --help
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # 主要参数（简化）
    parser.add_argument("pdf", nargs="?", help="单个 PDF 路径（可选）")
    parser.add_argument("--batch", nargs="+", metavar="PDF", help="批量处理：多个 PDF 文件")

    # 智能默认参数
    parser.add_argument("--max-pages", type=int, default=0, help="OCR 最大页数（默认: 0=全部）")
    parser.add_argument("--engine", choices=["auto", "baidu", "mineru", "mineru_api"], default="auto",
                        help="OCR 引擎（默认: auto=智能选择）")

    # 完整归档参数
    parser.add_argument("--catalog", metavar="TYPE", choices=["civil", "criminal", "admin", "nonlit", "counsel"],
                        help="完整归档模式：案件类型")
    parser.add_argument("--skip-missing", action="store_true",
                        help="完整归档：跳过所有缺失项（无需确认）")
    parser.add_argument("--output", metavar="PDF", help="完整归档：输出 PDF 路径")
    parser.add_argument("--order-mode", choices=["catalog", "original"], default="catalog",
                        help="正文排序模式（默认: catalog=按目录序）")

    # 高级参数
    parser.add_argument("--sources", nargs="+", metavar="FILE:TYPE",
                        help="分类多文件，如 判决.pdf:judgment 合同.pdf:contract")
    parser.add_argument("--supplement", nargs="+", metavar="SEQ:FILE",
                        help="补充缺失项，如 2:发票.pdf 7:证据.pdf")
    parser.add_argument("--adjustments", metavar="JSON",
                        help="手动调序调整 JSON 文件")

    # 界面选项
    parser.add_argument("--progress", action="store_true", default=True,
                        help="显示运行进度（默认: 开启）")
    parser.add_argument("--quiet", action="store_true",
                        help="静默模式，减少输出")

    args = parser.parse_args()

    # 创建进度指示器
    progress = ProgressIndicator(enabled=args.progress, quiet=args.quiet)

    # V4 完整归档模式
    if args.catalog:
        if ac is None:
            print("[FAIL] archive_catalog 模块未找到")
            sys.exit(1)

        config = load_config()
        if args.order_mode:
            config.setdefault("archive", {})["order_mode"] = args.order_mode
        case_type_label = ac.CASE_TYPE_LABELS.get(args.catalog, args.catalog)

        if args.sources:
            sources = parse_sources(args.sources)
            for s in sources:
                if not os.path.exists(s.path):
                    print(f"[FAIL] PDF 不存在: {s.path}")
                    sys.exit(1)
            primary_name = os.path.splitext(os.path.basename(sources[0].path))[0]
        elif args.pdf and os.path.exists(args.pdf):
            sources = None
            primary_name = os.path.splitext(os.path.basename(args.pdf))[0]
        else:
            print("[FAIL] 完整归档需要 pdf 参数或 --sources")
            sys.exit(1)

        print(f"[V4 完整归档] 案件类型: {case_type_label}")
        print(f"[1/3] 分析归档...")
        if sources:
            analysis = analyze_archive(args.catalog, sources=sources, config=config, log=print)
        else:
            analysis = analyze_archive(args.catalog, args.pdf, config, log=print)

        # 应用手动调序/归属调整（与 GUI 调序等价）
        if args.adjustments:
            if not os.path.exists(args.adjustments):
                print(f"[FAIL] 调整文件不存在: {args.adjustments}")
                sys.exit(1)
            import json as _json
            try:
                with open(args.adjustments, "r", encoding="utf-8") as f:
                    adj = _json.load(f)
            except (OSError, ValueError) as e:
                print(f"[FAIL] 调整文件解析失败: {e}")
                sys.exit(1)
            apply_adjustments(analysis, adj, log=print)

        # 解析补充文件（按 seq 直达）
        supplements = parse_supplements(args.supplement)
        if supplements:
            total = sum(len(v) for v in supplements.values())
            print(f"\n补充文件: {total} 个，覆盖 seq {sorted(supplements)}")

        # 处理缺失项
        if analysis.missing_items:
            missing_seqs = [item["seq"] for item in analysis.missing_items]
            # 已由 --supplement 覆盖的不算缺失
            uncovered = [s for s in missing_seqs if s not in supplements]

            print(f"\n缺失项 ({len(analysis.missing_items)}):")
            for item in analysis.missing_items:
                tag = " [已补充]" if item["seq"] in supplements else ""
                print(f"  [{item['seq']}] {item['name']} ({item['source']}){tag}")

            if not uncovered:
                print("\n所有缺失项已由 --supplement 覆盖")
                skipped = []
            elif args.skip_missing:
                skipped = uncovered
                print(f"\n--skip-missing: 跳过未补充的缺失项 {uncovered}")
            else:
                # 与 GUI 人工闸门语义对齐：未补充且未显式跳过 → 非零退出，提示用户
                print("\n以下缺失项未补充：", uncovered)
                print("请用 --supplement SEQ:FILE 补充，或用 --skip-missing 显式跳过。")
                sys.exit(2)
        else:
            print("\n无缺失项")
            skipped = []

        # 生成输出路径
        output_pdf = args.output
        if not output_pdf:
            output_pdf = f"{primary_name}_完整归档.pdf"

        print(f"\n[2/3] 拼装归档 PDF...")
        result = assemble_archive(
            analysis, output_pdf, supplements=supplements or None,
            skipped=skipped, config=config, log=print,
        )

        # 写结构化报告（缺失/页守恒/排序问题）
        write_archive_report(analysis, result, output_pdf, log=print)

        print(f"\n[3/3] 完成")
        print("=" * 60)
        if result.success:
            print(f"[OK] 完整归档 PDF: {result.output_pdf}")
            print(f"  页数: {result.page_count}")
            print(f"  源 PDF 纳入: {result.original_pages_included} 页")
            if result.missing:
                print(f"  缺失/跳过: {len(result.missing)} 项")
            if result.order_issues:
                print(f"  排序问题: {len(result.order_issues)} 项")
            sys.exit(0)
        else:
            print("[FAIL] 归档失败")
            print(f"  源 PDF 纳入: {result.original_pages_included} 页")
            for it in (result.order_issues or [])[:5]:
                print(f"    - {it.get('description', it)}")
            sys.exit(1)

    # V3 批量/分类模式
    if args.batch:
        result = process_batch(args.batch, max_pages=args.max_pages or None, log=print)
    elif args.sources:
        sources = parse_sources(args.sources)
        result = process_archive_sources(
            sources, max_pages=args.max_pages or None, log=print
        )
    elif args.pdf:
        result = process_archive(args.pdf, max_pages=args.max_pages or None, log=print)
    else:
        parser.print_help()
        sys.exit(1)

    print()
    print("=" * 60)
    if result.get("batch_root"):
        print(f"[OK] 批量完成 {result.get('ok_count')}/{result.get('total')}")
        print(f"  批次目录: {result['batch_root']}")
        sys.exit(0 if result.get("success") else 1)

    if result.get("success"):
        print("[OK] 归档完成")
        print(f"  输出目录: {result['output_dir']}")
        if result.get("layout_issues"):
            print(f"  版式待核对: {len(result['layout_issues'])} 项")
        sys.exit(0)
    print("[FAIL] 失败:", result.get("error"))
    sys.exit(1)


if __name__ == "__main__":
    main()
