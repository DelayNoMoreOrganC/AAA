from copy import deepcopy
import json

import pytest

from app.services.field_assurance import field_assurance
from app.services.preview_fields import build_preview

SOURCE = {"path": "fictional.pdf", "file_id": "fictional", "pages": 4}


def test_business_intake_excerpt_links_current_source_and_rejects_changed_bundle():
    from types import SimpleNamespace as NS
    from app.core.v4_bridge import init_v4_path
    init_v4_path()
    from business_intake import collect, KEY
    from form_drafts import derive_form_drafts
    unit = NS(doc_type='contract', doc_id=1, source_path=SOURCE['path'], start_page=0, end_page=0, confidence=.95)
    data = {'案件类别':'非诉'}
    text = '非诉讼法律事务委托合同一、甲方委托的具体事项详述如下：1、协助办理公证手续。2、仅提供该事项咨询。二、工作方式。'
    collect(data, page_cache={(SOURCE['path'],1):text}, allowed_sources={(SOURCE['path'],1)}, document_units=[unit])
    data = derive_form_drafts(data, [unit], source_manifest=[SOURCE])
    value = data['案情简介']
    result = field_assurance('案情简介', value, data, source_manifest=[SOURCE])
    assert result['status'] == 'derived_draft'
    assert result['anchors'] == [{'file_id':'fictional','page':1}]
    assert field_assurance('案情简介', value, data, source_manifest=[])['status'] == 'unverified'
    data[KEY]['pages'][0]['quote'] += '补充内容'
    assert field_assurance('案情简介', value, data, source_manifest=[SOURCE])['status'] == 'unverified'


def fields():
    return {"委托人": "虚构乙", "_provenance": {"委托人": [{
        "method": "visual_agent_local_evidence", "value": "虚构乙", "quote": "委托人：虚构乙",
        "source_path": SOURCE["path"], "page": 1}]}}


def assess(data, **kw):
    return field_assurance("委托人", data.get("委托人", ""), data, source_manifest=[SOURCE], **kw)


def test_current_in_case_source_is_not_asserted_as_verified_truth_or_exposed():
    result = assess(fields())
    assert result["status"] == "source_supported"
    assert result["anchors"] == [{"file_id": "fictional", "page": 1}]
    assert "待核对" in result["label"]
    assert "source_path" not in json.dumps(result) and "虚构乙" not in json.dumps(result,ensure_ascii=False)


@pytest.mark.parametrize("change", ["wrong_value", "wrong_quote", "other_case", "page_overflow", "untrusted_method"])
def test_unverified_field_never_gets_source_badge(change):
    data = fields(); ref = data["_provenance"]["委托人"][0]
    if change == "wrong_value": ref["value"] = "虚构甲"
    if change == "wrong_quote": ref["quote"] = "无对应值"
    if change == "other_case": ref["source_path"] = "another.pdf"
    if change == "page_overflow": ref["page"] = 5
    if change == "untrusted_method": ref["method"] = "model_guess"
    assert assess(data)["status"] == "unverified"


def test_workflow_conflict_and_human_resolution_blank():
    data = fields()
    assert assess(data, issues=[{"kind": "field_conflict", "detail": {"field": "委托人"}}])["status"] == "conflict"
    assert assess(data, issues=[{"kind": "form_draft", "field": "委托人"}])["status"] == "source_supported"
    data["委托人"] = ""
    data["_provenance"]["委托人"].append({"method": "human", "value": ""})
    assert assess(data)["status"] == "human_confirmed"


def test_draft_badge_rejects_changed_values_or_removed_sources():
    from app.core.v4_bridge import init_v4_path
    init_v4_path()
    from form_drafts import derive_form_drafts
    data = fields()
    data["案由"] = "买卖合同纠纷"
    data["_provenance"]["案由"] = [{"method":"local_agent", "value":data["案由"],
        "quote":"案由：买卖合同纠纷", "source_path":SOURCE["path"], "page":2}]
    drafted = derive_form_drafts(data, [], source_manifest=[SOURCE])
    value = drafted["案件或项目名称"]
    result = field_assurance("案件或项目名称", value, drafted, source_manifest=[SOURCE])
    assert result["status"] == "derived_draft" and result["source_count"] == 2
    assert field_assurance("案件或项目名称", value, drafted)["status"] == "unverified"
    assert field_assurance("案件或项目名称", value+"已结案", drafted, source_manifest=[SOURCE])["status"] == "unverified"


def test_supplement_conflict_overrides_old_human_badge_until_exact_resolution():
    data = fields()
    data["_provenance"]["委托人"].append({"method": "human", "value": data["委托人"]})
    conflict = {"field": "委托人", "saved": data["委托人"], "new": "虚构甲"}
    issue = {"id": "new-conflict", "kind": "field_conflict", "detail": conflict}
    data["_field_conflicts"] = [conflict]
    data["_issue_decisions"] = {"old-conflict": {"action": "acknowledged", "reason": "已核对"}}
    assert assess(data, issues=[issue])["status"] == "conflict"
    data["_issue_decisions"]["new-conflict"] = {"action": "acknowledged", "reason": ""}
    assert assess(data, issues=[issue])["status"] == "conflict"
    data["_issue_decisions"]["new-conflict"]["reason"] = "已核对新材料并保留原值"
    assert assess(data, issues=[issue])["status"] == "conflict"
    conflict["resolved"] = True
    assert assess(data, issues=[issue])["status"] == "human_confirmed"
    data["_field_conflicts"].append({"field": "委托人", "new": "虚构丙"})
    assert assess(data, issues=[issue])["status"] == "conflict"


def test_alias_uses_its_actual_provenance_and_does_not_revive_human_blank():
    data = {"案号":"（2026）虚民初1号", "_provenance":{"案号":[{"method":"human", "value":"（2026）虚民初1号"}]}}
    rows = {r["key"]:r for r in build_preview("档案卷宗",data)["fields"]}
    assert rows["法院收案号"]["assurance"]["status"] == "human_confirmed"
    data["法院收案号"]="";data["_provenance"]["法院收案号"]=[{"method":"human","value":""}]
    rows = {r["key"]:r for r in build_preview("档案卷宗",data)["fields"]}
    assert rows["法院收案号"]["value"] == ""
    assert rows["法院收案号"]["assurance"]["status"] == "human_confirmed"


def test_plaintiff_defendant_and_contract_signature_date_are_not_role_or_receipt_aliases():
    data = {"委托人":"虚构被告", "原告":"虚构甲", "被告":"虚构被告",
            "判决书中的原告":"虚构甲", "判决书中的被告":"虚构被告", "委托代理合同中落款日期":"2026-01-01"}
    before=deepcopy(data)
    for template in ("立案审批表","档案卷宗"):
        values={r["key"]:r["value"] for r in build_preview(template,data)["fields"]}
        date_key = '立案审批日期' if template == '立案审批表' else '收案日期'
        assert values["当事人"] == values["对方当事人"] == values[date_key] == ""
    assert data == before


def test_unattributed_document_counsel_is_not_assigned_to_this_firm():
    for template in ("档案卷宗", "送达材料清单", "质量监督卡"):
        values = {r["key"]: r["value"] for r in build_preview(template, {
            "代理律师": "虚构甲律师", "判决书上代理律师": "虚构乙律师"})["fields"]}
        assert values["承办律师"] == ""
