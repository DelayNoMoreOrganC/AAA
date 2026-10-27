"""Local model security/failure boundaries using fictional inputs and no network."""
import pytest

import archive_pipeline as ap
import settings
from document_segmenter import DocumentSource


@pytest.fixture
def local_config():
    config = {
        "privacy": {"mode": "local"},
        "deepseek": {
            "api_key": "fictional-local-token",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "fictional-local-model",
            # Intentionally omit local_only: privacy policy must still apply.
        },
        "output": {"preview_only": True},
    }
    settings.push_config(config)
    try:
        yield config
    finally:
        settings.pop_config()


@pytest.fixture
def fake_session(monkeypatch):
    import requests

    class Response:
        status_code = 200

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("fictional model error")

        def json(self):
            return {"choices": [{"message": {"content": '{"委托人":"虚构甲"}'}}]}

    class Session:
        def __init__(self):
            self.trust_env = True
            self.calls = []
            self.response = Response()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return self.response

    session = Session()
    monkeypatch.setattr(requests, "Session", lambda: session)
    return session


@pytest.mark.parametrize("base_url", [
    "https://external.example/v1",
    "http://127.0.0.1.external.example/v1",
    "http://localhost:11434/v1",  # do not depend on DNS/hosts resolution
    "http://192.168.1.12:11434/v1",
    "http://169.254.169.254/v1",
    "http://0.0.0.0:11434/v1",
    "http://2130706433/v1",
    "http://[2001:db8::1]/v1",
    "ftp://127.0.0.1/v1",
    "http://user:pass@127.0.0.1/v1",
    "http://127.0.0.1/v1?destination=external.example",
    "http://127.0.0.1/v1#external.example",
])
def test_local_rejects_non_literal_loopback_before_post(local_config, fake_session, base_url):
    local_config["deepseek"]["base_url"] = base_url
    with pytest.raises(RuntimeError, match="本地保密模式禁止"):
        ap._deepseek_request("虚构材料", "按原文提取")
    assert fake_session.calls == []


@pytest.mark.parametrize("base_url", [
    "http://127.0.0.1:11434/v1", "http://127.1.2.3:1234/v1", "http://[::1]:11434/v1",
])
def test_local_disables_environment_proxy_and_redirects(local_config, fake_session, monkeypatch, base_url):
    local_config["deepseek"]["base_url"] = base_url
    monkeypatch.setenv("HTTP_PROXY", "http://external-proxy.example:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://external-proxy.example:8080")
    monkeypatch.setenv("ALL_PROXY", "http://external-proxy.example:8080")
    monkeypatch.setenv("NETRC", "fictional-credentials-file")
    assert ap._deepseek_request("虚构材料", "按原文提取") == '{"委托人":"虚构甲"}'
    assert fake_session.trust_env is False
    assert len(fake_session.calls) == 1
    url, kwargs = fake_session.calls[0]
    assert url == base_url + "/chat/completions"
    assert kwargs["allow_redirects"] is False
    assert "proxies" not in kwargs


@pytest.mark.parametrize("status_code", [301, 302, 303, 307, 308])
def test_redirect_response_is_rejected_without_follow_up(local_config, fake_session, status_code):
    fake_session.response.status_code = status_code
    fake_session.response.headers = {"Location": "https://external.example/upload"}
    with pytest.raises(RuntimeError, match="跳转"):
        ap._deepseek_request("虚构材料", "按原文提取")
    assert len(fake_session.calls) == 1
    assert fake_session.calls[0][1]["allow_redirects"] is False


def test_local_privacy_overrides_false_provider_flag(local_config, fake_session):
    local_config["deepseek"].update(local_only=False, base_url="https://external.example")
    assert settings.get_deepseek_config()["local_only"] is True
    with pytest.raises(RuntimeError, match="本地保密模式禁止"):
        ap._deepseek_request("虚构材料", "按原文提取")
    assert not fake_session.calls


@pytest.mark.parametrize("content", [
    "", "{}", '{"委托人":""}', '{"委托人":"待确认"}',
    "error: fictional model unavailable", '{"案件类别":"民事"}', "无法生成结构化结果",
])
def test_unusable_local_output_fails_explicitly(local_config, monkeypatch, content):
    calls = []

    def respond(*_args):
        calls.append(1)
        return content

    monkeypatch.setattr(ap, "_deepseek_request", respond)
    with pytest.raises(ap.FieldExtractionError, match="没有返回可用字段"):
        ap._deepseek_chat("虚构材料", "按原文提取")
    assert len(calls) == 2


def test_local_network_failure_is_not_swallowed_by_segmented_route(local_config, monkeypatch):
    def fail(*_args):
        raise RuntimeError("fictional connection refused")

    monkeypatch.setattr(ap, "_deepseek_request", fail)
    with pytest.raises(ap.FieldExtractionError, match="connection refused"):
        ap.extract_fields_segmented({"contract": "虚构法律服务委托合同，仅为离线测试材料。" * 4}, case_type="civil")


@pytest.mark.parametrize("doc_type", ["default", "contract"])
def test_archive_analysis_cannot_report_success_after_local_model_failure(local_config, monkeypatch, tmp_path, doc_type):
    source = str(tmp_path / "fictional.pdf")
    text = "虚构法律服务委托合同，以下内容仅用于测试。" * 4
    monkeypatch.setattr(ap, "ingest_archive_sources", lambda *_a, **_kw: (
        {source: text}, {source: [text]}, {}, 0, 0,
    ))
    monkeypatch.setattr(ap.pdl, "build_units_from_sources", lambda *_a, **_kw: [])

    def fail(*_args, **_kwargs):
        raise RuntimeError("fictional model process failed")

    monkeypatch.setattr(ap, "extract_fields_auto", fail)
    with pytest.raises(ap.FieldExtractionError, match="model process failed"):
        ap.analyze_archive("civil", config=local_config, sources=[DocumentSource(path=source, doc_type=doc_type)])


def test_execution_extraction_preserves_pending_payment(local_config, monkeypatch):
    content = '{"结案小结":"申请执行人申请参与分配，尚未收到款项。"}'
    monkeypatch.setattr(ap, "_deepseek_request", lambda *_a: content)
    fields = ap.extract_fields_segmented(
        {"execution": "虚构执行材料：申请执行人申请参与分配，尚未收到款项。仅供离线测试。"},
        case_type="civil",
    )
    assert "尚未收到款项" in fields["结案小结"]
    assert "依法受偿" not in fields["结案小结"]
