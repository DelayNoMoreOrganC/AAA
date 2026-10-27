"""Synthetic title-review evidence must reach forms without inventing service."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from document_title_review import review_visual_titles
from form_drafts import derive_form_drafts


PATH = "fictional-current-court.pdf"
MANIFEST = [{"path": PATH, "pages": 1, "file_id": "fictional-court"}]


def reviewed(text):
    pages = SimpleNamespace(pages={"p1": (PATH, 0)}, read=lambda _: text)
    rows, audit = review_visual_titles([{
        "page_id": "p1", "document_start": True, "doc_type": "unknown",
        "confidence": .9, "document_role": "unknown", "procedure_stage": "unknown", "title": "",
    }], pages)
    row = rows[0]
    unit = SimpleNamespace(doc_id=0, doc_type=row["doc_type"], title=row["title"],
        source_path=PATH, start_page=0, end_page=0, confidence=row["confidence"])
    return unit, {"_visual_classification_review": audit}


@pytest.mark.parametrize("title,body", [
    ("财产保全情况告知书", "本院已依法冻结被申请人的银行存款。"),
    ("保全情况告知书", "本院未发现可供保全的财产。"),
    ("财产保全告知书", "本案已解除此前采取的财产保全。"),
    ("民事裁定书", "裁定如下：冻结被申请人的银行存款。"),
    ("执行结案通知书", "本案已经执行完毕，现通知双方。"),
    ("执行案件结案通知书", "本院决定终结本次执行程序。"),
])
def test_current_independently_verified_court_document_enters_inventory(title, body):
    unit, fields = reviewed(f"虚构区人民法院\n{title}\n{body}")
    before = deepcopy(fields)
    out = derive_form_drafts(fields, [unit], source_manifest=MANIFEST)
    assert title in out.get("法院文件清单", "")
    assert out["_form_drafts"]["fields"]["法院文件清单"]["status"] == "generated"
    assert out["_form_draft_sources"]["法院文件清单"][0]["page"] == 1
    assert out["_form_draft_sources"]["法院文件清单"][0]["independent_title_verified"] is True
    assert "已送达" not in out["法院文件清单"]
    assert not out.get("结案小结") and not out.get("结案日期")
    assert fields == before


@pytest.mark.parametrize("change", ["absent", "source", "page", "type", "title", "method", "verified", "reason", "doc_id"])
def test_title_audit_must_match_current_unit_and_independent_review(change):
    unit, fields = reviewed("虚构区人民法院\n财产保全情况告知书\n本院已冻结被申请人的银行存款。")
    audit = fields["_visual_classification_review"][0]
    if change == "absent": fields["_visual_classification_review"] = []
    elif change == "source": audit["source_path"] = "another-case.pdf"
    elif change == "page": audit["page"] = 2
    elif change == "type": audit["effective_doc_type"] = "evidence"
    elif change == "title": audit["title"] = "执行结案通知书"
    elif change == "method": audit["method"] = "model_guess"
    elif change == "verified": audit["independent_title_verified"] = False
    elif change == "doc_id": audit["doc_id"] = 9
    else: audit["reason_code"] = "preservation_context_verified"
    out = derive_form_drafts(fields, [unit], source_manifest=MANIFEST)
    assert not out.get("法院文件清单")
    assert "classification_requires_review" in out["_form_drafts"]["fields"]["法院文件清单"]["reason_codes"]


@pytest.mark.parametrize("text", [
    "财产保全申请书\n申请人请求法院冻结被申请人银行存款。",
    "执行申请书\n申请执行人请求法院强制执行。",
    "律师工作报告\n收到《财产保全情况告知书》，本院已冻结银行存款。",
    "证据目录\n财产保全情况告知书\n虚构区人民法院\n本院已冻结银行存款。",
    "虚构区人民法院\n财产保全情况告知书\n另案材料摘录。本院已冻结银行存款。",
])
def test_application_work_report_reference_and_other_case_are_not_court_inventory(text):
    unit, fields = reviewed(text)
    out = derive_form_drafts(fields, [unit], source_manifest=MANIFEST)
    assert not out.get("法院文件清单")


def test_human_clear_wins_over_new_court_title_evidence():
    unit, fields = reviewed("虚构区人民法院\n执行结案通知书\n本院决定终结本次执行程序。")
    out = derive_form_drafts(fields, [unit], source_manifest=MANIFEST, manual_fields={"法院文件清单": ""})
    assert out["法院文件清单"] == ""
    assert out["_form_drafts"]["fields"]["法院文件清单"]["status"] == "human_modified"


@pytest.mark.parametrize("preservation_count,execution_count", [(19, 0), (11, 8)])
def test_large_inventory_groups_preservation_separately_and_preserves_every_anchor(preservation_count, execution_count):
    units, audit = [], []
    for index in range(preservation_count + execution_count):
        title, body = (("财产保全情况告知书", "本院未发现可供保全的财产。") if index < preservation_count
                       else ("执行结案通知书", "本院决定终结本次执行程序。"))
        unit, fields = reviewed(f"虚构区人民法院\n{title}\n{body}")
        unit.doc_id = unit.start_page = unit.end_page = index
        fields["_visual_classification_review"][0]["page"] = index + 1
        units.append(unit)
        audit.extend(fields["_visual_classification_review"])
    fields = {"_visual_classification_review": audit}
    out = derive_form_drafts(fields, units, source_manifest=[{"path": PATH, "pages": len(units)}])
    text = out["法院文件清单"]
    assert f"《保全法院文书》（{preservation_count}份，详见本卷）" in text
    if execution_count:
        assert f"《执行文书》（{execution_count}份，详见本卷）" in text
    else:
        assert "执行文书" not in text
    sources = out["_form_draft_sources"]["法院文件清单"]
    assert len(sources) == len(units)
    assert {ref["page"] for ref in sources} == set(range(1, len(units) + 1))
    assert all(ref["document_title"] == units[ref["doc_id"]].title for ref in sources)
