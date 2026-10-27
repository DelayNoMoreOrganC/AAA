"""Synthetic PDFs and scripted responses only; no live model or speed claims."""
from collections import Counter
from copy import deepcopy
import json
import subprocess

import fitz
import pytest
import requests

from document_segmenter import DocumentSource
from page_classifier import collect_low_confidence_units
import visual_archive_agent as agent


CFG = {"privacy": {"mode": "cloud", "cloud_authorized": True},
       "vision": {"provider": "zhipu", "model": agent.MODEL, "api_key": "synthetic-test-key"}}


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("This synthetic test must not access a network or launch a process")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(agent, "create_local_engine", forbidden)


def synthetic_pdf(tmp_path, count=1, *, name="synthetic.pdf", texts=None):
    path = tmp_path / name
    with fitz.open() as pdf:
        for number in range(count):
            page = pdf.new_page(width=360, height=480)
            text = texts[number] if texts is not None else f"Fictional evidence page {number + 1}. No actual client data."
            page.insert_textbox(fitz.Rect(30, 30, 330, 450), text, fontname="china-s", fontsize=11)
        pdf.save(path)
    return DocumentSource(str(path), "default")


def batch_context(messages):
    return json.loads(messages[1]["content"][0]["text"])


def record(context, *, kind="evidence", confidence=0.95, starts=(), facts=()):
    keys = context["本批页面"]
    return {"tool": "record_batch", "pages": [
        {"page_id": key, "doc_type": kind, "confidence": confidence,
         "document_start": (index == 0 and context["上一页判断"] is None) or key in starts}
        for index, key in enumerate(keys)], "facts": list(facts)}


def scripted_client(monkeypatch, respond, *, provider="zhipu"):
    class Client:
        def __init__(self):
            self.messages = []
            self.constructor_keys = []
            self.metrics = {"model_requests": 0, "model_failed_requests": 0,
                            "model_seconds": 0.0, "prompt_tokens": 0, "completion_tokens": 0}

        def complete(self, messages):
            self.messages.append(deepcopy(messages))
            self.metrics["model_requests"] += 1
            try:
                return respond(messages, len(self.messages))
            except Exception:
                self.metrics["model_failed_requests"] += 1
                raise

    client = Client()
    def construct(key):
        client.constructor_keys.append(key)
        return client
    name = "DeepSeekVisionClient" if provider == "deepseek" else "GlmVisionClient"
    monkeypatch.setattr(agent, name, construct)
    return client


def covered_pages(units):
    return Counter((unit.source_path, page) for unit in units
                   for page in range(unit.start_page, unit.end_page + 1))


@pytest.mark.parametrize("provider,model,other_client", [
    ("zhipu", agent.MODEL, "DeepSeekVisionClient"),
    ("deepseek", "deepseek-flash", "GlmVisionClient"),
])
def test_visual_provider_routes_once_and_metadata_records_selected_model(tmp_path, monkeypatch, provider, model, other_client):
    source = synthetic_pdf(tmp_path, 7, texts=["委托人：虚构星河公司"] * 7)
    original_bytes = (tmp_path / "synthetic.pdf").read_bytes()
    config = deepcopy(CFG)
    config["vision"].update(provider=provider, model=model)
    def forbidden(*args, **kwargs):
        pytest.fail("Only the explicitly selected provider may be constructed")
    monkeypatch.setattr(agent, other_client, forbidden)
    def respond(messages, call):
        facts = ([{"field": "委托人", "value": "虚构星河公司", "page_id": "f1p1",
                   "quote": "委托人：虚构星河公司"}] if call == 1 else [])
        return record(batch_context(messages), facts=facts)
    client = scripted_client(monkeypatch, respond, provider=provider)
    units, fields, metadata, _ = agent.analyze_visual_sources([source], "civil", config, log=lambda _: None)
    assert client.constructor_keys == ["synthetic-test-key"]
    assert client.metrics["model_requests"] == 2
    assert covered_pages(units) == Counter((source.path, page) for page in range(7))
    assert (units[0].start_page, units[0].end_page) == (0, 6)
    assert batch_context(client.messages[1])["上一页判断"]["page_id"] == "f1p6"
    assert fields == {"委托人": "虚构星河公司"}
    summary = metadata["_agent_summary"]
    assert summary["provider"] == provider and summary["model"] == model
    assert summary["local"] is False and summary["visual"] is True
    assert summary["source_pages_checked"] == 7 and summary["accepted_fact_count"] == 1
    assert summary["this_run_metrics"]["model_requests"] == 2
    assert "synthetic-test-key" not in json.dumps(metadata, ensure_ascii=False)
    assert (tmp_path / "synthetic.pdf").read_bytes() == original_bytes


