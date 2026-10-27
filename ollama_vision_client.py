"""Local vision transport. Fixed loopback, guarded on every request, no fallback."""
from __future__ import annotations

import base64
import json
from time import perf_counter
import requests
from local_vision_catalog import DEFAULT_MODEL, ALLOWED_MODELS

MODEL = DEFAULT_MODEL
BASE_URL = "http://127.0.0.1:11435"
MAX_RESPONSE_BYTES = 2_000_000


class OllamaVisionError(RuntimeError):
    def __init__(self, code="UNAVAILABLE"):
        self.code = code if code in {"UNAVAILABLE", "INVALID_RESPONSE", "INCOMPLETE", "INVALID_INPUT"} else "UNAVAILABLE"
        super().__init__({"UNAVAILABLE": "本地视觉引擎未就绪，已停止且未转向云端",
                         "INVALID_RESPONSE": "本地模型未返回有效的归档操作",
                         "INCOMPLETE": "本地模型输出不完整，请检查上下文和内存",
                         "INVALID_INPUT": "本地视觉请求格式无效"}[self.code])


def native_messages(messages):
    result = []
    for message in messages:
        if message.get("role") not in ("system", "user", "assistant"):
            raise OllamaVisionError("INVALID_INPUT")
        content, images = message.get("content"), []
        if isinstance(content, list):
            texts = []
            for item in content:
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    texts.append(item["text"])
                elif item.get("type") == "image_url":
                    url = (item.get("image_url") or {}).get("url", "")
                    if not isinstance(url, str) or not url.startswith(("data:image/jpeg;base64,", "data:image/png;base64,")):
                        raise OllamaVisionError("INVALID_INPUT")
                    encoded = url.split(",", 1)[1]
                    try:
                        if len(encoded) > 24_000_000 or not base64.b64decode(encoded, validate=True):
                            raise ValueError()
                    except ValueError:
                        raise OllamaVisionError("INVALID_INPUT") from None
                    images.append(encoded)
                else:
                    raise OllamaVisionError("INVALID_INPUT")
            content = "\n".join(texts)
        if not isinstance(content, str):
            raise OllamaVisionError("INVALID_INPUT")
        row = {"role": message["role"], "content": content}
        if images:
            row["images"] = images
        result.append(row)
    return result


class OllamaVisionClient:
    def __init__(self, guard, model=MODEL):
        if not callable(guard) or model not in ALLOWED_MODELS:
            raise OllamaVisionError()
        self.model = model
        self.guard = guard
        self.metrics = {"model_requests": 0, "model_failed_requests": 0, "model_seconds": 0.,
                        "prompt_tokens": 0, "completion_tokens": 0, "returned_model": model}

    def complete(self, messages):
        body = {"model": self.model, "messages": native_messages(messages), "stream": False,
                "format": "json", "think": False, "keep_alive": "2m",
                "options": {"num_ctx": 16384, "num_predict": 4096, "temperature": 0}}
        # A local URL alone is insufficient: the server must be app-owned with
        # cloud disabled and the pinned local model still present.
        self.guard()
        started = perf_counter()
        self.metrics["model_requests"] += 1
        try:
            with requests.Session() as session:
                session.trust_env = False
                with session.post(BASE_URL + "/api/chat", json=body, timeout=(3, 180),
                                  allow_redirects=False, stream=True) as response:
                    if response.status_code != 200:
                        raise OllamaVisionError()
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise OllamaVisionError("INVALID_RESPONSE")
                        chunks.append(chunk)
            result = json.loads(b"".join(chunks))
            if result.get("done") is not True or result.get("done_reason") != "stop":
                raise OllamaVisionError("INCOMPLETE")
            if result.get("model") != self.model:
                raise OllamaVisionError("INVALID_RESPONSE")
            action = json.loads(result["message"]["content"])
            if not isinstance(action, dict):
                raise OllamaVisionError("INVALID_RESPONSE")
            for source, dest in (("prompt_eval_count", "prompt_tokens"), ("eval_count", "completion_tokens")):
                value = result.get(source)
                if type(value) is int and 0 <= value <= 1_000_000_000:
                    self.metrics[dest] += value
            return action
        except OllamaVisionError:
            self.metrics["model_failed_requests"] += 1
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            self.metrics["model_failed_requests"] += 1
            raise OllamaVisionError("INVALID_RESPONSE") from None
        except Exception:
            self.metrics["model_failed_requests"] += 1
            raise OllamaVisionError() from None
        finally:
            self.metrics["model_seconds"] += perf_counter() - started
