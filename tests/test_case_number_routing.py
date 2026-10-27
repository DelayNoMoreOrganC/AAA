"""Fictional cases: source-bound numbers remain separate across all agents."""
from copy import deepcopy

import pytest

from fact_evidence import validate_fact, validated_fact_field
from form_drafts import derive_form_drafts
import visual_archive_agent as visual
import workstation_agent as local
from tests.test_visual_document_workflow import CONFIG, classified, extracted, mock_client, offline_only, pdf
from tests.test_visual_archive_agent import CFG, batch_context, record, scripted_client


TRIAL = "（2026）粤0999行初2001号"
EXECUTION = "（2026）粤0999执3001号"
TRIAL_TEXT = "行政判决书\n" + TRIAL + "\n本院判决如下：撤销处罚决定。"
EXECUTION_TEXT = "执行通知书\n" + EXECUTION + "\n执行依据：" + TRIAL + "行政判决书。"


@pytest.mark.parametrize("field,value,quote,page,target", [
    ("案号", TRIAL, TRIAL, TRIAL_TEXT, "案号"),
    ("案号", EXECUTION, EXECUTION, EXECUTION_TEXT, "执行案号"),
    ("执行案号", EXECUTION, EXECUTION, EXECUTION_TEXT, "执行案号"),
    ("案号", TRIAL, TRIAL, "委托合同。法院案号：" + TRIAL + "。", "案号"),
    ("执行案号", EXECUTION, EXECUTION, "本案执行案号：" + EXECUTION + "。", "执行案号"),
    ("执行案号", TRIAL, TRIAL, TRIAL_TEXT, None),
    ("案号", TRIAL, TRIAL, EXECUTION_TEXT, None),
    ("案号", EXECUTION, EXECUTION, "证据清单。正文引用" + EXECUTION + "裁定书。", None),
    ("案号", EXECUTION, EXECUTION, "参考案例。执行通知书\n" + EXECUTION, None),
    ("执行案号", EXECUTION, EXECUTION, "执行依据：" + EXECUTION, None),
    ("案号", "（2026）粤0999执保9号", "（2026）粤0999执保9号", "财产保全裁定书\n（2026）粤0999执保9号", None),
    ("案号", EXECUTION, EXECUTION, TRIAL_TEXT, None),
])
def test_number_routing_requires_own_document_number_and_procedure(field, value, quote, page, target):
    assert validated_fact_field(field, value, quote, page) == target


def facts(trial_key, execution_key):
    return [{"field": "案号", "value": value, "page_id": key, "quote": value}
            for value, key in [(TRIAL, trial_key), (EXECUTION, execution_key)]]


def assert_separate(fields, metadata):
    assert fields["案号"] == TRIAL
    assert fields["执行案号"] == EXECUTION
    assert metadata["_field_conflicts"] == []
    for field, value in [("案号", TRIAL), ("执行案号", EXECUTION)]:
        refs = metadata["_provenance"][field]
        assert len(refs) == 1 and refs[0]["value"] == value and refs[0]["quote"] == value


def test_local_agent_routes_before_conflict_detection(monkeypatch):
    responses = iter([
        {"tool": "read_pages", "page_ids": ["f1p1c1", "f1p2c1"]},
        {"tool": "record_fields", "facts": facts("f1p1c1", "f1p2c1")},
    ])
    monkeypatch.setattr(local, "request_tool", lambda *_: next(responses))
    fields, metadata = local.extract_with_agent({"synthetic.pdf": [TRIAL_TEXT, EXECUTION_TEXT]}, {}, log=lambda _: None)
    assert_separate(fields, metadata)
    assert metadata["_provenance"]["案号"][0]["page"] == 1
    assert metadata["_provenance"]["执行案号"][0]["page"] == 2


def test_deepseek_two_stage_routes_without_losing_duplicate_or_source_audit(tmp_path, monkeypatch):
    source = pdf(tmp_path, 2, texts=[TRIAL_TEXT, EXECUTION_TEXT])
    def respond(ctx, *_):
        if ctx["phase"] == "classification":
            return classified(ctx, kind="evidence", starts=("f1p2",))
        values = facts("f1p1", "f1p2")
        chosen = values[0 if ctx["document_id"] == "d1" else 1]
        return extracted(ctx, [chosen, dict(chosen)])
    client = mock_client(monkeypatch, respond)
    units, fields, metadata, _ = visual.analyze_visual_sources([source], "admin", deepcopy(CONFIG), log=lambda _: None)
    assert_separate(fields, metadata)
    assert len(units) == 2 and client.metrics["model_requests"] == 3
    assert metadata["_agent_summary"]["this_run_metrics"]["duplicate_fact_candidates"] == 2
    assert metadata["_provenance"]["执行案号"][0]["page"] == 2


def test_glm_visual_agent_uses_the_same_validated_storage_keys(tmp_path, monkeypatch):
    source = pdf(tmp_path, 2, texts=[TRIAL_TEXT, EXECUTION_TEXT])
    scripted_client(monkeypatch, lambda messages, _: record(batch_context(messages), kind="judgment",
                      starts=("f1p2",), facts=facts("f1p1", "f1p2")))
    _, fields, metadata, _ = visual.analyze_visual_sources([source], "admin", deepcopy(CFG), log=lambda _: None)
    assert_separate(fields, metadata)


def test_same_procedure_distinct_numbers_still_conflict(monkeypatch):
    other = "（2026）粤0999行初2002号"
    pages = ["案号：" + TRIAL, "案号：" + other]
    responses = iter([
        {"tool": "read_pages", "page_ids": ["f1p1c1", "f1p2c1"]},
        {"tool": "record_fields", "facts": [
            {"field": "案号", "value": val, "page_id": f"f1p{i+1}c1", "quote": pages[i]}
            for i, val in enumerate([TRIAL, other])]},
    ])
    monkeypatch.setattr(local, "request_tool", lambda *_: next(responses))
    fields, metadata = local.extract_with_agent({"synthetic.pdf": pages}, {}, log=lambda _: None)
    assert fields == {"案号": TRIAL}
    assert metadata["_field_conflicts"][0]["values"] == [TRIAL, other]


def test_explicit_project_field_survives_real_draft_builder_and_manual_blank(monkeypatch):
    name = "虚构星桥采购合同审查项目"
    quote = "项目名称：" + name
    responses = iter([
        {"tool": "read_pages", "page_ids": ["f1p1c1"]},
        {"tool": "record_fields", "facts": [{"field": "案件或项目名称", "value": name, "page_id": "f1p1c1", "quote": quote}]},
    ])
    monkeypatch.setattr(local, "request_tool", lambda *_: next(responses))
    fields, metadata = local.extract_with_agent({"synthetic.pdf": [quote]}, {}, log=lambda _: None)
    source = {**fields, **metadata}
    kwargs = {"source_manifest": [{"path": "synthetic.pdf", "pages": 1}]}
    result = derive_form_drafts(source, [], **kwargs)
    assert result["案件或项目名称"] == name
    assert result["_provenance"]["案件或项目名称"] == metadata["_provenance"]["案件或项目名称"]
    human = derive_form_drafts(source, [], manual_fields={"案件或项目名称": ""}, **kwargs)
    assert human["案件或项目名称"] == ""