@pytest.mark.parametrize("provider,model", [
    ("deepseek", agent.MODEL),
    ("zhipu", "deepseek-flash"),
    ("deepseek", "deepseek-chat"),
    ("deepseek", None),
    (None, "deepseek-flash"),
    ("untrusted-provider", "deepseek-flash"),
])
def test_provider_model_mismatch_is_rejected_before_read_or_send(monkeypatch, provider, model):
    def forbidden(*args, **kwargs):
        pytest.fail("An invalid provider/model pair must not read files or create any client")
    monkeypatch.setattr(agent, "CasePages", forbidden)
    monkeypatch.setattr(agent, "GlmVisionClient", forbidden)
    monkeypatch.setattr(agent, "DeepSeekVisionClient", forbidden)
    config = deepcopy(CFG)
    config["vision"].update(provider=provider, model=model)
    with pytest.raises(agent.GlmVisionError, match="视觉服务配置无效"):
        agent.analyze_visual_sources([], "civil", config)


def test_deepseek_failure_never_falls_back_to_another_provider(tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path)
    config = deepcopy(CFG)
    config["vision"].update(provider="deepseek", model="deepseek-flash")
    def forbidden(*args, **kwargs):
        pytest.fail("A provider failure must not send materials to another provider")
    monkeypatch.setattr(agent, "GlmVisionClient", forbidden)
    class SyntheticProviderFailure(RuntimeError):
        pass
    def fail(*args):
        raise SyntheticProviderFailure("synthetic provider failure")
    client = scripted_client(monkeypatch, fail, provider="deepseek")
    with pytest.raises(SyntheticProviderFailure):
        agent.analyze_visual_sources([source], "civil", config, log=lambda _: None)
    assert client.metrics["model_requests"] == 1
    assert client.constructor_keys == ["synthetic-test-key"]


def test_deepseek_invalid_json_recovers_with_fixed_correction_and_no_response_echo(tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path, 7)
    config = deepcopy(CFG)
    config["vision"].update(provider="deepseek", model="deepseek-flash")
    monkeypatch.setattr(agent, "GlmVisionClient", lambda *_: pytest.fail("No provider fallback is allowed"))
    private_response = "SYNTHETIC_PRIVATE_INVALID_RESPONSE"
    def respond(messages, call):
        if call == 1:
            raise agent.DeepSeekVisionError("INVALID_RESPONSE") from ValueError(private_response)
        return record(batch_context(messages))
    client = scripted_client(monkeypatch, respond, provider="deepseek")
    logs = []
    units, fields, metadata, _ = agent.analyze_visual_sources([source], "civil", config, log=logs.append)
    assert covered_pages(units) == Counter((source.path, page) for page in range(7))
    assert fields == {} and len(units) == 1
    assert client.constructor_keys == ["synthetic-test-key"]
    assert client.metrics["model_requests"] == 3
    assert client.metrics["model_failed_requests"] == 1
    assert client.messages[1][2:] == [{"role": "user", "content":
        "返回格式无效。请仅返回一个有效的JSON操作对象，不要使用Markdown代码块或附加说明。"}]
    assert len(client.messages[2]) == 2  # The next batch starts with fresh context.
    assert metadata["_agent_summary"]["this_run_metrics"]["model_failed_requests"] == 1
    assert len(metadata["_agent_events"]) == 2
    assert private_response not in json.dumps([client.messages, metadata, logs], ensure_ascii=False)


