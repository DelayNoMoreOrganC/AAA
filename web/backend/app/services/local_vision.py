"""Workstation-owned Ollama engine. No case files or credentials in diagnostics."""
from __future__ import annotations

import base64
import hashlib
import platform
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import threading
import time

import psutil
import requests
from ..config import DATA_DIR

from ..core.v4_bridge import init_v4_path
init_v4_path()
from local_vision_catalog import PRESETS, DEFAULT_MODEL, DEFAULT_TIER, ALLOWED_MODELS, preset
MODEL = DEFAULT_MODEL
BASE_URL = "http://127.0.0.1:11435"
LOCK = threading.Lock()


class LocalEngineUnavailable(RuntimeError):
    pass


def _directory():
    directory = DATA_DIR / "local-vision"
    directory.mkdir(parents=True, exist_ok=True)
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    from workstation_security import protect_directory
    protect_directory(directory)
    return directory


def _read(name):
    try:
        value = json.loads((DATA_DIR / "local-vision" / name).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(name, value):
    path = _directory() / name
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def executable():
    candidates = [shutil.which("ollama"),
                  os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
                  os.path.expandvars(r"%PROGRAMFILES%\Ollama\ollama.exe")]
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), "")


def _owned(record, command):
    try:
        process = psutil.Process(record["pid"])
        return (process.is_running() and abs(process.create_time() - record["created"]) < .01
                and os.path.normcase(process.exe()) == os.path.normcase(record["executable"])
                and process.cmdline()[1:] == command)
    except (psutil.Error, KeyError, TypeError):
        return False


def require_owned():
    record = _read("engine.json")
    if record.get("cloud_disabled") is not True or not _owned(record, ["serve"]):
        raise LocalEngineUnavailable("本地引擎尚未准备，请由管理员准备引擎")
    try:
        listeners = [c for c in psutil.Process(record["pid"]).net_connections(kind="tcp")
                     if c.status == psutil.CONN_LISTEN and c.laddr.port == 11435]
        if not listeners or any(c.laddr.ip != "127.0.0.1" for c in listeners):
            raise LocalEngineUnavailable("本地引擎端口归属未通过检查")
    except psutil.Error:
        raise LocalEngineUnavailable("无法验证本地引擎进程") from None


def _api(path, body=None):
    require_owned()
    with requests.Session() as session:
        session.trust_env = False
        with session.request("GET" if body is None else "POST", BASE_URL + path, json=body,
                             timeout=(2, 5), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise LocalEngineUnavailable("本地模型未就绪，请准备模型后重试")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2_000_000:
                    raise LocalEngineUnavailable("本地引擎响应无效")
                chunks.append(chunk)
        value = json.loads(b"".join(chunks))
        if not isinstance(value, dict):
            raise LocalEngineUnavailable("本地引擎响应无效")
        return value


def model_identity(model=MODEL):
    if model not in ALLOWED_MODELS:
        raise LocalEngineUnavailable("本地视觉模型未获支持")
    version = _api("/api/version").get("version", "")
    parsed = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[.-].*)?$", version)
    if not parsed or tuple(map(int, parsed.groups())) < (0, 12, 7):
        raise LocalEngineUnavailable("请更新 Ollama 至 0.12.7 或更新版本")
    tags = _api("/api/tags")
    row = next((m for m in tags.get("models", []) if m.get("name") == model), {})
    digest = row.get("digest", "")
    if not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", digest):
        raise LocalEngineUnavailable("尚未下载所选视觉模型")
    details = _api("/api/show", {"model": model})
    if (row.get("remote_model") or row.get("remote_host") or details.get("remote_model") or details.get("remote_host")
            or "vision" not in details.get("capabilities", [])
            or details.get("details", {}).get("quantization_level") != "Q4_K_M"):
        raise LocalEngineUnavailable("所选模型必须是本地 Q4_K_M 视觉模型")
    return digest


def guard(expected_digest=None, model=MODEL):
    try:
        digest = model_identity(model)
        if expected_digest is not None and digest != expected_digest:
            raise LocalEngineUnavailable("本地模型版本已变化，请使用创建任务时的模型")
        return digest
    except LocalEngineUnavailable:
        raise
    except Exception:
        raise LocalEngineUnavailable("本地视觉引擎无法连接，未转向云端") from None


