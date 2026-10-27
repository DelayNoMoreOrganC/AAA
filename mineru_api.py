#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU 云端精准解析 API（V2.0.3）
文档：https://mineru.net/apiManage/docs
流程：申请上传 URL → PUT 文件 → 轮询 batch 结果 → 解压 full.md
"""

from __future__ import annotations

import io
import os
import time
import zipfile
from typing import Callable, List, Optional, Tuple

import requests

LogFn = Callable[[str], None]

API_BASE = "https://mineru.net/api/v4"
DEFAULT_TOKEN_FILE = os.path.join(
    os.path.expanduser("~"), "Desktop", "minerU API TOKEN.txt"
)

POLL_INTERVAL = 3
POLL_TIMEOUT = 600


def normalize_mineru_api_token(raw: str) -> str:
    """去掉 Bearer 前缀、引号与空白。"""
    t = (raw or "").strip().strip('"').strip("'")
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return t


def resolve_mineru_api_token(config: dict = None) -> str:
    """优先 config.mineru.api_token，其次环境变量、桌面 token 文件"""
    cfg = config or {}
    token = normalize_mineru_api_token((cfg.get("mineru") or {}).get("api_token", ""))
    if token:
        return token
    token = normalize_mineru_api_token(os.environ.get("MINERU_API_TOKEN", ""))
    if token:
        return token
    for path in (
        DEFAULT_TOKEN_FILE,
        r"C:\Users\Administrator\Desktop\minerU API TOKEN.txt",
    ):
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    t = normalize_mineru_api_token(f.read())
                if t:
                    return t
            except OSError:
                pass
    return ""


def _headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def _page_ranges_arg(max_pages: int, total_pages: int) -> Optional[str]:
    if not max_pages or max_pages <= 0:
        return None
    if total_pages and max_pages >= total_pages:
        return None
    return f"1-{max_pages}"


def check_mineru_api_available(config: dict = None) -> Tuple[bool, str]:
    token = resolve_mineru_api_token(config)
    if not token:
        return False, "未配置 MinerU API Token（详细设置或桌面 token 文件）"
    try:
        r = requests.post(
            f"{API_BASE}/file-urls/batch",
            headers=_headers(token),
            json={
                "files": [{"name": "_config_probe.pdf", "data_id": "probe"}],
                "model_version": (config or {}).get("mineru", {}).get(
                    "api_model_version", "vlm"
                ),
            },
            timeout=25,
        )
        if r.status_code == 401:
            return False, "Token 无效或已过期，请重新填写并保存"
        data = r.json()
        if r.status_code == 200 and data.get("code") == 0:
            return True, "MinerU API 已连通"
        msg = data.get("msg") or data.get("message") or r.text[:120]
        return False, f"MinerU API 校验失败: {msg}"
    except requests.RequestException as e:
        return False, f"无法连接 MinerU API: {e}"


def _request_batch_upload(
    token: str,
    pdf_paths: List[str],
    model_version: str = "vlm",
    page_ranges: Optional[str] = None,
    is_ocr: bool = True,
) -> Tuple[str, List[str]]:
    files = []
    for p in pdf_paths:
        item = {"name": os.path.basename(p), "data_id": os.path.basename(p)}
        if page_ranges:
            item["page_ranges"] = page_ranges
        if is_ocr:
            item["is_ocr"] = True
        files.append(item)

    body = {
        "files": files,
        "model_version": model_version,
        "enable_formula": True,
        "enable_table": True,
        "language": "ch",
    }
    if is_ocr:
        body["enable_formula"] = True

    r = requests.post(
        f"{API_BASE}/file-urls/batch",
        headers=_headers(token),
        json=body,
        timeout=60,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"MinerU API 申请上传失败: {data.get('msg', data)}")
    batch_id = data["data"]["batch_id"]
    urls = data["data"]["file_urls"]
    if len(urls) != len(pdf_paths):
        raise RuntimeError("MinerU API 返回的上传链接数量与文件不一致")
    return batch_id, urls


def _put_files(pdf_paths: List[str], upload_urls: List[str], log: LogFn = print):
    for path, url in zip(pdf_paths, upload_urls):
        log(f"  [INFO] MinerU API 上传: {os.path.basename(path)}")
        with open(path, "rb") as f:
            r = requests.put(url, data=f, timeout=300)
        if r.status_code not in (200, 201):
            raise RuntimeError(
                f"MinerU API 文件上传失败 ({os.path.basename(path)}): HTTP {r.status_code}"
            )


def _poll_batch_results(
    token: str,
    batch_id: str,
    file_names: List[str],
    log: LogFn = print,
) -> dict:
    """返回 {file_name: full_zip_url}"""
    deadline = time.time() + POLL_TIMEOUT
    name_set = set(file_names)
    done_map = {}

    while time.time() < deadline:
        r = requests.get(
            f"{API_BASE}/extract-results/batch/{batch_id}",
            headers=_headers(token),
            timeout=60,
        )
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"MinerU API 查询失败: {data.get('msg', data)}")

        results = data.get("data", {}).get("extract_result") or []
        if isinstance(results, dict):
            results = [results]

        pending = 0
        for item in results:
            fname = item.get("file_name") or ""
            state = (item.get("state") or "").lower()
            if fname not in name_set and len(name_set) == 1 and len(results) == 1:
                fname = list(name_set)[0]

            if state == "done":
                url = item.get("full_zip_url") or ""
                if url:
                    done_map[fname] = url
                    log(f"  [OK] MinerU API 解析完成: {fname}")
            elif state == "failed":
                err = item.get("err_msg") or "解析失败"
                raise RuntimeError(f"MinerU API 解析失败 ({fname}): {err}")
            elif state in (
                "pending",
                "running",
                "converting",
                "waiting-file",
                "uploading",
            ):
                pending += 1
                prog = item.get("extract_progress") or {}
                if prog.get("total_pages"):
                    log(
                        f"  [INFO] {fname}: {state} "
                        f"{prog.get('extracted_pages', 0)}/{prog.get('total_pages')} 页"
                    )

        if len(done_map) >= len(name_set):
            return done_map

        if pending == 0 and results and not done_map:
            time.sleep(POLL_INTERVAL)
            continue

        time.sleep(POLL_INTERVAL)

    raise RuntimeError(f"MinerU API 轮询超时（>{POLL_TIMEOUT}s），batch_id={batch_id}")


def _download_zip_bytes(
    zip_url: str,
    log: LogFn = print,
    retries: int = 8,
    timeout: int = 300,
) -> bytes:
    """断点续传下载结果 zip（修复大文件慢速链路 IncompleteRead）。

    连接中断时用 HTTP Range 从断点继续，而非重头下载；
    完成后校验长度与 zip 完整性。
    """
    buf = bytearray()
    expected: Optional[int] = None
    last_err = None

    for attempt in range(1, retries + 1):
        headers = {}
        if buf:
            headers["Range"] = f"bytes={len(buf)}-"
        try:
            with requests.get(
                zip_url, stream=True, timeout=timeout, headers=headers
            ) as r:
                # 已有数据却返回 200 → 服务器不支持 Range，重置从头下
                if buf and r.status_code == 200:
                    buf = bytearray()
                r.raise_for_status()
                if expected is None:
                    cr = r.headers.get("Content-Range")  # bytes start-end/total
                    cl = r.headers.get("Content-Length")
                    if cr and "/" in cr and cr.rsplit("/", 1)[-1].isdigit():
                        expected = int(cr.rsplit("/", 1)[-1])
                    elif cl and cl.isdigit() and not buf:
                        expected = int(cl)
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        buf.extend(chunk)
        except Exception as e:  # noqa: BLE001 - 网络异常 → 续传重试
            last_err = e
            log(
                f"  [WARN] 结果下载中断（第 {attempt}/{retries} 次，"
                f"已收 {len(buf):,}"
                + (f"/{expected:,}" if expected else "")
                + f" 字节）: {e}"
            )
            if attempt < retries:
                time.sleep(2)
            continue

        # 收齐校验
        if expected is None or len(buf) >= expected:
            data = bytes(buf)
            if not data:
                last_err = "下载内容为空"
            else:
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as zf:
                        if zf.testzip() is not None:
                            raise IOError("zip 校验失败（存在损坏文件）")
                    if attempt > 1:
                        log(f"  [OK] 结果下载完成（续传 {attempt} 次，{len(data):,} 字节）")
                    return data
                except Exception as e:  # zip 损坏 → 重置重下
                    last_err = e
                    log(f"  [WARN] 结果 zip 校验失败，将重下: {e}")
                    buf = bytearray()
                    expected = None
        else:
            log(
                f"  [INFO] 续传中：已收 {len(buf):,}/{expected:,} 字节"
            )
        if attempt < retries:
            time.sleep(1)

    raise RuntimeError(f"MinerU API 结果下载失败: {last_err}")


def _text_from_zip_bytes(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = zf.namelist()
        for prefer in ("full.md", "content.md"):
            for n in names:
                if n.endswith(prefer) or n.lower().endswith("/" + prefer):
                    return zf.read(n).decode("utf-8", errors="replace").strip()
        md_files = [n for n in names if n.lower().endswith(".md")]
        if md_files:
            md_files.sort(key=lambda x: (0 if "full" in x.lower() else 1, x))
            return zf.read(md_files[0]).decode("utf-8", errors="replace").strip()
    return ""


def _save_zip_bytes_to_temp(content: bytes, log: LogFn = print) -> Optional[str]:
    """将已下载的结果 zip 字节解压到临时目录（不再二次下载）。"""
    import tempfile

    tmp = tempfile.mkdtemp(prefix="mineru_api_")
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        zf.extractall(tmp)
    log(f"  [OK] MinerU API 结果已解压: {tmp}")
    return tmp


def extract_pdf_with_mineru_api(
    pdf_path: str,
    config: dict,
    log: LogFn = print,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """单 PDF 云端解析，返回 (markdown文本, 错误, 解压目录)"""
    token = resolve_mineru_api_token(config)
    if not token:
        return None, "未配置 MinerU API Token", None

    from archive_ocr import get_pdf_page_count

    mcfg = config.get("mineru") or {}
    model = mcfg.get("api_model_version") or mcfg.get("model_version") or "vlm"
    max_pages = config.get("local_ocr", {}).get("max_pages", 0)
    total = get_pdf_page_count(pdf_path)
    page_ranges = _page_ranges_arg(max_pages, total)

    log(f"  [INFO] MinerU API 云端解析: {os.path.basename(pdf_path)}")
    if page_ranges:
        log(f"  [INFO] 页码范围: {page_ranges} / 共 {total} 页")

    try:
        batch_id, urls = _request_batch_upload(
            token, [pdf_path], model_version=model, page_ranges=page_ranges
        )
        log(f"  [INFO] batch_id: {batch_id}")
        _put_files([pdf_path], urls, log=log)
        log("  [INFO] 等待 MinerU API 解析…")
        done = _poll_batch_results(
            token, batch_id, [os.path.basename(pdf_path)], log=log
        )
        zip_url = done.get(os.path.basename(pdf_path)) or next(iter(done.values()), "")
        if not zip_url:
            return None, "MinerU API 未返回结果下载链接", None
        # 仅下载一次（流式 + 重试 + 完整性校验），复用字节解析 md 与解压
        zip_bytes = _download_zip_bytes(zip_url, log=log)
        text = _text_from_zip_bytes(zip_bytes)
        if not text or len(text.strip()) < 80:
            return None, "MinerU API 结果为空或过短", None
        output_dir = _save_zip_bytes_to_temp(zip_bytes, log=log)
        log(f"  [OK] MinerU API 输出 {len(text)} 字符")
        return text, None, output_dir
    except Exception as e:
        return None, str(e), None