@pytest.mark.parametrize("first_four_invalid_tools", [False, True])
def test_deepseek_json_errors_share_the_existing_five_operation_limit(tmp_path, monkeypatch, first_four_invalid_tools):
    source = synthetic_pdf(tmp_path)
    config = deepcopy(CFG)
    config["vision"].update(provider="deepseek", model="deepseek-flash")
    monkeypatch.setattr(agent, "GlmVisionClient", lambda *_: pytest.fail("No provider fallback is allowed"))
    def respond(messages, call):
        if first_four_invalid_tools and call <= 4:
            return {"tool": "unauthorized_tool"}
        raise agent.DeepSeekVisionError("INVALID_RESPONSE")
    client = scripted_client(monkeypatch, respond, provider="deepseek")
    with pytest.raises(agent.GlmVisionError, match="操作上限"):
        agent.analyze_visual_sources([source], "civil", config, log=lambda _: None)
    assert client.metrics["model_requests"] == 5
    assert client.metrics["model_failed_requests"] == (1 if first_four_invalid_tools else 5)
    assert client.constructor_keys == ["synthetic-test-key"]


@pytest.mark.parametrize("code", ["AUTH_FAILED", "QUOTA_EXHAUSTED", "CONNECTION_FAILED", "RATE_LIMITED",
                                  "HTTP_FAILED", "INCOMPLETE", "RESPONSE_TOO_LARGE"])
def test_deepseek_other_provider_errors_propagate_without_retry(tmp_path, monkeypatch, code):
    source = synthetic_pdf(tmp_path)
    config = deepcopy(CFG)
    config["vision"].update(provider="deepseek", model="deepseek-flash")
    monkeypatch.setattr(agent, "GlmVisionClient", lambda *_: pytest.fail("No provider fallback is allowed"))
    error = agent.DeepSeekVisionError(code)
    def fail(*args):
        raise error
    client = scripted_client(monkeypatch, fail, provider="deepseek")
    with pytest.raises(agent.DeepSeekVisionError) as caught:
        agent.analyze_visual_sources([source], "civil", config, log=lambda _: None)
    assert caught.value is error
    assert client.metrics["model_requests"] == client.metrics["model_failed_requests"] == 1


@pytest.mark.parametrize("error", [agent.GlmVisionError("Synthetic invalid JSON"),
                                  agent.DeepSeekVisionError("INVALID_RESPONSE")])
def test_glm_errors_do_not_use_deepseek_format_correction(tmp_path, monkeypatch, error):
    source = synthetic_pdf(tmp_path)
    monkeypatch.setattr(agent, "DeepSeekVisionClient", lambda *_: pytest.fail("No provider fallback is allowed"))
    def fail(*args):
        raise error
    client = scripted_client(monkeypatch, fail)
    with pytest.raises(type(error)) as caught:
        agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert caught.value is error
    assert client.metrics["model_requests"] == client.metrics["model_failed_requests"] == 1


@pytest.mark.parametrize("provider,model", [("zhipu", agent.MODEL), ("deepseek", "deepseek-flash")])
def test_request_guard_stops_next_send_without_model_error_retry(tmp_path, monkeypatch, provider, model):
    source = synthetic_pdf(tmp_path, 7)
    config = deepcopy(CFG)
    config["vision"].update(provider=provider, model=model)
    client = scripted_client(monkeypatch, lambda messages, _: record(batch_context(messages)), provider=provider)
    # Even if the guard raises the adapter's format-error type, its failure is
    # authority revocation, not a model response eligible for retry.
    revoked = agent.DeepSeekVisionError("INVALID_RESPONSE")
    guards = []
    def guard():
        guards.append(1)
        if client.metrics["model_requests"]:
            raise revoked
    config["privacy"]["request_guard"] = guard
    with pytest.raises(agent.DeepSeekVisionError) as caught:
        agent.analyze_visual_sources([source], "civil", config, log=lambda _: None)
    assert caught.value is revoked
    assert client.metrics["model_requests"] == 1 and len(guards) == 2


