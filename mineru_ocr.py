#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU 本地 OCR / 文档解析（V2）
https://github.com/opendatalab/MinerU

在 14900KF + 64G + RTX 3080 20G 上推荐使用 quality=ultra（pipeline + 强制 OCR，需 mineru[pipeline] + CUDA torch）。
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Callable, Optional, Tuple

LogFn = Callable[[str], None]

# 精细度预设（method/backend 见 MinerU CLI 文档）
# hybrid-auto-engine 需完整 mineru[all]；仅 pip install mineru 时请用 pipeline
QUALITY_PRESETS = {
    "ultra": {
        "backend": "pipeline",
        "method": "ocr",
        "lang": "ch",
        "formula_enable": True,
        "table_enable": True,
        "client_side_output": True,
    },
    "high": {
        "backend": "pipeline",
        "method": "auto",
        "lang": "ch",
        "formula_enable": True,
        "table_enable": True,
        "client_side_output": True,
    },
    "fast": {
        "backend": "pipeline",
        "method": "ocr",
        "lang": "ch",
        "formula_enable": False,
        "table_enable": True,
        "client_side_output": True,
    },
}


def get_mineru_settings(config: dict) -> dict:
    """合并 config.mineru 与 quality 预设"""
    raw = dict(config.get("mineru") or {})
    quality = (raw.get("quality") or "ultra").lower()
    preset = dict(QUALITY_PRESETS.get(quality, QUALITY_PRESETS["ultra"]))
    for k in ("backend", "method", "lang", "formula_enable", "table_enable"):
        if raw.get(k) is not None:
            preset[k] = raw[k]
    preset["quality"] = quality
    preset["cli_path"] = (raw.get("cli_path") or "").strip()
    preset["api_url"] = (raw.get("api_url") or "").strip()
    preset["force_ocr"] = bool(raw.get("force_ocr", True))
    preset["gpu_device"] = str(raw.get("gpu_device", "0"))
    preset["render_threads"] = int(raw.get("render_threads", 8))
    preset["timeout_seconds"] = int(raw.get("timeout_seconds", 7200))
    preset["startup_timeout"] = int(raw.get("startup_timeout", 600))
    preset["work_subdir"] = raw.get("work_subdir") or "mineru_cache"
    preset["client_side_output"] = raw.get(
        "client_side_output_generation", preset.get("client_side_output", True)
    )
    return preset


def _windows_mineru_search_paths() -> list:
    """
    Windows 下 pip 安装 MinerU 的常见位置（含目标机 Python 3.13 布局）。
    优先较新版本目录。
    """
    found = []
    seen = set()

    def add(p):
        p = os.path.normpath(p)
        if p not in seen and os.path.isfile(p):
            seen.add(p)
            found.append(p)

    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        py_root = os.path.join(local, "Programs", "Python")
        if os.path.isdir(py_root):
            vers = sorted(glob.glob(os.path.join(py_root, "Python3*")), reverse=True)
            for py_dir in vers:
                add(os.path.join(py_dir, "Scripts", "mineru.exe"))
    # 与当前进程同目录的 Python（开发模式 py legal_archive_gui.py）
    if sys.executable.lower().endswith((".exe",)):
        add(os.path.join(os.path.dirname(sys.executable), "Scripts", "mineru.exe"))
    # 目标部署机示例：用户 PC + Python 3.13（config 未填 cli_path 时的兜底）
    add(
        r"C:\Users\PC\AppData\Local\Programs\Python\Python313\Scripts\mineru.exe"
    )
    return found


def python_for_mineru_cli(cli_path: str = "") -> Optional[str]:
    """与 mineru.exe 同目录 Python（pip 安装环境）"""
    cli = resolve_mineru_cli(cli_path)
    if not cli:
        return None
    scripts = os.path.dirname(os.path.abspath(cli))
    py_root = os.path.dirname(scripts)
    for name in ("python.exe", "python3.exe"):
        cand = os.path.join(py_root, name)
        if os.path.isfile(cand):
            return cand
    return None


