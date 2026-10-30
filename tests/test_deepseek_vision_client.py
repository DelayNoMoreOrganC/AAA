"""DeepSeek transport regressions with synthetic responses, never a live API."""
import json

import pytest

import deepseek_vision_client as ds

PRIVATE = "SYNTHETIC_PRIVATE_BODY_AND_KEY"


def answer(content='{"ok":true}', **extra):
    return {"model": "deepseek-v4-flash", "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3,
                      "prompt_cache_hit_tokens": 8, "prompt_cache_miss_tokens": 4}, **extra}


class Response:
    def __init__(self, status=200, body=None, chunks=None):
        self.status_code = status
        self.body = answer() if body is None else body
        self.chunks = chunks
        self.closed = False
    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True
    def iter_content(self, chunk_size):
        assert chunk_size == 65536
        if self.chunks is not None:
            yield from self.chunks
        else:
            yield self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()


def wire(monkeypatch, response=None, failure=None):
    seen, adapters = [], []
    class Session:
        trust_env = True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def mount(self, prefix, adapter): adapters.append((prefix, adapter))
        def post(self, url, **kwargs):
            seen.append({"url": url, "trust_env": self.trust_env, **kwargs})
            if failure is not None:
                raise failure
            return response
    monkeypatch.setattr(ds.requests, "Session", Session)
    return seen, adapters


def test_fixed_endpoint_native_images_json_disabled_thinking_and_no_retry(monkeypatch):
    response = Response()
    seen, adapters = wire(monkeypatch, response)
    images = [{"role":"user", "content":[{"type":"text", "text":"fictional"},
        {"type":"image_url", "image_url":{"url":"data:image/jpeg;base64,c3ludGhldGlj"}}]}]
    client = ds.DeepSeekVisionClient("synthetic-key")
    assert client.complete(images) == {"ok": True}
    req = seen[0]
    assert req["url"] == "https://api.deepseek.com/chat/completions"
    assert req["trust_env"] is False and req["allow_redirects"] is False
    assert req["stream"] is True and req["timeout"] == (10, 180)
    assert req["headers"] == {"Authorization":"Bearer synthetic-key"}
    assert req["json"] == {"model":"deepseek-flash", "messages":images, "stream":False,
        "thinking":{"type":"disabled"}, "max_tokens":8192, "response_format":{"type":"json_object"}}
    assert len(adapters) == 1 and adapters[0][0] == "https://" and adapters[0][1].max_retries.total == 0
    assert client.metrics["model_requests"] == 1 and client.metrics["model_failed_requests"] == 0
    assert client.metrics["prompt_tokens"] == 12 and client.metrics["completion_tokens"] == 3
    assert client.metrics["prompt_cache_hit_tokens"] == 8 and client.metrics["prompt_cache_miss_tokens"] == 4
    assert client.metrics["returned_model"] == "deepseek-v4-flash" and response.closed


def test_oversize_request_is_not_sent_or_retried(monkeypatch):
    seen,_=wire(monkeypatch,Response())
    monkeypatch.setattr(ds,'MAX_REQUEST_BYTES',100)
    client=ds.DeepSeekVisionClient('synthetic-key')
    with pytest.raises(ds.DeepSeekVisionError) as error:
        client.complete([{'role':'user','content':'原件'*100}])
    assert error.value.code=='REQUEST_TOO_LARGE' and seen==[]


@pytest.mark.parametrize("status", [301, 302, 307, 400, 401, 402, 403, 404, 422, 429, 500, 503])
def test_provider_http_error_is_safe_and_never_retried(monkeypatch, status):
    seen, _ = wire(monkeypatch, Response(status, {"error":{"code":"invalid_api_key", "message": PRIVATE}, "data":PRIVATE}))
    client = ds.DeepSeekVisionClient("synthetic-key")
    with pytest.raises(ds.DeepSeekVisionError) as caught:
        client.complete([])
    error = caught.value
    assert error.http_status == status and error.provider_code == "invalid_api_key"
    assert PRIVATE not in str(error) and "synthetic-key" not in str(error)
    assert len(seen) == 1 and client.metrics["model_failed_requests"] == 1


@pytest.mark.parametrize("provider_code", [PRIVATE, "invalid_request_error\n" + PRIVATE, {"nested":PRIVATE}, True, 123456789])
def test_unrecognized_provider_code_is_never_exposed(monkeypatch, provider_code):
    wire(monkeypatch, Response(400, {"error":{"code":provider_code, "message":PRIVATE}}))
    with pytest.raises(ds.DeepSeekVisionError) as caught:
        ds.DeepSeekVisionClient("synthetic-key").complete([])
    assert caught.value.provider_code is None and PRIVATE not in str(caught.value)