def test_request_guard_must_be_internal_callable_not_json_value(monkeypatch):
    config = deepcopy(CFG)
    config["privacy"]["request_guard"] = {"allow": True}
    monkeypatch.setattr(agent, "CasePages", lambda *_: pytest.fail("Invalid authority hook must fail before reading"))
    with pytest.raises(agent.GlmVisionError, match="权限检查配置无效"):
        agent.analyze_visual_sources([], "civil", config)


def test_48_pages_use_eight_mock_requests_and_preserve_every_page_once(tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path, 48)
    original_bytes = (tmp_path / "synthetic.pdf").read_bytes()
    client = scripted_client(monkeypatch, lambda messages, _: record(batch_context(messages)))
    units, fields, metadata, texts = agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert client.metrics["model_requests"] == 8  # Algorithmic request count, not a timing benchmark.
    assert len(units) == 1 and (units[0].start_page, units[0].end_page) == (0, 47)
    assert covered_pages(units) == Counter((source.path, page) for page in range(48))
    assert fields == {} and texts[source.path] == [""] * 48
    summary = metadata["_agent_summary"]
    assert summary["pages_checked"] == summary["source_pages_checked"] == 48
    assert summary["this_run_metrics"]["model_requests"] == 8
    assert summary["this_run_metrics"]["ocr_pages"] == 0
    assert summary["this_run_metrics"]["images_rendered"] == 55  # Seven preceding-page contexts.
    for index, messages in enumerate(client.messages):
        context = batch_context(messages)
        assert context["本批页面"] == [f"f1p{page}" for page in range(index * 6 + 1, index * 6 + 7)]
        assert context["上一页判断"] is None if index == 0 else context["上一页判断"]["page_id"] == f"f1p{index * 6}"
        images = [item for item in messages[1]["content"] if item["type"] == "image_url"]
        assert len(images) == (6 if index == 0 else 7)
        assert all(item["image_url"]["url"].startswith("data:image/jpeg;base64,") for item in images)
    assert (tmp_path / "synthetic.pdf").read_bytes() == original_bytes


def test_cross_file_context_resets_and_same_type_new_document_remains_separate(tmp_path, monkeypatch):
    sources = [synthetic_pdf(tmp_path, 7, name="first.pdf"), synthetic_pdf(tmp_path, 7, name="second.pdf")]
    client = scripted_client(monkeypatch, lambda messages, _: record(batch_context(messages), starts=("f1p4",)))
    units, _, _, _ = agent.analyze_visual_sources(sources, "civil", deepcopy(CFG), log=lambda _: None)
    assert [(unit.source_path, unit.start_page, unit.end_page) for unit in units] == [
        (sources[0].path, 0, 2), (sources[0].path, 3, 6), (sources[1].path, 0, 6)]
    assert covered_pages(units) == Counter((source.path, page) for source in sources for page in range(7))
    assert len(client.messages) == 4
    assert batch_context(client.messages[2])["上一页判断"] is None
    assert batch_context(client.messages[3])["上一页判断"]["page_id"] == "f2p6"


@pytest.mark.parametrize("mutate", [
    lambda action: action["pages"].pop(),
    lambda action: action["pages"].__setitem__(1, dict(action["pages"][0])),
    lambda action: action["pages"][1].update(page_id="f1p999"),
    lambda action: action["pages"][0].update(document_start=False),
    lambda action: action["pages"][1].update(doc_type="contract", document_start=False),
    lambda action: action["pages"][0].update(confidence=float("nan")),
])
def test_incomplete_duplicate_or_invalid_page_decisions_never_commit(tmp_path, monkeypatch, mutate):
    source = synthetic_pdf(tmp_path, 2)
    def respond(messages, _):
        action = record(batch_context(messages))
        mutate(action)
        return action
    client = scripted_client(monkeypatch, respond)
    with pytest.raises(agent.GlmVisionError, match="操作上限"):
        agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert client.metrics["model_requests"] == 5


def test_previous_page_is_context_only_and_cannot_be_resubmitted(tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path, 7)
    def respond(messages, call):
        action = record(batch_context(messages))
        if call > 1:
            action["pages"][0]["page_id"] = "f1p6"
        return action
    client = scripted_client(monkeypatch, respond)
    with pytest.raises(agent.GlmVisionError, match="操作上限"):
        agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert len(client.messages) == 6


