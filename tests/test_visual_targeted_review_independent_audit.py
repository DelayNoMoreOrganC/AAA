"""Independent, offline regressions for the new targeted-review boundaries."""
from types import SimpleNamespace

import visual_document_workflow as workflow
from pdf_doc_locator import DocumentUnit
from tests.test_visual_document_workflow import (classified, extracted, fact, mock_client,
                                                 offline_only, pdf, run)


def test_targeted_raw_field_cannot_conflict_with_already_accepted_canonical_field(tmp_path, monkeypatch):
    first_number = "（2026）粤0101执1001号"
    other_number = "（2026）粤0101执1002号"
    sources = [
        pdf(tmp_path, name="first.pdf", texts=[
            f"执行通知书\n{first_number}\n本院通知被执行人履行本案生效法律文书确定的义务。"]),
        pdf(tmp_path, name="second.pdf", texts=[
            f"执行通知书\n{other_number}\n普通记录：虚构错误案号。\n本院通知被执行人履行本案法律文书确定的义务。"]),
    ]

    def respond(ctx, messages, _):
        if ctx["phase"] == "classification":
            return classified(ctx, kind="execution", stage="enforcement")
        if ctx["document_id"] == "d1":
            return extracted(ctx, [fact("f1p1", first_number, "执行案号", first_number)])
        if len(messages) == 2:
            return extracted(ctx, [fact("f2p1", "虚构错误案号", "案号", "普通记录：虚构错误案号。")])
        # The wire key is the permitted unaccepted 案号, but local validation
        # resolves its value to the existing canonical 执行案号 field.
        return extracted(ctx, [fact("f2p1", other_number, "案号", other_number)])

    client = mock_client(monkeypatch, respond)
    _, fields, metadata, _ = run(sources)
    assert fields == {"执行案号": first_number}
    assert client.metrics["model_requests"] == 5
    assert not metadata["_field_conflicts"]
    assert len(metadata["_provenance"]["执行案号"]) == 1


def test_omission_target_does_not_treat_judgment_quoted_prayer_as_operative_anchor():
    text = "民事判决书\n原告诉称：请求法院判决如下：被告支付货款。\n本页仅为当事人诉请记录。"
    pages = SimpleNamespace(pages={"f1p1": ("synthetic.pdf", 0)},
                            texts={"synthetic.pdf": [text]}, read_pages={"f1p1"})
    unit = DocumentUnit(0, "judgment", 0, 0, "民事判决书", source_path="synthetic.pdf", confidence=.95)
    document = {"keys": ["f1p1"], "role": "standard", "stage": "trial"}
    assert workflow._outcome_omission_targets(unit, document, pages, {"f1p1"}, {}, set()) == []