def hardware():
    memory = psutil.virtual_memory()
    gpus = []
    command = shutil.which("nvidia-smi")
    if command:
        try:
            result = subprocess.run([command, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                                    capture_output=True, text=True, timeout=4,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            for line in result.stdout.splitlines():
                name, total, free = line.rsplit(",", 2)
                gpus.append({"name": name.strip()[:100], "total_gb": round(float(total)/1024, 1),
                             "free_gb": round(float(free)/1024, 1)})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return {"ram_gb": round(memory.total/1024**3, 1), "available_ram_gb": round(memory.available/1024**3, 1),
            "gpus": gpus, "gpu_verified": bool(gpus)}


def recommendation(info, tier=DEFAULT_TIER):
    spec = preset(tier)
    vram = max((g["total_gb"] for g in info["gpus"]), default=0)
    if tier == "unified128":
        if info["ram_gb"] < 125:
            return "below_tier", "未达到所选档位的 128 GB 统一内存要求"
        return "needs_verification", "需核实统一内存架构、GPU 可用内存和带宽；请先试跑"
    if info["ram_gb"] >= spec["ram_gb"] * .97 and vram >= spec["vram_gb"] * .97:
        return "meets_tier", "达到所选档位容量要求，仍需试跑验证"
    return "below_tier", "未达到所选档位容量要求；配置标准不会随本机调整"


def _benchmark_file(model):
    return "benchmark-" + hashlib.sha256(model.encode()).hexdigest()[:16] + ".json"


def environment(tier=DEFAULT_TIER):
    spec = preset(tier)
    model = spec["model"]
    info = hardware()
    level, advice = recommendation(info, tier)
    issues, digest = [], None
    downloading = _owned(_read("download.json"), ["pull", _read("download.json").get("model", "")])
    if not executable():
        issues.append("工作站未安装 Ollama，请由管理员安装后准备引擎")
    try:
        digest = guard(model=model)
    except LocalEngineUnavailable as exc:
        issues.append(str(exc))
    report = _read(_benchmark_file(model))
    current_report = report if digest and report.get("model_digest") == digest and report.get("hardware") == {"ram_gb": info["ram_gb"], "gpus": [{"name": g["name"], "total_gb": g["total_gb"]} for g in info["gpus"]]} else None
    return {"model": model, "tier": tier, "preset": spec, "presets": PRESETS, "hardware": info, "recommendation": level, "advice": advice,
            "engine_ready": bool(digest), "ready": bool(digest and current_report and current_report.get("passed")),
            "issues": issues, "download_running": downloading, "benchmark": current_report,
            "benchmark_required": not bool(current_report and current_report.get("passed")),
            "installed": bool(executable()), "scope": "workstation", "offline_acceptance": "not_verified"}


def prepare(*, download=False, tier=DEFAULT_TIER):
    spec = preset(tier)
    model = spec["model"]
    if not LOCK.acquire(blocking=False):
        raise LocalEngineUnavailable("本地引擎正在准备或试跑")
    try:
        binary = executable()
        if not binary:
            raise LocalEngineUnavailable("请先在工作站安装 Ollama，再点击准备引擎")
        env = dict(os.environ)
        env.update(OLLAMA_HOST="127.0.0.1:11435", OLLAMA_NO_CLOUD="1", OLLAMA_NUM_PARALLEL="1",
                   OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_CONTEXT_LENGTH="16384",
                   OLLAMA_MODELS=str(_directory() / "models"))
        if not _owned(_read("engine.json"), ["serve"]):
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", 11435)) == 0:
                    raise LocalEngineUnavailable("专用端口已被其他程序占用，请管理员处理")
            process = subprocess.Popen([binary, "serve"], env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            _save("engine.json", {"pid": process.pid, "created": psutil.Process(process.pid).create_time(),
                                  "executable": binary, "cloud_disabled": True})
            for _ in range(30):
                try:
                    _api("/api/version")
                    break
                except Exception:
                    time.sleep(.1)
        require_owned()
        if download and not _owned(_read("download.json"), ["pull", _read("download.json").get("model", "")]):
            # Reuse an installed model without upgrading its digest under active tasks.
            try:
                guard(model=model)
                return {"message": "本地模型已准备，请进行试跑"}
            except LocalEngineUnavailable:
                pass
            if shutil.disk_usage(_directory()).free < (spec["download_gb"] + 8) * 1024**3:
                raise LocalEngineUnavailable("模型磁盘剩余空间不足（需模型大小另加 8 GB 余量）")
            process = subprocess.Popen([binary, "pull", model], env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            _save("download.json", {"pid": process.pid, "created": psutil.Process(process.pid).create_time(), "executable": binary, "model": model})
            return {"message": f"模型下载已开始（约 {spec['download_gb']} GB），完成后请检测并试跑"}
        return {"message": "本地引擎已启动；云端功能已禁用"}
    finally:
        LOCK.release()


def benchmark(tier=DEFAULT_TIER):
    model = preset(tier)["model"]
    if not LOCK.acquire(blocking=False):
        raise LocalEngineUnavailable("本地引擎正在准备或试跑")
    try:
        digest = guard(model=model)
        _save(_benchmark_file(model), {"passed": False, "model_digest": digest})
        import fitz
        from ollama_vision_client import OllamaVisionClient
        # The target value appears only in this generated image, never in the prompt.
        import secrets
        marker = secrets.token_hex(4).upper()
        with fitz.open() as doc:
            page = doc.new_page(width=640, height=300)
            page.insert_text((40, 90), "SYNTHETIC VISION CHECK", fontsize=24)
            page.insert_text((40, 155), "REFERENCE: " + marker, fontsize=28)
            image = base64.b64encode(page.get_pixmap().tobytes("png")).decode()
        client = OllamaVisionClient(lambda: guard(digest, model), model=model)
        started = time.perf_counter()
        result = client.complete([{"role": "user", "content": [{"type": "text", "text": '读取图中的 REFERENCE，只返回 JSON {"reference":"图中编号"}。'},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image}}]}])
        elapsed = round(time.perf_counter() - started, 2)
        info = hardware()
        running = _api("/api/ps").get("models", [])
        resident = next((m for m in running if m.get("name") == model), {})
        report = {"passed": result.get("reference") == marker, "seconds": elapsed, "model_digest": digest,
                  "checked_at": datetime.now(timezone.utc).isoformat(), "model_requests": client.metrics["model_requests"],
                  "hardware": {"ram_gb": info["ram_gb"], "gpus": [{"name": g["name"], "total_gb": g["total_gb"]} for g in info["gpus"]]},
                  "loaded_gb": round(resident.get("size", 0)/1024**3, 2), "loaded_vram_gb": round(resident.get("size_vram", 0)/1024**3, 2),
                  "scope": "synthetic_single_image_json_only", "offline_acceptance": "not_verified"}
        _save(_benchmark_file(model), report)
        return report
    except LocalEngineUnavailable:
        raise
    except Exception:
        raise LocalEngineUnavailable("本地视觉试跑未通过，未发送案件资料或切换云端") from None
    finally:
        LOCK.release()
