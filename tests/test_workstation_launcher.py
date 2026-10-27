import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

import workstation_launcher as launcher
import workstation_https as https


ROOT = Path(__file__).resolve().parents[1]


def child_lock(path):
    code = ('from pathlib import Path; from workstation_launcher import startup_lock; '
            'import sys\nwith startup_lock(Path(sys.argv[1])) as held:\n sys.exit(0 if held else 2)')
    return subprocess.run([sys.executable, '-c', code, str(path)], cwd=ROOT,
                          capture_output=True, timeout=10).returncode


def test_real_cross_process_lock_blocks_and_releases(tmp_path):
    path = tmp_path / 'startup.lock'
    with launcher.startup_lock(path) as held:
        assert held
        assert child_lock(path) == 2
    assert path.exists()  # Stale lock files must not block a later launch.
    assert child_lock(path) == 0


def test_process_exit_releases_lock(tmp_path):
    path = tmp_path / 'startup.lock'
    code = ('from workstation_launcher import startup_lock; import os, sys\n'
            'with startup_lock(sys.argv[1]) as held:\n os._exit(0 if held else 2)')
    result = subprocess.run([sys.executable, '-c', code, str(path)], cwd=ROOT, timeout=10)
    assert result.returncode == 0
    assert child_lock(path) == 0


def test_busy_start_does_not_launch_anything(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(launcher, 'DATA', tmp_path)
    start = Mock()
    monkeypatch.setattr(launcher, 'start_workstation', start)
    with launcher.startup_lock(tmp_path / 'startup.lock'):
        assert launcher.main() == 0
    start.assert_not_called()
    assert '没有重复启动' in capsys.readouterr().out


def model_files(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, 'ROOT', tmp_path)
    monkeypatch.setattr(launcher, 'DATA', tmp_path)
    for name in ['runtime/llama/llama-server.exe', 'runtime/models/Qwen3-4B-Q4_K_M.gguf']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def test_existing_loading_model_is_waited_without_second_process(tmp_path, monkeypatch):
    model_files(tmp_path, monkeypatch)
    monkeypatch.setattr(launcher, 'model_ready', lambda opener: False)
    monkeypatch.setattr(launcher, 'port_in_use', lambda port: True)
    wait = Mock(return_value=False)
    popen = Mock()
    monkeypatch.setattr(launcher, 'wait_for_model', wait)
    monkeypatch.setattr(launcher.subprocess, 'Popen', popen)
    assert launcher.start_model() is False
    wait.assert_called_once()
    assert len(wait.call_args.args) == 1  # Existing process is never terminated.
    popen.assert_not_called()


def test_failed_owned_model_is_stopped_before_unlock(tmp_path, monkeypatch):
    model_files(tmp_path, monkeypatch)
    monkeypatch.setattr(launcher, 'model_ready', lambda opener: False)
    monkeypatch.setattr(launcher, 'port_in_use', lambda port: False)
    monkeypatch.setattr(launcher, 'wait_for_model', lambda *args: False)
    process = Mock(pid=123)
    process.poll.return_value = None
    monkeypatch.setattr(launcher.subprocess, 'Popen', Mock(return_value=process))
    assert launcher.start_model() is False
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=5)


@pytest.mark.parametrize('raised', [False, True])
def test_page_can_open_but_model_failure_is_explicit(tmp_path, monkeypatch, capsys, raised):
    import workstation_security
    monkeypatch.setattr(launcher, 'DATA', tmp_path)
    monkeypatch.setattr(workstation_security, 'protect_directory', lambda _: None)
    monkeypatch.setattr(launcher, 'start_model', Mock(side_effect=OSError('missing') if raised else None, return_value=False))
    monkeypatch.setattr(launcher, 'request_json', lambda path: {'required': False} if path.endswith('/status') else {'application': 'gd-workstation'})
    monkeypatch.setattr(launcher.subprocess, 'check_output', lambda *a, **kw: '123')
    monkeypatch.setattr(https, 'start', lambda: False)
    browser = Mock()
    monkeypatch.setattr(launcher.webbrowser, 'open', browser)
    monkeypatch.setattr(sys, 'argv', ['launcher'])
    assert launcher.main() == 1
    browser.assert_called_once_with('http://127.0.0.1:8765/')
    output = capsys.readouterr().out
    assert '模型尚未就绪' in output
    assert 'model.log' in output
    assert '本地 HTTPS 健康检查未通过' in output
    assert '本机页面和模型已就绪' not in output


