"""Fictional inputs only; CPython guard is not an OS/native-process sandbox."""
from html.parser import HTMLParser
import json
from pathlib import Path
import socket
import sys

import fitz
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[3]), str(Path(__file__).resolve().parents[3] / 'scripts')]
from local_boundary_guard import LocalBoundaryGuard


@pytest.fixture
def local_guard(tmp_path):
    guard = LocalBoundaryGuard(tmp_path / 'audit.jsonl').install()
    try:
        yield guard
    finally:
        # Audit hooks cannot be removed. Disable this fixture's hook after test.
        guard.enabled = False


@pytest.mark.parametrize('host', ['192.0.2.1', '10.0.0.1', '169.254.169.254', '0.0.0.0', 'external.invalid'])
def test_blocks_non_loopback_before_connect(local_guard, host):
    with socket.socket() as connection, pytest.raises(PermissionError, match='local-only'):
        connection.connect((host, 9))
    assert local_guard.records[-1]['allowed'] is False


def test_blocks_dns_and_datagram_without_logging_payload(local_guard):
    with pytest.raises(PermissionError):
        socket.getaddrinfo('external.invalid', 443)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection, pytest.raises(PermissionError):
        connection.sendto(b'fictional-body-must-not-be-logged', ('192.0.2.1', 53))
    audit = local_guard.audit_file.read_text(encoding='utf-8')
    assert 'fictional-body' not in audit
    assert all(record['allowed'] is False for record in local_guard.records)


def test_localhost_tcp_roundtrip_is_allowed(local_guard):
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0)); server.listen(1)
        with socket.create_connection(server.getsockname()) as client:
            connection, _address = server.accept()
            with connection:
                client.sendall(b'fictional')
                assert connection.recv(20) == b'fictional'
    assert local_guard.records and all(record['allowed'] for record in local_guard.records)


def test_real_scanned_page_ocr_needs_no_python_socket_or_body_log(local_guard, tmp_path):
    import local_ocr
    if local_ocr.util.find_spec('rapidocr_onnxruntime') is None:
        pytest.skip('fixed bundled local OCR not installed')
    source = tmp_path / 'fictional.pdf'
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 120), 'FICTIONAL PRIVACY TEST 2026', fontsize=23)
        page.insert_text((72, 180), '虚构保密测试材料', fontname='china-s', fontsize=23)
        raster = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes('png')
    with fitz.open() as document:
        page = document.new_page(); page.insert_image(page.rect, stream=raster)
        assert not page.get_text().strip()
        document.save(source)
    logs = []
    result = local_ocr.read_local_pdf(str(source), log=logs.append)
    assert result.ocr_pages == 1 and '2026' in result.page_texts[0]
    assert '虚构保密测试材料' in result.page_texts[0]
    assert not local_guard.records
    assert 'FICTIONAL' not in '\n'.join(logs) and '虚构保密测试材料' not in '\n'.join(logs)


class Resources(HTMLParser):
    def __init__(self):
        super().__init__(); self.tags=[]; self.attributes=[]; self.styles=[]; self.in_style=False
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag); self.attributes.extend(attrs)
        if tag == 'style': self.in_style=True
    def handle_endtag(self, tag):
        if tag == 'style': self.in_style=False
    def handle_data(self, text):
        if self.in_style: self.styles.append(text)


def test_all_five_generated_html_forms_have_no_remote_or_executable_resources(local_guard):
    from app.services.browser_pdf_service import FORM_LAYOUTS, render_form_html
    payload = '<img src="https://external.invalid/fake"><script>fetch("//external.invalid")</script>'
    for name in FORM_LAYOUTS:
        fields = {'委托人':payload, '结案小结':payload, '法院文件清单':payload,
                  '_preview_styles':{name:{'field:委托人':{'fontFamily':'url(https://external.invalid/font)','color':'red; background:url(https://external.invalid/image)'}}}}
        parser = Resources(); parser.feed(render_form_html(name, fields, payload))
        assert not set(parser.tags) & {'script','img','link','iframe','object','embed','base','audio','video','source'}
        assert not any(key in {'src','srcset','href','poster','action','formaction'} or key.startswith('on') for key,_value in parser.attributes)
        styles='\n'.join(parser.styles+[value for key,value in parser.attributes if key=='style'])
        assert 'url(' not in styles.lower() and '@import' not in styles.lower()
    assert not local_guard.records