def test_inspecting_previous_page_keeps_context_only_pixel_label(tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path, 7)
    original_bytes = (tmp_path / "synthetic.pdf").read_bytes()
    headings = []
    original_draw_text = agent.ImageDraw.ImageDraw.text
    def capture_draw_text(self, position, text, *args, **kwargs):
        if text.startswith("SOURCE PAGE ID:"):
            headings.append(text)
        return original_draw_text(self, position, text, *args, **kwargs)
    monkeypatch.setattr(agent.ImageDraw.ImageDraw, "text", capture_draw_text)
    def respond(messages, call):
        if call == 2:
            return {"tool": "inspect_page", "page_id": "f1p6", "box": [0.1, 0.1, 0.9, 0.9]}
        return record(batch_context(messages))
    client = scripted_client(monkeypatch, respond)
    units, _, metadata, _ = agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert len(client.messages) == 3
    assert [heading for heading in headings if "f1p6 |" in heading] == [
        "SOURCE PAGE ID: f1p6 | TARGET",
        "SOURCE PAGE ID: f1p6 | CONTEXT ONLY",
        "SOURCE PAGE ID: f1p6 | CONTEXT ONLY",
    ]
    assert headings[-1] == "SOURCE PAGE ID: f1p6 | CONTEXT ONLY"
    assert headings.count("SOURCE PAGE ID: f1p7 | TARGET") == 1
    image = client.messages[-1][-1]["content"][1]
    assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert covered_pages(units) == Counter((source.path, page) for page in range(7))
    assert metadata["_agent_summary"]["this_run_metrics"]["images_rendered"] == 9
    assert (tmp_path / "synthetic.pdf").read_bytes() == original_bytes


def test_out_of_order_rows_are_committed_in_source_order(tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path, 3)
    def respond(messages, _):
        action = record(batch_context(messages), starts=("f1p3",))
        action["pages"].reverse()
        return action
    scripted_client(monkeypatch, respond)
    units, _, _, _ = agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert [(unit.start_page, unit.end_page) for unit in units] == [(0, 1), (2, 2)]
    assert covered_pages(units) == Counter((source.path, page) for page in range(3))


@pytest.mark.parametrize("different_file", [False, True])
def test_existing_page_outside_current_batch_and_previous_page_is_inaccessible(tmp_path, monkeypatch, different_file):
    sources = ([synthetic_pdf(tmp_path, 6, name="first.pdf"), synthetic_pdf(tmp_path, name="second.pdf")]
               if different_file else [synthetic_pdf(tmp_path, 7)])
    def respond(messages, call):
        if call == 1:
            return record(batch_context(messages))
        return {"tool": "read_text", "page_ids": ["f1p6" if different_file else "f1p1"]}
    client = scripted_client(monkeypatch, respond)
    def forbidden_read(*args):
        pytest.fail("A page outside the current allowed window must not be read")
    monkeypatch.setattr(agent.CasePages, "read", forbidden_read)
    with pytest.raises(agent.GlmVisionError, match="操作上限"):
        agent.analyze_visual_sources(sources, "civil", deepcopy(CFG), log=lambda _: None)
    assert len(client.messages) == 6


@pytest.mark.parametrize("action", [
    {"tool": "shell", "command": "PRIVATE_INSTRUCTION execute arbitrary command"},
    {"tool": "open_url", "url": "https://example.invalid/PRIVATE_INSTRUCTION"},
    {"tool": "read_file", "path": "C:/PRIVATE_INSTRUCTION.pdf"},
    {"tool": "read_text", "page_ids": ["C:/PRIVATE_INSTRUCTION.pdf"]},
    {"tool": "inspect_page", "page_id": "https://example.invalid/PRIVATE_INSTRUCTION"},
    {"tool": "read_text", "page_ids": ["f1p7"]},
    {"tool": "inspect_page", "page_id": "f2p1"},
])
def test_model_cannot_select_shell_url_file_or_unavailable_page(tmp_path, monkeypatch, action):
    source = synthetic_pdf(tmp_path, 7)
    client = scripted_client(monkeypatch, lambda *_: deepcopy(action))
    logs = []
    with pytest.raises(agent.GlmVisionError, match="操作上限") as error:
        agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=logs.append)
    assert len(client.messages) == 5
    assert "PRIVATE_INSTRUCTION" not in str(error.value) + "\n".join(logs)
    # Rejected action arguments are not echoed into model correction messages.
    corrections = [message["content"] for message in client.messages[-1][2:]]
    assert "PRIVATE_INSTRUCTION" not in json.dumps(corrections)


