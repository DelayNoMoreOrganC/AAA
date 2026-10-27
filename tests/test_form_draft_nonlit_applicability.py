"""Synthetic material sets: reduce inapplicable prompts without hiding uncertainty."""
from copy import deepcopy
import hashlib

import pytest

from form_drafts import derive_form_drafts, draft_review_summary, NO_COURT_MATERIAL_REASON
from pdf_doc_locator import DocumentUnit


PATH = "fictional-nonlit.pdf"


def doc(index=0, kind="legal_work", title="法律意见书", confidence=0.95, **kwargs):
    return DocumentUnit(index, kind, index, index, title, source_path=PATH,
                        confidence=confidence, **kwargs)


def derive(fields, units, pages=None, **kwargs):
    return derive_form_drafts(fields, units, source_manifest=[{
        "path": PATH, "pages": pages if pages is not None else len(units)
    }], **kwargs)


def inventory_status(result):
    return result["_form_drafts"]["fields"]["法院文件清单"]


@pytest.mark.parametrize("case_type,kind,title", [
    ("非诉", "legal_work", "法律意见书"),
    ("法律顾问", "work_record", "法律顾问工作记录"),
    ("nonlit", "client_talk", "与委托人谈话记录"),
    ("counsel", "agreement_status", "法律顾问协议存续情况说明"),
])
def test_complete_nonlit_material_set_does_not_request_missing_court_papers(case_type, kind, title):
    fields = {"案件类别": case_type}
    result = derive(fields, [doc(kind=kind, title=title)])
    assert inventory_status(result)["status"] == "not_applicable"
    assert inventory_status(result)["reason_codes"] == [NO_COURT_MATERIAL_REASON]
    assert "法院文件清单" not in result
    assert "法院文件清单" not in draft_review_summary(result)["insufficient_fields"]
    assert result["_form_draft_sources"]["法院文件清单"] == []
    assert result["_provenance"]["法院文件清单"] == []
    assert fields == {"案件类别": case_type}
    assert derive(result, [doc(kind=kind, title=title)]) == result


@pytest.mark.parametrize("case_type", ["民事", "行政", "刑事", "", "未识别"])
def test_litigation_or_unknown_case_type_keeps_missing_court_paper_review(case_type):
    result = derive({"案件类别": case_type}, [doc(kind="contract", title="委托合同")])
    assert inventory_status(result)["status"] == "insufficient"
    assert "法院文件清单" in draft_review_summary(result)["insufficient_fields"]


@pytest.mark.parametrize("kind,title", [("judgment", "民事判决书"), ("ruling", "民事裁定书"),
                                        ("execution", "执行通知书")])
def test_nonlit_case_with_actual_court_document_keeps_inventory(kind, title):
    result = derive({"案件类别": "法律顾问"}, [doc(kind=kind, title=title)])
    assert inventory_status(result)["status"] == "generated"
    assert title in result["法院文件清单"]
    assert "已送达" not in result["法院文件清单"]


@pytest.mark.parametrize("kind,title,confidence", [
    ("unknown", "待辨认材料", 0.9), ("evidence", "证据材料", 0.9),
    ("execution", "执行申请书", 0.9), ("complaint", "起诉状", 0.9),
    ("legal_work", "法律意见书", 0.5), ("legal_work", "法律意见书", float("nan")),
])
def test_uncertain_or_litigation_related_material_is_not_hidden(kind, title, confidence):
    result = derive({"案件类别": "非诉"}, [doc(kind=kind, title=title, confidence=confidence)])
    assert inventory_status(result)["status"] == "insufficient"


@pytest.mark.parametrize("field", ["案号", "执行案号", "法院收案号", "审理法院"])
def test_existing_litigation_identity_prevents_automatic_not_applicable(field):
    result = derive({"案件类别": "法律顾问", field: "虚构本案记录"}, [doc()])
    assert inventory_status(result)["status"] == "insufficient"


@pytest.mark.parametrize("units,pages", [([], 1), ([doc()], 2), ([doc(1)], 2),
                                        ([doc(), doc()], 1)])
def test_absent_uncovered_or_duplicate_source_pages_keep_review(units, pages):
    result = derive({"案件类别": "非诉"}, units, pages=pages)
    assert inventory_status(result)["status"] == "insufficient"


def test_manual_classification_can_establish_known_nonlit_material_without_acknowledging_facts():
    result = derive({"案件类别": "非诉"}, [doc(confidence=0.2, manual_catalog_seq=7)])
    assert inventory_status(result)["status"] == "not_applicable"
    assert "_review_decisions" not in result
    assert "签章" not in result and "结案小结" not in result


def test_supplemented_court_material_replaces_not_applicable_status():
    first = derive({"案件类别": "非诉"}, [doc()])
    units = [doc(), doc(1, "judgment", "民事判决书")]
    supplemented = derive(first, units)
    assert inventory_status(supplemented)["status"] == "generated"
    assert supplemented["法院文件清单"] == "《民事判决书》（原材料第2页）"
    uncertain = derive(first, [doc(kind="unknown", title="尚待识别")])
    assert inventory_status(uncertain)["status"] == "insufficient"


@pytest.mark.parametrize("manual", ["", "人工核对清单"])
def test_material_applicability_never_changes_manual_inventory_or_deliberate_clear(manual):
    result = derive({"案件类别": "法律顾问"}, [doc()], manual_fields={"法院文件清单": manual})
    assert result["法院文件清单"] == manual
    assert inventory_status(result)["status"] == "human_modified"


def evidenced_project(name="虚构采购合同审查项目"):
    return {"案件类别": "非诉", "委托人": "虚构甲公司", "案由": "采购合同审查",
            "案件或项目名称": name, "_provenance": {"案件或项目名称": [{
                "method": "visual_agent_local_evidence", "value": name,
                "quote": f"项目名称：{name}。", "source_path": PATH, "page": 1}]}}


def test_explicit_project_name_and_original_provenance_win_over_composed_label():
    fields = evidenced_project()
    before = deepcopy(fields)
    result = derive(fields, [doc()])
    assert result["案件或项目名称"] == "虚构采购合同审查项目"
    assert result["_provenance"]["案件或项目名称"] == before["_provenance"]["案件或项目名称"]
    assert result["_form_drafts"]["fields"]["案件或项目名称"]["status"] == "preserved"
    assert fields == before


def test_explicit_evidence_can_survive_stale_machine_ownership_metadata():
    fields = evidenced_project()
    fields["_form_drafts"] = {"version": 4, "fields": {"案件或项目名称": {
        "status": "generated", "value_digest": hashlib.sha256(fields["案件或项目名称"].encode()).hexdigest()}}}
    result = derive(fields, [doc()])
    assert result["案件或项目名称"] == fields["案件或项目名称"]
    assert result["_form_drafts"]["fields"]["案件或项目名称"]["reason_codes"] == ["explicit_project_name_preserved"]
    assert {x["field"] for x in result["_form_draft_sources"]["案件或项目名称"]} == {"案件或项目名称"}


@pytest.mark.parametrize("manual", ["", "人工确认项目"])
def test_explicit_project_name_does_not_overwrite_human_change(manual):
    result = derive(evidenced_project(), [doc()], manual_fields={"案件或项目名称": manual})
    assert result["案件或项目名称"] == manual
    assert result["_form_drafts"]["fields"]["案件或项目名称"]["status"] == "human_modified"
