"""Application-level acceptance guard, not an OS firewall or native-process sandbox.

Run only with fictional materials. Socket API entry checks and CPython audit
events refuse destinations other than literal loopback addresses. Native libraries and child
processes (model, Chromium, LibreOffice) are outside this guard's coverage.
Audit records contain event/destination metadata only, never request bodies.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import threading
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


class LocalBoundaryGuard:
    def __init__(self, audit_file: Path | None = None):
        self.enabled = True
        self.records: list[dict] = []
        self.audit_file = audit_file
        self.lock = threading.Lock()

    @staticmethod
    def is_loopback(host) -> bool:
        try:
            address = ipaddress.ip_address(host)
            # IPv4-mapped IPv6 must be loopback in its underlying address too.
            return bool(address.is_loopback or (getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback))
        except (ValueError, TypeError):
            return False

    def _record(self, event: str, host, port, allowed: bool):
        # Destination only; no URLs, tokens, headers, prompts or source text.
        record = {"time": datetime.now(timezone.utc).isoformat(), "event": event,
                  "host": str(host)[:253], "port": port, "allowed": allowed}
        with self.lock:
            self.records.append(record)
            if self.audit_file:
                with self.audit_file.open('a', encoding='utf-8') as output:
                    output.write(json.dumps(record, ensure_ascii=False) + '\n')

    def audit(self, event: str, args):
        if not self.enabled:
            return
        host = port = None
        if event in ('socket.connect', 'socket.bind'):
            sock, address = args[:2]
            if sock.family not in (socket.AF_INET, socket.AF_INET6):
                return
            host, port = address[:2]
        elif event == 'socket.sendto':
            sock, address = args[0], args[-1]
            if sock.family not in (socket.AF_INET, socket.AF_INET6):
                return
            host, port = address[:2]
        elif event == 'socket.getaddrinfo':
            host, port = args[:2]
        elif event in ('socket.gethostbyname', 'socket.gethostbyaddr'):
            host = args[0]
        else:
            return
        allowed = self.is_loopback(host)
        self._record(event, host, port, allowed)
        if not allowed:
            raise PermissionError('Application-level local-only acceptance guard blocked a non-loopback socket operation')

    def install(self):
        if self.audit_file:
            self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        sys.addaudithook(self.audit)
        # On Windows, socket.connect(hostname) resolves its hostname in C before
        # the connect audit event. Check at the Python API entry as well, before
        # allowing the native method to perform any implicit DNS lookup.
        for name, event in (("connect", "socket.connect"), ("connect_ex", "socket.connect"), ("bind", "socket.bind")):
            original = getattr(socket.socket, name)
            def checked(sock, address, _original=original, _event=event):
                self.audit(_event, (sock, address))
                return _original(sock, address)
            setattr(socket.socket, name, checked)
        original_sendto = socket.socket.sendto
        def checked_sendto(sock, data, *args):
            self.audit('socket.sendto', (sock, args[-1]))
            return original_sendto(sock, data, *args)
        socket.socket.sendto = checked_sendto
        return self


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--data-dir', type=Path, default=ROOT / '.runtime-tmp/privacy-acceptance')
    parser.add_argument('--model-base', default='http://127.0.0.1:11434/v1')
    parser.add_argument('--model', default='gd-qwen3-4b')
    args = parser.parse_args()
    data = args.data_dir.resolve()
    data.mkdir(parents=True, exist_ok=True)
    os.environ.update(V5_DATA_DIR=str(data), V5_DATABASE_URL='', V5_HOST='127.0.0.1',
        V5_PORT=str(args.port), V5_PREVIEW_ONLY='true', V5_ALLOW_EXTERNAL_AI='false',
        V5_REGISTRATION_ENABLED='false', V5_LOCAL_LLM_BASE_URL=args.model_base,
        V5_LOCAL_LLM_MODEL=args.model, TEMP=str(data), TMP=str(data))
    sys.path[:0] = [str(ROOT / 'web/backend'), str(ROOT)]
    LocalBoundaryGuard(data / 'socket-audit.jsonl').install()
    print('Fictional-data acceptance: CPython socket operations limited to literal loopback.', flush=True)
    print('Native libraries and child processes are NOT covered; this is NOT OS disconnection.', flush=True)
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=args.port, reload=False, workers=1, access_log=False)


if __name__ == '__main__':
    main()