@pytest.mark.parametrize("box", [[-0.1, 0, 1, 1], [0, 0, 0, 1], [0, 0, float("inf"), 1],
                                  [False, 0, 1, 1], [0, 0, 1], "PRIVATE_CROP_ARGUMENT"])
def test_crop_coordinates_are_strictly_bounded(tmp_path, monkeypatch, box):
    source = synthetic_pdf(tmp_path)
    client = scripted_client(monkeypatch, lambda *_: {"tool": "inspect_page", "page_id": "f1p1", "box": box})
    with pytest.raises(agent.GlmVisionError, match="操作上限"):
        agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert len(client.messages) == 5


def test_inspection_and_local_text_are_limited_to_batch_and_preceding_page(tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path, 7)
    def respond(messages, call):
        if call == 1:
            return {"tool": "inspect_page", "page_id": "f1p1", "box": [0, 0, 0.5, 0.5]}
        if call == 2:
            return {"tool": "read_text", "page_ids": ["f1p2"]}
        if call == 4:
            return {"tool": "inspect_page", "page_id": "f1p6", "box": [0.1, 0.1, 0.9, 0.9]}
        if call == 5:
            return {"tool": "read_text", "page_ids": ["f1p6", "f1p7"]}
        return record(batch_context(messages))
    client = scripted_client(monkeypatch, respond)
    units, _, metadata, texts = agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert len(client.messages) == 6
    assert covered_pages(units) == Counter((source.path, page) for page in range(7))
    assert [index for index, text in enumerate(texts[source.path]) if text] == [1, 5, 6]
    assert metadata["_agent_summary"]["this_run_metrics"]["images_rendered"] == 10
    assert metadata["_agent_summary"]["this_run_metrics"]["ocr_pages"] == 0
    assert [event["tool"] for event in metadata["_agent_events"]] == [
        "inspect_page", "read_text", "record_batch", "inspect_page", "read_text", "record_batch"]


def test_visual_facts_must_pass_real_local_text_and_semantic_evidence(tmp_path, monkeypatch):
    text = ("委托代理合同\n委托人：虚构星河公司\n起诉日期：2026年3月3日\n"
            "样本行01：虚构无关记录\n被告承诺已支付10000元后提供凭证。")
    source = synthetic_pdf(tmp_path, texts=[text])
    facts = [
        {"field": "委托人", "value": "虚构星河公司", "page_id": "f1p1", "quote": "委托人：虚构星河公司"},
        {"field": "收案日期", "value": "2026年3月3日", "page_id": "f1p1", "quote": "起诉日期：2026年3月3日"},
        {"field": "律师事务所", "value": "虚构无关记录", "page_id": "f1p1", "quote": "样本行01：虚构无关记录"},
        {"field": "结案小结", "value": "已支付10000元", "page_id": "f1p1", "quote": "被告承诺已支付10000元后提供凭证"},
        {"field": "案号", "value": "编造案号", "page_id": "f1p1", "quote": "案号：编造案号"},
    ]
    scripted_client(monkeypatch, lambda messages, _: record(batch_context(messages), facts=facts))
    logs = []
    _, fields, metadata, texts = agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=logs.append)
    assert fields == {"委托人": "虚构星河公司"}
    assert metadata["_agent_summary"]["accepted_fact_count"] == 1
    assert metadata["_agent_summary"]["rejected_fact_count"] == 4
    assert metadata["_provenance"]["委托人"][0]["source_path"] == source.path
    assert metadata["_provenance"]["委托人"][0]["page"] == 1
    assert "委托人" in texts[source.path][0]
    for review in metadata["_fact_review"]:
        assert review["source_path"] == source.path and review["page"] == 1
        assert "value" not in review and "quote" not in review
    assert "虚构无关记录" not in str(metadata["_fact_review"])
    assert "虚构星河公司" not in "\n".join(logs)


