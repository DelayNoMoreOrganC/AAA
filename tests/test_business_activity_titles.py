"""Synthetic business-title boundaries; no model, OCR, template or service IO.

The principal title/body follows the frozen nonlit fixture. Catalog assertions
refer to existing business slots, not a new or legally mandatory document list.
"""
from copy import deepcopy
from pathlib import Path

import pytest

import archive_catalog as catalog
from document_title_review import review_visual_titles, title_evidence
import visual_archive_agent as agent
from tests.test_visual_document_workflow import (
    CONFIG, classified, context, coverage, extracted, mock_client, offline_only, pdf,
)


TITLE = "办理法律事务活动记录"
BODY = (
    "项目名称：虚构星桥采购合同审查项目。委托人：虚构星桥商贸有限公司。\n"
    "承办律师：虚构明序律师事务所接受本项目委托后指派的虚构律师丁。\n"
    "办理结果：2026年9月12日完成采购合同草案审查，并向委托人发出法律意见书和合同修改稿。\n"
    "本记录未附委托人签收回执；采购合同最终签订情况及律师费收款情况未记载。"
)


@pytest.mark.parametrize("case_type,kind,slot", [("nonlit", "legal_work", 7), ("counsel", "work_record", 5)])
@pytest.mark.parametrize("title", [TITLE, "办理具体法律事务活动记录", "办理具体法律事务活动的记录"])
def test_standalone_activity_record_uses_selected_business_slot(case_type, kind, slot, title):
    evidence = title_evidence(title + "\n" + BODY, case_type=case_type)
    assert evidence and evidence["verified"]
    assert evidence["doc_type"] == kind
    assert evidence["procedure_stage"] == "other"
    assert evidence["reason_code"] == "business_document_context_verified"
    assert [item.seq for item in catalog.get_catalog(case_type) if item.manual_key == kind] == [slot]


@pytest.mark.parametrize("case_type", ["nonlit", "counsel"])
@pytest.mark.parametrize("text", [
    "证据目录\n" + TITLE + "\n" + BODY,
    "附件清单\n" + TITLE + "\n" + BODY,
    "材料目录\n1. " + TITLE + "\n" + BODY,
    "《" + TITLE + "》\n" + BODY,
    "关于《" + TITLE + "》的说明\n" + BODY,
    "律师函\n本函提及《" + TITLE + "》，用于核对办理项目。\n" + BODY,
    "法律服务合同\n受托人为虚构明序律师事务所。\n" + TITLE + "\n" + BODY,
])
def test_reference_list_or_other_document_body_cannot_promote_activity_record(case_type, text):
    evidence = title_evidence(text, case_type=case_type)
    assert evidence is None or evidence["doc_type"] not in ("legal_work", "work_record")


@pytest.mark.parametrize("case_type", ["nonlit", "counsel"])
@pytest.mark.parametrize("body", ["", "本页仅有日期、编号、收件人，没有具体业务内容。"])
def test_activity_heading_without_lawyer_business_context_stays_unverified(case_type, body):
    evidence = title_evidence(TITLE + "\n" + body, case_type=case_type)
    assert evidence is None or (not evidence["verified"] and evidence["doc_type"] == "unknown")


@pytest.mark.parametrize("case_type", [None, "civil", "admin", "criminal"])
def test_activity_title_does_not_create_a_global_civil_or_other_business_fallback(case_type):
    assert title_evidence(TITLE + "\n" + BODY, case_type=case_type) is None


