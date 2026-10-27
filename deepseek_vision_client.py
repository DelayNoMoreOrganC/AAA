"""Bounded standard DeepSeek vision transport; no retries or provider fallback."""
from __future__ import annotations

import json
import re
from time import perf_counter

import requests
from requests.adapters import HTTPAdapter

ENDPOINT = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
MAX_RESPONSE_BYTES = 2_000_000

_ERROR_MESSAGES = {
    "KEY_MISSING": "尚未配置 DeepSeek 标准 API 密钥",
    "KEY_INVALID": "DeepSeek 标准 API 密钥格式无效",
    "AUTH_FAILED": "DeepSeek API 鉴权失败，请检查密钥及模型权限",
    "QUOTA_EXHAUSTED": "DeepSeek API 余额不足，请检查标准 API 额度",
    "RATE_LIMITED": "DeepSeek API 配额或并发受限，请稍后手动重试",
    "HTTP_FAILED": "DeepSeek API 请求未成功，已停止且未切换服务商",
    "RESPONSE_TOO_LARGE": "DeepSeek 响应超过安全大小限制",
    "INCOMPLETE": "DeepSeek 未完整返回结果，请缩小材料批次后重试",
    "INVALID_RESPONSE": "DeepSeek 未返回有效 JSON 归档操作",
    "CONNECTION_FAILED": "DeepSeek 连接或响应读取失败，已停止且未切换服务商",
    "PROBE_FAILED": "DeepSeek 连通检查未返回预期结果",
}
# Do not expose an arbitrary error.code string supplied in a provider response.
_PROVIDER_CODES = frozenset({
    "invalid_api_key", "authentication_error", "permission_denied",
    "invalid_request_error", "insufficient_quota", "insufficient_balance",
    "rate_limit_exceeded", "context_length_exceeded", "model_not_found",
    "server_error", "service_unavailable", "not_found",
    "400", "401", "402", "403", "404", "422", "429", "500", "503",
})
_MODEL_FORMAT = re.compile(r"deepseek-(?:v\d{1,2}(?:\.\d{1,2}){0,2}-)?flash(?:-\d{4}-?\d{2}-?\d{2})?\Z")


class DeepSeekVisionError(RuntimeError):
    """Fixed diagnostics only. Never retain response bodies, prompts or keys."""

    def __init__(self, code="CONNECTION_FAILED", *, http_status=None, provider_code=None):
        self.code = code if type(code) is str and code in _ERROR_MESSAGES else "CONNECTION_FAILED"
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        self.provider_code = provider_code if type(provider_code) is str and provider_code in _PROVIDER_CODES else None
        message = _ERROR_MESSAGES[self.code]
        if self.http_status is not None:
            message += f" [HTTP {self.http_status}]"
        if self.provider_code is not None:
            message += f" [{self.provider_code}]"
        super().__init__(message)


def _provider_code(raw):
    try:
        error = json.loads(raw).get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if type(code) is int and code in (400, 401, 402, 403, 404, 422, 429, 500, 503):
            code = str(code)
        return code if type(code) is str and code in _PROVIDER_CODES else None
    except (ValueError, TypeError, AttributeError):
        return None


def _bounded_body(response):
    chunks, size = [], 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise DeepSeekVisionError("RESPONSE_TOO_LARGE", http_status=response.status_code)
        chunks.append(chunk)
    return b"".join(chunks)


class DeepSeekVisionClient:
    def __init__(self, api_key):
        if not isinstance(api_key, str) or not api_key.strip():
            raise DeepSeekVisionError("KEY_MISSING")
        if len(api_key) > 512 or any(char.isspace() for char in api_key):
            raise DeepSeekVisionError("KEY_INVALID")
        self._api_key = api_key
        self.metrics = {"model_requests": 0, "model_failed_requests": 0,
                        "model_seconds": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
                        "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0,
                        "returned_model": ""}

    def _record_usage(self, result):
        usage = result.get("usage")
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                value = usage.get(key)
                if type(value) is int and 0 <= value <= 1_000_000_000:
                    self.metrics[key] += value
        model = result.get("model")
        if type(model) is str and len(model) <= 64 and _MODEL_FORMAT.fullmatch(model):
            self.metrics["returned_model"] = model

    def complete(self, messages):
        body = {"model": MODEL, "messages": messages, "stream": False,
                "thinking": {"type": "disabled"}, "max_tokens": 8192,
                "response_format": {"type": "json_object"}}
        self.metrics["model_requests"] += 1
        started = perf_counter()
        try:
            with requests.Session() as session:
                session.trust_env = False
                session.mount("https://", HTTPAdapter(max_retries=0))
                with session.post(ENDPOINT, json=body,
                        headers={"Authorization": "Bearer " + self._api_key},
                        timeout=(10, 180), allow_redirects=False, stream=True) as response:
                    status = response.status_code
                    raw = _bounded_body(response)
                    if status != 200:
                        code = "AUTH_FAILED" if status in (401, 403) else "QUOTA_EXHAUSTED" if status == 402 else "RATE_LIMITED" if status == 429 else "HTTP_FAILED"
                        raise DeepSeekVisionError(code, http_status=status, provider_code=_provider_code(raw))
            try:
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError()
                self._record_usage(result)
                choice = result["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise DeepSeekVisionError("INCOMPLETE")
                content = choice["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError()
                action = json.loads(content)
                if not isinstance(action, dict):
                    raise ValueError()
            except DeepSeekVisionError:
                raise
            except (ValueError, KeyError, TypeError, IndexError, AttributeError):
                raise DeepSeekVisionError("INVALID_RESPONSE") from None
            return action
        except DeepSeekVisionError:
            self.metrics["model_failed_requests"] += 1
            raise
        except Exception:
            self.metrics["model_failed_requests"] += 1
            raise DeepSeekVisionError("CONNECTION_FAILED") from None
        finally:
            self.metrics["model_seconds"] += max(0, perf_counter() - started)


def probe(api_key):
    """Explicit billable text-only check; never loads local files or material."""
    client = DeepSeekVisionClient(api_key)
    result = client.complete([{"role": "user", "content": '连接测试，请仅返回JSON对象 {"ok": true}。'}])
    if result.get("ok") is not True:
        raise DeepSeekVisionError("PROBE_FAILED")
    return {"ready": True, "model": MODEL, "provider": "deepseek",
            "returned_model": client.metrics["returned_model"],
            "usage": {key: client.metrics[key] for key in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")}}