def test_fact_from_context_page_cannot_be_recorded_twice(tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path, 7, texts=["委托人：虚构星河公司"] * 7)
    def respond(messages, call):
        facts = [] if call == 1 else [{"field": "委托人", "value": "虚构星河公司",
            "page_id": "f1p6", "quote": "委托人：虚构星河公司"}]
        return record(batch_context(messages), facts=facts)
    scripted_client(monkeypatch, respond)
    monkeypatch.setattr(agent.CasePages, "read", lambda *_: pytest.fail("Out-of-batch fact must be rejected before reading"))
    units, fields, metadata, _ = agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert fields == {} and metadata["_agent_summary"]["rejected_fact_count"] == 1
    assert covered_pages(units) == Counter((source.path, page) for page in range(7))


def test_requested_ocr_is_local_and_cached_for_subsequent_fact_validation(tmp_path, monkeypatch):
    # A blank synthetic PDF makes the local fallback necessary. OCR is scripted,
    # so this checks orchestration/cache behavior, not recognition accuracy.
    source = synthetic_pdf(tmp_path, texts=[""])
    ocr_calls = []
    def ocr(image_bytes):
        assert image_bytes.startswith(b"\x89PNG")
        ocr_calls.append(1)
        return [[[[0, 0], [100, 0], [100, 20], [0, 20]], "委托人：虚构星河公司", 0.99]], None
    monkeypatch.setattr(agent, "create_local_engine", lambda: ocr)
    def respond(messages, call):
        if call == 1:
            return {"tool": "read_text", "page_ids": ["f1p1"]}
        return record(batch_context(messages), facts=[{"field": "委托人", "value": "虚构星河公司",
            "page_id": "f1p1", "quote": "委托人：虚构星河公司"}])
    scripted_client(monkeypatch, respond)
    _, fields, metadata, texts = agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert fields == {"委托人": "虚构星河公司"}
    assert len(ocr_calls) == metadata["_agent_summary"]["this_run_metrics"]["ocr_pages"] == 1
    assert texts[source.path] == ["委托人：虚构星河公司"]


@pytest.mark.parametrize("empty", [False, True])
def test_only_read_page_receives_local_ocr_review_at_original_page_number(tmp_path, monkeypatch, empty):
    source = synthetic_pdf(tmp_path, 3, texts=["", "", ""])
    private_text = "虚构低置信正文不应复制到质检提示中"
    ocr_calls = []
    def ocr(image_bytes):
        assert image_bytes.startswith(b"\x89PNG")
        ocr_calls.append(1)
        rows = [] if empty else [[[[0, 0], [100, 0], [100, 20], [0, 20]], private_text, 0.2]]
        return rows, None
    monkeypatch.setattr(agent, "create_local_engine", lambda: ocr)
    def respond(messages, call):
        if call <= 2:
            return {"tool": "read_text", "page_ids": ["f1p2"]}
        return record(batch_context(messages))
    scripted_client(monkeypatch, respond)
    units, _, metadata, texts = agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert covered_pages(units) == Counter((source.path, page) for page in range(3))
    assert len(ocr_calls) == 1
    assert metadata["_agent_summary"]["this_run_metrics"]["ocr_pages"] == 1
    reviews = metadata["_ocr_review"]
    assert len(reviews) == 1  # Re-reading the cache must not duplicate the issue.
    assert reviews[0]["source_path"] == source.path and reviews[0]["page"] == 2
    assert ("empty_text" if empty else "low_confidence") in reviews[0]["reason_codes"]
    if not empty:
        assert reviews[0]["mean_confidence"] == 0.2
        assert len(reviews[0]['low_confidence_regions']) == 1
        assert reviews[0]['unlocated_low_confidence_blocks'] == 0
        assert reviews[0]['low_confidence_regions'][0]['box'][0:2] == [0,0]
    assert private_text not in str(reviews)
    assert texts[source.path][0] == texts[source.path][2] == ""