def test_https_occupied_unverified_port_is_not_replaced(tmp_path, monkeypatch):
    binary = tmp_path / 'runtime/caddy/caddy.exe'
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(https, 'ROOT', tmp_path)
    monkeypatch.setattr(https, 'verified_health', lambda: False)
    monkeypatch.setattr(launcher, 'port_in_use', lambda _: True)
    prepare, popen = Mock(), Mock()
    monkeypatch.setattr(https, 'prepare', prepare)
    monkeypatch.setattr(https.subprocess, 'Popen', popen)
    assert https.start() is False
    prepare.assert_not_called()
    popen.assert_not_called()


def test_https_spawn_is_not_success_without_verified_health(tmp_path, monkeypatch):
    binary = tmp_path / 'runtime/caddy/caddy.exe'
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(https, 'ROOT', tmp_path)
    monkeypatch.setattr(https, 'DATA', tmp_path)
    monkeypatch.setattr(https, 'TLS', tmp_path)
    monkeypatch.setattr(https, 'verified_health', lambda: False)
    monkeypatch.setattr(launcher, 'port_in_use', lambda _: False)
    monkeypatch.setattr(https, 'prepare', lambda: None)
    monkeypatch.setattr(https.subprocess, 'run', Mock())
    process = Mock(pid=123)
    process.poll.return_value = 1
    monkeypatch.setattr(https.subprocess, 'Popen', Mock(return_value=process))
    assert https.start() is False


@pytest.fixture
def tls_server(tmp_path, monkeypatch):
    """Real loopback TLS verifies the certificate, not a mocked success flag."""
    from datetime import datetime, timedelta, timezone
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import ipaddress
    import ssl
    import threading
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'GD test only')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
    ca = tmp_path / 'GD-workstation-CA.crt'
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path = tmp_path / 'test.key'
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    class Handler(BaseHTTPRequestHandler):
        redirect = False
        application = 'gd-workstation'

        def do_GET(self):
            if self.redirect:
                self.send_response(302)
                self.send_header('Location', '/healthy')
                self.end_headers()
                return
            body = json.dumps({'application': self.application}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(https, 'TLS', tmp_path)
    monkeypatch.setattr(https, 'HEALTH_URL', f'https://127.0.0.1:{server.server_port}/api/health')
    try:
        yield Handler, ca
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_https_accepts_only_ca_verified_correct_application(tls_server):
    handler, _ = tls_server
    assert https.verified_health() is True
    handler.application = 'other-application'
    assert https.verified_health() is False


def test_https_rejects_redirect(tls_server):
    handler, _ = tls_server
    handler.redirect = True
    assert https.verified_health() is False


def test_https_rejects_missing_ca(tls_server):
    _, ca = tls_server
    ca.unlink()
    assert https.verified_health() is False


def test_https_rejects_valid_but_unrelated_ca(tls_server):
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    _, ca = tls_server
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Unrelated test CA')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                   .not_valid_after(now + timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                   .sign(key, hashes.SHA256()))
    ca.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    assert https.verified_health() is False


def test_https_rejects_ip_san_mismatch(tls_server, monkeypatch):
    monkeypatch.setattr(https, 'HEALTH_URL', https.HEALTH_URL.replace('127.0.0.1', 'localhost'))
    assert https.verified_health() is False
