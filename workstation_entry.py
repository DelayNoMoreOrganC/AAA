"""Single entry for the current workstation. Never stops or replaces a server."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
DATA = ROOT / '.runtime-tmp/full-experience'
URL = 'http://127.0.0.1:8766'


def health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(URL + '/api/health', timeout=4) as response:
            value = json.load(response)
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('application') != 'gd-workstation' or value.get('status') != 'ok':
        raise RuntimeError('8766 端口不是有效的卷小助工作站，未启动新后台。')
    saved = DATA / 'service.pid'
    if saved.exists() and saved.read_text(encoding='ascii').strip() != str(value.get('pid')):
        raise RuntimeError('后台进程与当前数据目录记录不一致，未启动或替换后台。')
    return value


def port_in_use():
    try:
        with socket.create_connection(('127.0.0.1', 8766), timeout=1):
            return True
    except OSError:
        return False


def report(value):
    from recognition_identity import recognition_identity
    current = recognition_identity()['recognition_signature']
    same = value.get('recognition_signature') == current
    print('AAA 卷小助：' + URL + '/cases')
    print('后台正在运行，重复打开不会重复启动。')
    if not same:
        print('当前后台尚未加载磁盘上的最新修复。此入口只打开页面，不自动重启或覆盖案件。')
    return same


def main(argv=None):
    parser = argparse.ArgumentParser(description='打开当前卷小助工作站；不会自动重启服务')
    parser.add_argument('--check', action='store_true', help='只读检查，不启动进程、不打开浏览器')
    args = parser.parse_args(argv)
    if not (DATA / 'archive.db').is_file():
        raise RuntimeError('未找到当前工作站数据。请使用完整的已配置项目目录；不会另建空数据库。')
    if args.check:
        value = health()
        if value is None:
            print('当前工作站未运行；检查没有启动任何进程。')
            return 1
        report(value)
        return 0
    from workstation_launcher import startup_lock
    with startup_lock(DATA / 'entry.lock') as acquired:
        if not acquired:
            print('工作站正在启动，请稍候；没有重复启动。')
            return 0
        value = health()
        if value is None:
            if port_in_use():
                raise RuntimeError('8766 端口已有服务但未通过检查，未重复启动。')
            # Reuse the established configuration and existing database. No new
            # port, model, cloud permission, credentials or data migration here.
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/start_acceptance.py')],
                cwd=ROOT, timeout=90, capture_output=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode:
                raise RuntimeError('工作站未能启动，请检查 .runtime-tmp/full-experience/service.log。')
            value = health()
            if value is None:
                raise RuntimeError('后台未就绪，请检查工作站日志。')
        report(value)
        webbrowser.open(URL + '/cases')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc))
        raise SystemExit(1)
