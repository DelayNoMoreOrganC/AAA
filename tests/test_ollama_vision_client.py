"""Synthetic transport checks: no real model, documents or external requests."""
import json
import pytest
import ollama_vision_client as local


def wire(monkeypatch, *, status=200, data=None, chunks=None):
    seen=[]
    class Response:
        status_code=status
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def iter_content(self, n):
            yield from chunks if chunks is not None else [json.dumps(data or {"model":local.MODEL,"done":True,"done_reason":"stop","message":{"content":'{"ok":true}'}}).encode()]
    class Session:
        trust_env=True
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,**kw):
            seen.append({"url":url,"trust_env":self.trust_env,**kw})
            return Response()
    monkeypatch.setattr(local.requests,"Session",Session)
    return seen


def test_local_native_image_json_and_guard_every_call(monkeypatch):
    seen=wire(monkeypatch)
    guards=[]
    client=local.OllamaVisionClient(lambda:guards.append(True))
    msg=[{"role":"user","content":[{"type":"text","text":"source A"},{"type":"image_url","image_url":{"url":"data:image/png;base64,c3ludGhldGlj"}}]}]
    assert client.complete(msg)=={"ok":True}
    assert client.complete(msg)=={"ok":True}
    assert guards==[True,True]
    assert len(seen)==2 and all(r["url"]=="http://127.0.0.1:11435/api/chat" for r in seen)
    assert seen[0]["trust_env"] is False and seen[0]["allow_redirects"] is False
    assert "headers" not in seen[0]
    assert seen[0]["json"]["messages"]==[{"role":"user","content":"source A","images":["c3ludGhldGlj"]}]
    assert seen[0]["json"]["options"]["num_ctx"]==16384


@pytest.mark.parametrize("url",["https://example.com/a.png","file:///private.png","data:image/svg+xml;base64,eA==","data:image/png;base64,%%%"])
def test_no_remote_images_or_invalid_inline_data(monkeypatch,url):
    seen=wire(monkeypatch)
    with pytest.raises(local.OllamaVisionError):
        local.OllamaVisionClient(lambda:None).complete([{"role":"user","content":[{"type":"image_url","image_url":{"url":url}}]}])
    assert seen==[]


def test_unowned_engine_guard_stops_before_material_transmission(monkeypatch):
    seen=wire(monkeypatch)
    def deny(): raise RuntimeError("ownership failed")
    with pytest.raises(RuntimeError):local.OllamaVisionClient(deny).complete([])
    assert seen==[]


@pytest.mark.parametrize("status",[301,302,307,401,500])
def test_error_no_retry_no_body_disclosure(monkeypatch,status):
    seen=wire(monkeypatch,status=status,data={"error":"PRIVATE_BODY"})
    with pytest.raises(local.OllamaVisionError) as caught:local.OllamaVisionClient(lambda:None).complete([])
    assert "PRIVATE_BODY" not in str(caught.value) and len(seen)==1


@pytest.mark.parametrize("data",[
    {"model":local.MODEL,"done":False},
    {"model":local.MODEL,"done":True,"done_reason":"length"},
    {"model":"other-cloud","done":True,"done_reason":"stop","message":{"content":"{}"}},
    {"model":local.MODEL,"done":True,"done_reason":"stop","message":{"content":"[]"}},
    {"model":local.MODEL,"done":True,"done_reason":"stop","message":{"content":"PRIVATE_BODY"}},
])
def test_incomplete_or_wrong_model_cannot_succeed(monkeypatch,data):
    seen=wire(monkeypatch,data=data)
    with pytest.raises(local.OllamaVisionError) as caught:local.OllamaVisionClient(lambda:None).complete([])
    assert "PRIVATE_BODY" not in str(caught.value) and len(seen)==1


def test_bounded_response(monkeypatch):
    wire(monkeypatch,chunks=[b"x"*(local.MAX_RESPONSE_BYTES+1)])
    with pytest.raises(local.OllamaVisionError):local.OllamaVisionClient(lambda:None).complete([])
