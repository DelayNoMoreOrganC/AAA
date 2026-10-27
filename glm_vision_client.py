"""Standard BigModel API adapter. No Coding Plan endpoint or cloud fallback."""
from __future__ import annotations

import json
from time import perf_counter

import requests

ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-5.3-flash"


class GlmVisionError(RuntimeError):
    """Only fixed errors cross the provider boundary; never response bodies."""


class GlmVisionClient:
    def __init__(self, api_key):
        if not isinstance(api_key, str) or not api_key.strip():
            raise GlmVisionError("尚未配置智谱标准模型 API 密钥")
        if len(api_key) > 512 or any(char.isspace() for char in api_key):
            raise GlmVisionError("智谱标准模型 API 密钥格式无效")
        self._api_key = api_key
        self.metrics = {"model_requests": 0, "model_failed_requests": 0,
                        "model_seconds": 0.0, "prompt_tokens": 0, "completion_tokens": 0}

    def complete(self, messages):
        # GLM-5.3-Flash only supports enabled thinking; low is a documented tier.
        body = {"model": MODEL, "messages": messages, "stream": False,
                "thinking": {"type": "enabled"}, "reasoning_effort": "low",
                "temperature": 1, "max_tokens": 8192,
                "response_format": {"type": "json_object"}}
        self.metrics["model_requests"] += 1
        started = perf_counter()
        try:
            with requests.Session() as session:
                session.trust_env = False
                with session.post(ENDPOINT, json=body,
                        headers={"Authorization": "Bearer " + self._api_key},
                        timeout=(10, 180), allow_redirects=False, stream=True) as response:
                    code = response.status_code
                    if code in (401, 403):
                        raise GlmVisionError("智谱模型 API 鉴权失败，请检查标准 API 密钥及模型权限")
                    if code == 429:
                        raise GlmVisionError("智谱模型 API 配额或并发受限，请检查标准 API 额度后重试")
                    if code != 200:
                        raise GlmVisionError("智谱模型 API 请求未成功，已停止且未切换服务商")
                    chunks, size = [], 0
                    for chunk in response.iter_content(chunk_size=65536):
                        size += len(chunk)
                        if size > 2_000_000:
                            raise GlmVisionError("智谱模型响应超过安全大小限制")
                        chunks.append(chunk)
                    result = json.loads(b"".join(chunks))
            choice = result["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise GlmVisionError("智谱模型未完整返回结果，请缩小材料批次后重试")
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise GlmVisionError("智谱模型没有返回有效归档操作")
            action = json.loads(content)
            if not isinstance(action, dict):
                raise GlmVisionError("智谱模型没有返回有效归档操作")
            usage = result.get("usage") or {}
            for key in ("prompt_tokens", "completion_tokens"):
                value = usage.get(key)
                if type(value) is int and value >= 0:
                    self.metrics[key] += value
            return action
        except GlmVisionError:
            self.metrics["model_failed_requests"] += 1
            raise
        except Exception:
            self.metrics["model_failed_requests"] += 1
            raise GlmVisionError("智谱模型连接或响应解析失败，已停止且未切换服务商") from None
        finally:
            self.metrics["model_seconds"] += max(0, perf_counter() - started)


def probe(api_key):
    """Explicit, billable text-only probe; no case, filenames or page images."""
    client = GlmVisionClient(api_key)
    result = client.complete([{"role": "user", "content": '连接测试，请仅返回JSON对象 {"ok": true}。'}])
    if result.get("ok") is not True:
        raise GlmVisionError("智谱模型连通检查未返回预期结果")
    return {"ready": True, "model": MODEL, "provider": "zhipu",
            "usage": {key: client.metrics[key] for key in ("prompt_tokens", "completion_tokens")}}