def test_local_evidence_failure_does_not_partially_commit_batch_or_facts(tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path, 2, texts=["委托人：虚构星河公司", "律师事务所：虚构山海律师事务所"])
    facts = [
        {"field": "委托人", "value": "虚构星河公司", "page_id": "f1p1", "quote": "委托人：虚构星河公司"},
        {"field": "律师事务所", "value": "虚构山海律师事务所", "page_id": "f1p2", "quote": "律师事务所：虚构山海律师事务所"},
    ]
    client = scripted_client(monkeypatch, lambda messages, _: record(batch_context(messages), facts=facts))
    original_read, failed = agent.CasePages.read, []
    def read(self, key):
        if key == "f1p2" and not failed:
            failed.append(key)
            raise ValueError("PRIVATE_LOCAL_RETRY_CONTENT")
        return original_read(self, key)
    monkeypatch.setattr(agent.CasePages, "read", read)
    units, fields, metadata, _ = agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert client.metrics["model_requests"] == 2
    assert covered_pages(units) == Counter((source.path, page) for page in range(2))
    assert fields == {"委托人": "虚构星河公司", "律师事务所": "虚构山海律师事务所"}
    assert metadata["_agent_summary"]["accepted_fact_count"] == 2
    assert all(len(items) == 1 for items in metadata["_provenance"].values())
    assert len([event for event in metadata["_agent_events"] if event["tool"] == "record_batch"]) == 1
    assert "PRIVATE_LOCAL_RETRY_CONTENT" not in str(client.messages[-1][2:])


@pytest.mark.parametrize("kind,confidence,expected", [("unknown", 0.99, 0.5), ("evidence", 0, 0), ("contract", 0.74, 0.74)])
def test_low_or_zero_confidence_remains_in_quality_review(tmp_path, monkeypatch, kind, confidence, expected):
    source = synthetic_pdf(tmp_path)
    scripted_client(monkeypatch, lambda messages, _: record(batch_context(messages), kind=kind, confidence=confidence))
    units, _, _, _ = agent.analyze_visual_sources([source], "civil", deepcopy(CFG), log=lambda _: None)
    assert units[0].confidence == expected
    reviews = collect_low_confidence_units(units)
    assert len(reviews) == 1 and reviews[0]["confidence"] == expected


@pytest.mark.parametrize("provider,model", [("zhipu", agent.MODEL), ("deepseek", "deepseek-flash")])
@pytest.mark.parametrize("privacy", [{"mode": "local", "cloud_authorized": True},
                                      {"mode": "cloud", "cloud_authorized": False},
                                      {"mode": "cloud", "cloud_authorized": "true"},
                                      {"mode": "cloud", "cloud_authorized": 1}, {}])
def test_cloud_authorization_is_required_before_reading_any_pdf(monkeypatch, privacy, provider, model):
    def forbidden(*args):
        pytest.fail("Unauthorized task must not read files or construct the provider client")
    monkeypatch.setattr(agent, "CasePages", forbidden)
    monkeypatch.setattr(agent, "GlmVisionClient", forbidden)
    monkeypatch.setattr(agent, "DeepSeekVisionClient", forbidden)
    config = deepcopy(CFG)
    config["privacy"] = privacy
    config["vision"].update(provider=provider, model=model)
    with pytest.raises(agent.GlmVisionError, match="尚未授权"):
        agent.analyze_visual_sources([], "civil", config)


def test_consultation_retains_unverified_date_order_warning(tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path)
    scripted_client(monkeypatch, lambda messages, _: record(batch_context(messages)))
    units, _, metadata, _ = agent.analyze_visual_sources([source], "consultation", deepcopy(CFG), log=lambda _: None)
    assert covered_pages(units) == Counter({(source.path, 0): 1})
    assert metadata["_document_order"]["status"] == "needs_review"
    assert metadata["_document_order"]["strategy"] == "original_pending_date_review"
