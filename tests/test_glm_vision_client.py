"""Wire contract tests using fake HTTP responses; never a live paid API."""
import json

import pytest

import glm_vision_client as glm


class Response:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.body = body if body is not None else {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
                                                   "usage": {"prompt_tokens": 12, "completion_tokens": 3}}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, chunk_size):
        yield self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()


def wire(monkeypatch, response):
    seen = []
    class Session:
        trust_env = True
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, **kwargs):
            seen.append({"url": url, "trust_env": self.trust_env, **kwargs})
            return response
    monkeypatch.setattr(glm.requests, "Session", Session)
    return seen


def test_standard_endpoint_native_images_and_enabled_thinking(monkeypatch):
    seen = wire(monkeypatch, Response())
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,synthetic"}}]}]
    client = glm.GlmVisionClient("fictional-key")
    assert client.complete(messages) == {"ok": True}
    request = seen[0]
    assert request["url"] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert request["trust_env"] is False and request["allow_redirects"] is False
    assert request["headers"] == {"Authorization": "Bearer fictional-key"}
    assert request["json"]["model"] == "glm-5.3-flash"
    assert request["json"]["thinking"] == {"type": "enabled"}
    assert request["json"]["reasoning_effort"] == "low"
    assert request["json"]["messages"] is messages
    assert client.metrics["model_requests"] == 1
    assert client.metrics["prompt_tokens"] == 12 and client.metrics["completion_tokens"] == 3


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_provider_failure_never_leaks_response_or_retries(monkeypatch, status):
    seen = wire(monkeypatch, Response(status, b"PRIVATE_KEY_AND_CUSTOMER_BODY"))
    client = glm.GlmVisionClient("fictional-key")
    with pytest.raises(glm.GlmVisionError) as error:
        client.complete([{"role": "user", "content": "fictional"}])
    assert len(seen) == 1
    assert "PRIVATE" not in str(error.value)
    assert client.metrics["model_failed_requests"] == 1


@pytest.mark.parametrize("body", [b"not json PRIVATE_BODY", b"A"*2_000_001,
    {"choices": [{"finish_reason": "length", "message": {"content": '{"ok":true}'}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": '[]'}}]}], ids=["invalid-json", "oversized", "truncated", "not-object"])
def test_truncated_invalid_or_oversized_response_is_not_success(monkeypatch, body):
    wire(monkeypatch, Response(body=body))
    with pytest.raises(glm.GlmVisionError) as error:
        glm.GlmVisionClient("fictional-key").complete([])
    assert "PRIVATE" not in str(error.value)


def test_probe_contains_no_material_and_requires_key_before_network(monkeypatch):
    seen = wire(monkeypatch, Response())
    with pytest.raises(glm.GlmVisionError):
        glm.probe("")
    assert seen == []
    assert glm.probe("fictional-key")["ready"] is True
    assert len(seen) == 1
    assert seen[0]["json"]["messages"] == [{"role": "user", "content": '连接测试，请仅返回JSON对象 {"ok": true}。'}]