@pytest.mark.parametrize("body", [b"not-json " + PRIVATE.encode(), [], {},
    answer(content="[]"), answer(content=PRIVATE), answer(content=None),
    answer(choices=[{"finish_reason":"length", "message":{"content":'{"ok":true}'}}]),
    answer(choices=[]), answer(choices=[{"finish_reason":"stop", "message":{}}])])
def test_invalid_incomplete_response_is_not_success(monkeypatch, body):
    wire(monkeypatch, Response(body=body))
    client = ds.DeepSeekVisionClient("synthetic-key")
    with pytest.raises(ds.DeepSeekVisionError) as caught:
        client.complete([])
    assert PRIVATE not in str(caught.value) and client.metrics["model_failed_requests"] == 1


@pytest.mark.parametrize("status", [200, 400])
def test_streaming_response_limit_applies_also_to_error_bodies(monkeypatch, status):
    response = Response(status, chunks=[b"A" * 1_000_000, b"A" * 1_000_000, b"B"])
    seen, _ = wire(monkeypatch, response)
    with pytest.raises(ds.DeepSeekVisionError) as caught:
        ds.DeepSeekVisionClient("synthetic-key").complete([])
    assert caught.value.code == "RESPONSE_TOO_LARGE" and len(seen) == 1 and response.closed


def test_network_failure_never_retains_diagnostics_or_retries(monkeypatch):
    seen, _ = wire(monkeypatch, failure=RuntimeError(PRIVATE))
    client = ds.DeepSeekVisionClient("synthetic-key")
    with pytest.raises(ds.DeepSeekVisionError) as caught:
        client.complete([])
    assert caught.value.code == "CONNECTION_FAILED" and PRIVATE not in str(caught.value)
    assert caught.value.__suppress_context__ is True
    assert len(seen) == 1 and client.metrics["model_failed_requests"] == 1


@pytest.mark.parametrize("model", [PRIVATE, "deepseek-" + PRIVATE, "deepseek-flash\n" + PRIVATE, {}, "deepseek-flash-" + "9"*200])
def test_metrics_do_not_capture_arbitrary_provider_text(monkeypatch, model):
    wire(monkeypatch, Response(body=answer(model=model, usage={"prompt_tokens":PRIVATE,
        "completion_tokens":True, "prompt_cache_hit_tokens":-1, "prompt_cache_miss_tokens":10**50})))
    client = ds.DeepSeekVisionClient("synthetic-key")
    client.complete([])
    assert client.metrics["returned_model"] == ""
    assert all(client.metrics[key] == 0 for key in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"))
    assert PRIVATE not in json.dumps(client.metrics)


def test_metrics_are_cumulative_and_usage_recorded_for_truncated_result(monkeypatch):
    wire(monkeypatch, Response())
    client = ds.DeepSeekVisionClient("synthetic-key")
    client.complete([])
    wire(monkeypatch, Response(body=answer(choices=[{"finish_reason":"length", "message":{"content":""}}])))
    with pytest.raises(ds.DeepSeekVisionError): client.complete([])
    assert client.metrics["model_requests"] == 2 and client.metrics["model_failed_requests"] == 1
    assert client.metrics["prompt_tokens"] == 24 and client.metrics["prompt_cache_hit_tokens"] == 16


@pytest.mark.parametrize("key", [None, "", "   ", "bad key", "bad\nkey", "k"*513])
def test_invalid_key_never_reaches_network(monkeypatch, key):
    seen, _ = wire(monkeypatch, Response())
    with pytest.raises(ds.DeepSeekVisionError): ds.probe(key)
    assert seen == []


def test_probe_is_text_only_and_does_not_claim_false_success(monkeypatch):
    seen, _ = wire(monkeypatch, Response())
    result = ds.probe("synthetic-key")
    assert result["ready"] is True and result["provider"] == "deepseek" and result["model"] == "deepseek-flash"
    assert seen[0]["json"]["messages"] == [{"role":"user", "content":'连接测试，请仅返回JSON对象 {"ok": true}。'}]
    wire(monkeypatch, Response(body=answer('{"ok":false}')))
    with pytest.raises(ds.DeepSeekVisionError) as caught: ds.probe("synthetic-key")
    assert caught.value.code == "PROBE_FAILED"


def test_error_constructor_cannot_echo_arbitrary_parameters():
    error = ds.DeepSeekVisionError(PRIVATE, http_status=PRIVATE, provider_code=PRIVATE)
    assert error.code == "CONNECTION_FAILED" and error.http_status is None and error.provider_code is None
    assert PRIVATE not in str(error)