def _pipeline_install_hint(python_exe: Optional[str] = None) -> str:
    if python_exe and os.path.isfile(python_exe):
        py = f'& "{python_exe}"'
    else:
        py = "py"
    return (
        "MinerU 缺少本地解析依赖（torch + mineru[pipeline]）。\n"
        "请在 PowerShell 中执行（使用安装 MinerU 的同一 Python）：\n\n"
        f"  {py} -m pip install -U pip\n"
        f"  {py} -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124\n"
        f'  {py} -m pip install -U "mineru[pipeline]"\n\n'
        "完成后在程序中「详细设置 → 测试 MinerU」验证。\n"
        "或暂时在界面切换为「百度 OCR」。"
    )


def check_pipeline_dependencies(cli_path: str = "") -> Tuple[bool, str]:
    """
    检测 MinerU 所用 Python 是否已装 torch（pipeline / hybrid 均需要）。
    返回 (是否就绪, 说明或安装提示)
    """
    py = python_for_mineru_cli(cli_path)
    if not py:
        return False, "无法定位 MinerU 对应的 python.exe，请在设置中填写 mineru.exe 全路径"
    try:
        r = subprocess.run(
            [
                py,
                "-c",
                "import torch; print('cuda' if torch.cuda.is_available() else 'cpu')",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            if "No module named" in err or "torch" in err.lower():
                return False, _pipeline_install_hint(py)
            return False, err or "torch 检测失败"
        mode = (r.stdout or "").strip()
        if mode == "cuda":
            return True, f"PyTorch + CUDA 就绪 ({py})"
        return True, f"PyTorch 已安装（仅 CPU，建议安装 CUDA 版）({py})"
    except Exception as e:
        return False, str(e)


def _format_mineru_error(stderr: str, cli_path: str = "") -> str:
    text = stderr or ""
    if "requires local pipeline" in text or "mineru[pipeline]" in text:
        return _pipeline_install_hint(python_for_mineru_cli(cli_path))
    if "hybrid-auto-engine" in text and "torch" in text:
        return _pipeline_install_hint(python_for_mineru_cli(cli_path))
    return text[-2500:] if len(text) > 2500 else text


def resolve_mineru_cli(cli_path: str = "") -> Optional[str]:
    if cli_path and os.path.isfile(cli_path):
        return os.path.normpath(cli_path)
    for name in ("mineru", "mineru.exe"):
        found = shutil.which(name)
        if found:
            return os.path.normpath(found)
    for candidate in _windows_mineru_search_paths():
        return candidate
    return None


def check_mineru_available(config: dict = None) -> Tuple[bool, str]:
    cfg = get_mineru_settings(config or {})
    cli = resolve_mineru_cli(cfg.get("cli_path", ""))
    if not cli:
        return False, (
            "未找到 mineru 命令。请先安装：pip install -U \"mineru[all]\" "
            "并安装 CUDA 版 PyTorch，详见 MINERU_V2_SETUP.md"
        )
    try:
        r = subprocess.run(
            [cli, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        ver = (r.stdout or r.stderr or "").strip()
        if r.returncode != 0:
            return False, ver or f"mineru --version 退出码 {r.returncode}"
        dep_ok, dep_msg = check_pipeline_dependencies(cfg.get("cli_path", ""))
        if not dep_ok:
            return False, dep_msg
        return True, f"{ver or cli}；{dep_msg}"
    except Exception as e:
        return False, str(e)


def _mineru_work_dir(config: dict, pdf_path: str) -> str:
    try:
        from app_paths import get_outputs_dir
        root = get_outputs_dir()
    except ImportError:
        root = os.path.join(os.path.dirname(__file__), "outputs")
    mc = get_mineru_settings(config)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    safe = re.sub(r'[<>:"/\\|?*]', "_", base)[:80]
    d = os.path.join(root, mc["work_subdir"], safe)
    os.makedirs(d, exist_ok=True)
    return d


def _page_range_args(max_pages: int, total_pages: int) -> list:
    """MinerU -s/-e 为 0-based 闭区间端点"""
    if not total_pages or max_pages <= 0 or max_pages >= total_pages:
        return []
    end = max(0, max_pages - 1)
    return ["-s", "0", "-e", str(end)]


def _build_env(mcfg: dict) -> dict:
    env = os.environ.copy()
    gpu = mcfg.get("gpu_device", "0")
    if gpu not in ("", "-1"):
        env["CUDA_VISIBLE_DEVICES"] = gpu
    threads = mcfg.get("render_threads", 8)
    if threads > 0:
        env["MINERU_PDF_RENDER_THREADS"] = str(threads)
    env.setdefault("MINERU_FORMULA_ENABLE", "true" if mcfg.get("formula_enable") else "false")
    env.setdefault("MINERU_TABLE_ENABLE", "true" if mcfg.get("table_enable") else "false")
    env["MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS"] = str(mcfg.get("startup_timeout", 600))
    env["MINERU_TASK_RESULT_TIMEOUT_SECONDS"] = str(mcfg.get("timeout_seconds", 7200))
    return env


def _build_cmd(cli: str, pdf_path: str, out_dir: str, mcfg: dict, page_args: list) -> list:
    cmd = [
        cli,
        "-p",
        os.path.abspath(pdf_path),
        "-o",
        os.path.abspath(out_dir),
        "-b",
        mcfg["backend"],
        "-m",
        mcfg["method"],
        "-l",
        mcfg["lang"],
        "-f",
        "true" if mcfg.get("formula_enable", True) else "false",
        "-t",
        "true" if mcfg.get("table_enable", True) else "false",
    ]
    if mcfg.get("client_side_output"):
        cmd.extend(["--client-side-output-generation", "true"])
    api = mcfg.get("api_url") or ""
    if api:
        cmd.extend(["--api-url", api.rstrip("/")])
    cmd.extend(page_args)
    return cmd


def find_mineru_markdown(output_dir: str, pdf_path: str) -> Optional[str]:
    """在 MinerU 输出目录中定位主 Markdown 文件"""
    if not output_dir or not os.path.isdir(output_dir):
        return None
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    md_files = []
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.lower().endswith(".md"):
                md_files.append(os.path.join(root, f))
    if not md_files:
        return None

    def score(path: str) -> tuple:
        name = os.path.basename(path).lower()
        rel = path.lower()
        pri = 0
        if base.lower() in rel:
            pri += 10
        if name in (f"{base.lower()}.md", "content.md", "full.md"):
            pri += 8
        if "auto" in rel or "hybrid" in rel or "pipeline" in rel:
            pri += 2
        return (pri, os.path.getmtime(path))

    md_files.sort(key=score, reverse=True)
    return md_files[0]


def markdown_to_plain_text(md: str) -> str:
    """轻度清理 Markdown，保留段落结构供 LLM 使用"""
    if not md:
        return ""
    text = md
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_mineru_output(output_dir: str, pdf_path: str, keep_markdown: bool = True) -> str:
    md_path = find_mineru_markdown(output_dir, pdf_path)
    if not md_path:
        return ""
    with open(md_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    if keep_markdown:
        return content.strip()
    return markdown_to_plain_text(content)


def run_mineru_parse(
    pdf_path: str,
    config: dict,
    log: LogFn = print,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    调用 MinerU CLI 解析 PDF，返回 (文本, 错误信息, 输出目录)。
    """
    from archive_ocr import extract_pdf_text_direct, get_pdf_page_count

    mcfg = get_mineru_settings(config)
    cli = resolve_mineru_cli(mcfg.get("cli_path", ""))
    if not cli:
        return None, "未安装 MinerU CLI，请执行 pip install -U \"mineru[all]\"", None

    ok, ver = check_mineru_available(config)
    if ok:
        log(f"  [OK] MinerU: {ver}")
    else:
        return None, ver, None

    backend = mcfg.get("backend", "pipeline")
    if backend in ("pipeline", "hybrid-auto-engine", "hybrid-http-client"):
        dep_ok, dep_msg = check_pipeline_dependencies(mcfg.get("cli_path", ""))
        if not dep_ok:
            return None, dep_msg, None
        if "CUDA 就绪" in dep_msg:
            log(f"  [OK] {dep_msg}")

    if not mcfg.get("force_ocr", True):
        direct = extract_pdf_text_direct(pdf_path)
        if direct and len(direct.strip()) > 800:
            log(f"  [OK] PDF 文字层 {len(direct)} 字符（跳过 MinerU）")
            return direct, None, None

    total = get_pdf_page_count(pdf_path)
    max_pages = config.get("local_ocr", {}).get("max_pages", 0)
    page_args = _page_range_args(max_pages, total)
    if total and page_args:
        log(f"  [INFO] MinerU 解析第 1–{max_pages} 页 / 共 {total} 页")
    elif total:
        log(f"  [INFO] MinerU 解析全部 {total} 页")

    work_parent = _mineru_work_dir(config, pdf_path)
    run_dir = tempfile.mkdtemp(prefix="run_", dir=work_parent)
    out_dir = os.path.join(run_dir, "out")
    os.makedirs(out_dir, exist_ok=True)

    backends = [mcfg["backend"]]
    if mcfg["backend"] == "hybrid-auto-engine" and "pipeline" not in backends:
        backends.append("pipeline")

    env = _build_env(mcfg)
    timeout = mcfg.get("timeout_seconds", 7200)
    last_err = ""
    proc = None
    for bi, backend in enumerate(backends):
        run_cfg = {**mcfg, "backend": backend}
        cmd = _build_cmd(cli, pdf_path, out_dir, run_cfg, page_args)
        if bi == 0:
            log(
                f"  [INFO] MinerU 精细度: {run_cfg['quality']} "
                f"({backend} / {run_cfg['method']})"
            )
        else:
            log(f"  [WARN] 改用后端 {backend} 重试…")
        log(f"  [CMD] {' '.join(cmd[:8])} ...")
        try:
            proc = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                cwd=work_parent,
            )
        except subprocess.TimeoutExpired:
            return None, f"MinerU 超时（>{timeout}s），可在 config 中增大 mineru.timeout_seconds", None
        except Exception as e:
            return None, str(e), None
        if proc.returncode == 0:
            break
        raw = proc.stderr or proc.stdout or ""
        last_err = _format_mineru_error(raw, mcfg.get("cli_path", ""))
        if bi < len(backends) - 1 and (
            "requires local pipeline" in raw or "hybrid-auto-engine" in raw
        ):
            continue
        return None, f"MinerU 退出码 {proc.returncode}: {last_err}", None

    text = read_mineru_output(out_dir, pdf_path, keep_markdown=True)
    meta_dir = out_dir
    if not text or len(text.strip()) < 80:
        # 部分版本输出在 work_parent 子目录
        text = read_mineru_output(work_parent, pdf_path, keep_markdown=True)
        meta_dir = work_parent
    if len(text.strip()) < 80:
        return None, "MinerU 已完成但未找到有效 .md 输出，请检查 mineru 安装与 GPU 驱动", None
    log(f"  [OK] MinerU 输出 {len(text)} 字符")
    return text, None, meta_dir


def extract_pdf_with_mineru(
    pdf_path: str,
    config: dict,
    log: LogFn = print,
) -> Tuple[Optional[str], Optional[str]]:
    """V2 主入口：MinerU 解析，可选回退百度 OCR"""
    text, err, _ = run_mineru_parse(pdf_path, config, log=log)
    if text and len(text.strip()) >= 100:
        return text, None

    if config.get("mineru", {}).get("fallback_baidu"):
        log("  [WARN] MinerU 失败，回退百度 OCR…")
        from archive_ocr import extract_pdf_text_sampled

        return extract_pdf_text_sampled(pdf_path, config, log=log)
    return text, err