@pytest.mark.parametrize("case_type,wrong_kind,expected", [
    ("nonlit", "work_record", "legal_work"),
    ("counsel", "legal_work", "work_record"),
])
def test_local_title_correction_preserves_source_pages_and_continuation(case_type, wrong_kind, expected):
    class Pages:
        pages = {"p1": ("fictional-activity.pdf", 0), "p2": ("fictional-activity.pdf", 1)}
        def __init__(self):
            self.reads = []
        def read(self, key):
            self.reads.append(key)
            return TITLE + "\n" + BODY if key == "p1" else "记录续页：未附签收回执，不说明实际付款。"

    pages = Pages()
    rows = [{"page_id": key, "document_start": key == "p1", "doc_type": wrong_kind,
             "confidence": .9, "document_role": "standard", "procedure_stage": "other", "title": TITLE}
            for key in pages.pages]
    before = deepcopy(rows)
    result, audit = review_visual_titles(rows, pages, case_type=case_type, max_new_reads=2)
    assert rows == before
    assert [row["page_id"] for row in result] == ["p1", "p2"]
    assert [row["doc_type"] for row in result] == [expected, expected]
    assert [row["document_start"] for row in result] == [True, False]
    assert pages.reads == ["p1", "p2"]
    assert pages.title_review_metrics["new_page_reads"] == 2
    assert audit[0]["source_path"] == "fictional-activity.pdf" and audit[0]["page"] == 1
    assert audit[0]["independent_title_verified"] is True
    assert "未附签收" not in str(audit)
    assert not any(key in audit[0] for key in ("signed", "paid", "delivered", "facts"))


def test_original_title_split_across_lines_remains_a_leading_heading():
    evidence = title_evidence("虚构明序律师事务所\n办理法律事务\n活动记录\n" + BODY, case_type="nonlit")
    assert evidence and evidence["doc_type"] == "legal_work" and evidence["verified"]


@pytest.mark.parametrize("model_kind", ["work_record", "legal_work"])
def test_frozen_nonlit_wording_corrects_scripted_cross_business_candidate_without_retry(
    tmp_path, monkeypatch, model_kind,
):
    # Transcription of frozen nonlit_mixed/04 material, plus an explicitly
    # constructed continuation. V8 retained its final work_record/slot-5 unit,
    # not raw model actions: this scripted candidate is not a response replay.
    source = pdf(tmp_path, 2, texts=[
        TITLE + "\n" + BODY + "\n记录日期：2026年9月12日。",
        "记录续页：本页为测试续页。未附签收回执，不说明实际付款。",
    ])
    original = Path(source.path).read_bytes()

    def respond(ctx, *_):
        if ctx["phase"] == "classification":
            action = classified(ctx, kind=model_kind, stage="other")
            action["pages"][0]["title"] = TITLE
            return action
        # Both the wrong-type candidate and correct-type control must reach
        # extraction with the local title's business-correct type.
        assert ctx["doc_type"] == "legal_work"
        return extracted(ctx)

    client = mock_client(monkeypatch, respond)
    config = deepcopy(CONFIG)
    config["vision"]["title_review_budget"] = 2
    units, fields, metadata, _ = agent.analyze_visual_sources(
        [source], "nonlit", config, log=lambda _: None,
    )
    assert [(u.doc_type, u.catalog_seq, u.start_page, u.end_page) for u in units] == [
        ("legal_work", 7, 0, 1),
    ]
    assert dict(coverage(units)) == {(source.path, 0): 1, (source.path, 1): 1}
    assert [context(messages)["phase"] for messages in client.messages] == ["classification", "fields"]
    metrics = metadata["_agent_summary"]["this_run_metrics"]
    assert client.metrics["model_requests"] == metrics["model_requests"] == 2
    assert metrics["model_failed_requests"] == metrics["ocr_pages"] == 0
    assert metrics["classification_requests"] == metrics["field_requests"] == 1
    assert metrics["targeted_fact_review"]["requests"] == 0
    assert metrics["validation_failures"] == {"classification": {}, "fields": {}}
    assert metrics["title_review"]["new_page_reads"] == 2
    if model_kind == "work_record":
        assert any(item["visual_doc_type"] == "work_record"
                   and item["effective_doc_type"] == "legal_work"
                   and item["independent_title_verified"]
                   and item["reason_code"] == "business_document_context_verified"
                   for item in metadata["_visual_classification_review"])
    # Classification is not proof of completion, signature, receipt or payment.
    assert fields == {} and metadata["_provenance"] == {}
    assert metadata["_agent_summary"]["accepted_fact_count"] == 0
    assert Path(source.path).read_bytes() == original
