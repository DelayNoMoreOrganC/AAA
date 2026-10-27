"""Start/reopen the locally installed workstation; never download code at runtime."""
from __future__ import annotations
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'workstation-data'
PORT = 8765
MODEL_TIMEOUT = 60


@contextmanager
def startup_lock(path):
    """OS-owned lock: survives a stale file, releases automatically on process exit."""
    with Path(path).open('a+b') as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        acquired = False
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
        try:
            yield acquired
        finally:
            if acquired:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def port_in_use(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def stop_owned_process(process):
    """Only stop the child created by this launcher, never an existing listener."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def model_ready(opener):
    try:
        with opener.open('http://127.0.0.1:11434/v1/models', timeout=2) as response:
            data = json.load(response)
            return response.status == 200 and any(
                x.get('id') == 'gd-qwen3-4b' for x in data.get('data', []))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def wait_for_model(opener, process=None):
    deadline = time.monotonic() + MODEL_TIMEOUT
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return False
        if model_ready(opener):
            return True
        time.sleep(.5)
    return False


def start_model():
    executable = ROOT / 'runtime/llama/llama-server.exe'
    if not executable.is_file():
        candidates = list((ROOT / 'runtime/llama').rglob('llama-server.exe'))
        executable = candidates[0] if candidates else executable
    model = ROOT / 'runtime/models/Qwen3-4B-Q4_K_M.gguf'
    if not executable.is_file() or not model.is_file():
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if model_ready(opener):
        return True
    # A previous launcher may have exited while its child was loading. Do not
    # spawn a second model into an occupied port, even when /models returns 503.
    if port_in_use(11434):
        print('正在等待已运行的本地模型就绪……', flush=True)
        return wait_for_model(opener)
    print('正在加载本地模型，请稍候……', flush=True)
    with (DATA / 'model.log').open('ab') as log:
        process = subprocess.Popen([str(executable), '-m', str(model), '--alias', 'gd-qwen3-4b',
            '--host', '127.0.0.1', '--port', '11434', '-c', '8192', '-t', '6', '-np', '1', '-ngl', '0', '--cache-ram', '0',
            '--jinja', '--chat-template-kwargs', '{"enable_thinking":false}', '--no-webui', '--no-warmup', '--log-disable', '--offline'],
            cwd=str(executable.parent), stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (DATA / 'model.pid').write_text(str(process.pid), encoding='ascii')
    ready = wait_for_model(opener, process)
    if not ready:
        stop_owned_process(process)
    return ready


def request_json(path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{PORT}{path}', timeout=2) as response:
        return json.load(response)


def main():
    DATA.mkdir(exist_ok=True)
    with startup_lock(DATA / 'startup.lock') as acquired:
        if not acquired:
            print('工作站正在启动，请等待已打开的启动窗口；没有重复启动模型或后台。', flush=True)
            return 0
        return start_workstation()


def start_workstation():
    from workstation_security import protect_directory
    protect_directory(DATA)
    try:
        model_is_ready = start_model()
    except (OSError, subprocess.SubprocessError, ValueError):
        model_is_ready = False
    try:
        health = request_json('/api/health')
        if health.get('application') != 'gd-workstation':
            print('端口已被其他服务使用，工作站未启动。')
            return 1
    except Exception:
        health = None
    if not health:
        if port_in_use(PORT):
            print('工作站端口已被占用但健康检查未通过，未重复启动后台。请查看 workstation-data/service.log。')
            return 1
        env = dict(os.environ, V5_DATA_DIR=str(DATA), V5_HOST='127.0.0.1', V5_PORT=str(PORT),
                   V5_PREVIEW_ONLY='true', V5_ALLOW_EXTERNAL_AI='false', V5_REGISTRATION_ENABLED='false',
                   V5_LOCAL_LLM_BASE_URL='http://127.0.0.1:11434/v1', V5_LOCAL_LLM_MODEL='gd-qwen3-4b',
                   TEMP=str(DATA / 'temp'), TMP=str(DATA / 'temp'), PYTHONUTF8='1')
        (DATA / 'temp').mkdir(exist_ok=True)
        with (DATA / 'service.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, str(ROOT / 'web/backend/run.py')],
                cwd=str(ROOT / 'web/backend'), env=env, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (DATA / 'service.pid').write_text(str(process.pid), encoding='ascii')
        for _ in range(60):
            try:
                health = request_json('/api/health')
                if health.get('application') != 'gd-workstation':
                    health = None
                break
            except Exception:
                if process.poll() is not None:
                    break
                time.sleep(.5)
    if not health:
        print('工作站启动失败，请查看 workstation-data/service.log。')
        return 1
    if os.name == 'nt':
        # A Windows venv executable may be a launcher, with a separate worker.
        try:
            listening_pid = subprocess.check_output(['powershell', '-NoProfile', '-Command',
                f'(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort {PORT} -State Listen | Select-Object -First 1).OwningProcess'],
                text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
            if listening_pid.isdigit():
                (DATA / 'service.pid').write_text(listening_pid, encoding='ascii')
        except (OSError, subprocess.CalledProcessError):
            pass
    url = f'http://127.0.0.1:{PORT}/'
    try:
        from workstation_https import start as start_https
        https_ready = start_https()
    except Exception:
        https_ready = False
    if not https_ready:
        print('本机页面可用，本地 HTTPS 健康检查未通过；局域网尚不可用，请查看 workstation-data/https.log。')
    if request_json('/api/setup/status')['required']:
        token = (DATA / 'setup.token').read_text(encoding='utf-8').strip()
        url += 'setup#token=' + token
    if '--no-browser' not in sys.argv:
        webbrowser.open(url)
    if not model_is_ready:
        print(f'本机页面已启动：http://127.0.0.1:{PORT}/；工作站模型尚未就绪，暂不能开始分析。请查看 workstation-data/model.log。')
        return 1
    print(f'本机页面和模型已就绪：http://127.0.0.1:{PORT}/')
    if https_ready:
        print('本地 CA 验证的 HTTPS 健康检查通过；第二台电脑访问仍须完成防火墙和客户端信任验收。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
