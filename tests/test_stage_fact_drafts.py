"""V8 red contracts: fictional stage facts are not final case completion.

All source sentences come from the pre-frozen nonlit/counsel synthetic oracle
or explicit adversarial variants. No OCR, model, HTTP, files or service needed.
These tests intentionally expose missing production support before implementation.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from fact_evidence import validate_fact
from form_drafts import derive_form_drafts
from visual_document_workflow import _verify_facts
from stage_fact_evidence import stage_subject, validate_stage_fact


WORK = "2026年10月10日，虚构律师戊完成采购合同模板审查，向聘方发送修订意见。"
WORK_PAGE = ("法律顾问工作记录\n服务对象：虚构星岚科技有限公司。"
             "顾问事项：日常合同审查与经营法律咨询。" + WORK +
             "本次工作只涉及模板审查；不涉及诉讼案件，未附聘方签收证明。")
STATUS = "截至2026年10月20日，该顾问协议仍在履行，尚未终止"
STATUS_PAGE = ("法律顾问协议存续情况说明\n聘方：虚构星岚科技有限公司。"
               "对应合同：服务期限为2026年1月1日至2026年12月31日的法律顾问合同。" +
               STATUS + "；本说明不是终止协议。后续日常顾问服务继续。")
NONLIT_WORK = "2026年9月12日完成采购合同草案审查，并向委托人发出法律意见书和合同修改稿。"
NONLIT_PAGE = ("办理法律事务活动记录\n项目名称：虚构星桥采购合同审查项目。"
               "委托人：虚构星桥商贸有限公司。办理结果：" + NONLIT_WORK +
               "本记录未附委托人签收回执；采购合同最终签订情况及律师费收款情况未记载。")
WORK_PATH = "fictional-case/work.pdf"
STATUS_PATH = "fictional-case/status.pdf"
CLIENT_PATH = "fictional-case/client.pdf"
CLIENT = "虚构星岚科技有限公司"
CLIENT_QUOTE = "聘方暨委托人：虚构星岚科技有限公司。"
MANIFEST = [{"path": WORK_PATH, "pages": 1}, {"path": STATUS_PATH, "pages": 1},
            {"path": CLIENT_PATH, "pages": 1}]


@pytest.mark.parametrize("field,value,page", [
    ("阶段工作情况", WORK, WORK_PAGE),
    ("阶段工作情况", NONLIT_WORK, NONLIT_PAGE),
    ("顾问协议状态", STATUS, STATUS_PAGE),
    ("顾问协议状态", "后续日常顾问服务继续。", STATUS_PAGE),
])
def test_literal_business_stage_and_continuing_status_are_supported(field, value, page):
    assert validate_fact(field, value, value, page)


@pytest.mark.parametrize("prefix", ["拟", "计划", "尚未", "未", "不", "如", "对方声称：", "参考案例："])
def test_stage_quote_cannot_crop_future_negation_or_other_party_scope(prefix):
    value = "完成采购合同模板审查，向聘方发送修订意见。"
    page = "法律顾问工作记录\n" + prefix + value
    assert not validate_fact("阶段工作情况", value, value, page)


@pytest.mark.parametrize("field,value,page", [
    ("阶段工作情况", "已完成全年法律顾问服务", "阶段工作情况：尚未完成全年法律顾问服务。"),
    ("阶段工作情况", "已签收修订意见", "阶段工作情况：未附聘方签收证明，不能证明已签收修订意见。"),
    ("阶段工作情况", "已收取顾问费12000元", "约定顾问费12000元，未附凭证，不能证明已收取顾问费12000元。"),
    ("顾问协议状态", "终止", STATUS_PAGE),
    ("顾问协议状态", "已终止", "法律顾问协议存续情况说明。如顾问协议已终止，应补充终止协议。"),
    ("顾问协议状态", "已终止", "参考案例：顾问协议状态：已终止。"),
    ("顾问协议状态", "尚未终止", "对方声称：顾问协议状态：尚未终止。"),
])
def test_stage_fields_do_not_manufacture_completion_payment_receipt_or_status(field, value, page):
    assert not validate_fact(field, value, value, page)


@pytest.mark.parametrize("field,value,page", [
    ("阶段工作情况", WORK, WORK_PAGE),
    ("顾问协议状态", STATUS, STATUS_PAGE),
])
def test_record_fields_preserves_new_internal_field_and_literal_evidence(field, value, page):
    pages = SimpleNamespace(pages={"f1p1": (WORK_PATH, 0)}, read=lambda key: page)
    fact = {"field": field, "value": value, "quote": value, "page_id": "f1p1"}
    before = deepcopy(fact)
    verified, rejected, duplicates, _ = _verify_facts([fact], pages, {"f1p1"}, {"f1p1"}, set(), set())
    assert not rejected and duplicates == 0 and len(verified) == 1
    stored_field, stored_value, evidence = verified[0]
    assert stored_field == field and stored_value == value
    assert evidence["quote"] == value and evidence["value"] == value
    assert evidence["source_path"] == WORK_PATH and evidence["page"] == 1
    assert fact == before


def accepted_fields(case_type="法律顾问"):
    return {"案件类别": case_type, "委托人": CLIENT, "阶段工作情况": WORK, "顾问协议状态": STATUS,
            "_provenance": {
                "委托人": [{"source_path": CLIENT_PATH, "page": 1, "quote": CLIENT_QUOTE,
                            "value": CLIENT, "method": "visual_agent_local_evidence"}],
                "阶段工作情况": [{"source_path": WORK_PATH, "page": 1, "quote": WORK,
                            "value": WORK, "method": "visual_agent_local_evidence", "subject": CLIENT}],
                "顾问协议状态": [{"source_path": STATUS_PATH, "page": 1, "quote": STATUS,
                            "value": STATUS, "method": "visual_agent_local_evidence", "subject": CLIENT}],
            }}


@pytest.mark.parametrize("case_type", ["nonlit", "counsel", "非诉", "非诉讼", "法律顾问"])
def test_stage_summary_draft_preserves_both_sources_and_continuing_status(case_type):
    fields = accepted_fields(case_type)
    before = deepcopy(fields)
    out = derive_form_drafts(fields, [], source_manifest=MANIFEST)
    summary = out.get("结案小结", "")
    assert WORK in summary and STATUS in summary
    assert "阶段工作" in summary and "协议状态" in summary
    refs = out.get("_form_draft_sources", {}).get("结案小结", [])
    assert {(r["field"], r["source_path"], r["page"], r["quote"])
            for r in refs} == {("委托人", CLIENT_PATH, 1, CLIENT_QUOTE),
                              ("阶段工作情况", WORK_PATH, 1, WORK),
                              ("顾问协议状态", STATUS_PATH, 1, STATUS)}
    assert out["_form_drafts"]["fields"]["结案小结"]["status"] == "generated"
    assert not out.get("结案日期") and not out.get("已收业务费") and not out.get("送达时间")
    assert fields == before
    again = derive_form_drafts(out, [], source_manifest=MANIFEST)
    assert again == out


@pytest.mark.parametrize("case_type", ["civil", "民事", "criminal", "行政", "arbitration"])
def test_stage_draft_does_not_reinterpret_litigation_or_unknown_business_type(case_type):
    out = derive_form_drafts(accepted_fields(case_type), [], source_manifest=MANIFEST)
    assert not out.get("结案小结")


@pytest.mark.parametrize("existing,manual", [
    ("人工明确只记录已核实阶段，不作正式结案。", True),
    ("", True),
    ("既有已采纳的完整办理结果，包含金额及附加条件。", False),
])
def test_existing_outcome_or_manual_empty_is_not_replaced_by_stage_draft(existing, manual):
    fields = accepted_fields()
    fields["结案小结"] = existing
    out = derive_form_drafts(fields, [], source_manifest=MANIFEST,
                             manual_fields={"结案小结": existing} if manual else {})
    assert out["结案小结"] == existing


@pytest.mark.parametrize("bad", ["outside_case", "page_out_of_range", "wrong_value", "missing_quote", "conflict"])
def test_unverified_or_other_case_stage_cannot_enter_draft(bad):
    fields = accepted_fields()
    del fields["顾问协议状态"]
    del fields["_provenance"]["顾问协议状态"]
    ref = fields["_provenance"]["阶段工作情况"][0]
    if bad == "outside_case": ref["source_path"] = "other-case/work.pdf"
    elif bad == "page_out_of_range": ref["page"] = 2
    elif bad == "wrong_value": ref["value"] = "不同工作"
    elif bad == "missing_quote": ref["quote"] = "没有此项工作"
    else: fields["_field_conflicts"] = [{"field": "阶段工作情况", "values": [WORK, "冲突工作"]}]
    out = derive_form_drafts(fields, [], source_manifest=MANIFEST)
    assert not out.get("结案小结")


def test_overlong_stage_draft_does_not_cut_off_negated_agreement_status():
    fields = accepted_fields()
    long_work = WORK * 12
    fields["阶段工作情况"] = long_work
    fields["_provenance"]["阶段工作情况"][0].update(value=long_work, quote=long_work)
    out = derive_form_drafts(fields, [], source_manifest=MANIFEST)
    summary = out.get("结案小结", "")
    # Either retain the complete bounded facts or leave a layout-review gap.
    # A prefix/truncated completion statement that loses 尚未终止 is unacceptable.
    assert not summary or (long_work in summary and STATUS in summary)
    assert not out.get("结案日期")


@pytest.mark.parametrize("page", [
    WORK,  # a sentence/title without an identified service subject is not enough
    "法律顾问工作记录\n" + WORK,
    "服务对象：虚构星岚科技有限公司。" + WORK,
    WORK_PAGE.replace("服务对象：虚构星岚科技有限公司。", "服务对象：未提供。"),
    WORK_PAGE.replace("服务对象：虚构星岚科技有限公司。", "服务对象：虚构星岚科技有限公司。委托人：虚构其他公司。"),
    WORK_PAGE.replace("服务对象：虚构星岚科技有限公司。", "对方服务对象：虚构星岚科技有限公司。"),
])
def test_title_or_unbound_ambiguous_subject_is_not_sufficient(page):
    assert not validate_stage_fact("阶段工作情况", WORK, WORK, page)


@pytest.mark.parametrize("suffix", ["，但尚未向聘方发送意见。", "，以上仅为下阶段计划。"])
def test_crop_cannot_discard_stage_qualifier(suffix):
    value = "完成采购合同模板审查"
    page = "法律顾问工作记录\n服务对象：虚构星岚科技有限公司。" + value + suffix
    assert not validate_stage_fact("阶段工作情况", value, value, page)


@pytest.mark.parametrize("alias", ["审（办）结果", "审(办)结果", "审办结果", "办案小结"])
@pytest.mark.parametrize("value,manual", [("既有已采纳结果，包括完整金额和条件。", False), ("", True)])
def test_existing_result_alias_or_manual_alias_blank_blocks_new_stage_summary(alias, value, manual):
    fields = accepted_fields()
    fields[alias] = value
    out = derive_form_drafts(fields, [], source_manifest=MANIFEST,
                             manual_fields={alias: value} if manual else {})
    assert out[alias] == value and not out.get("结案小结")


def test_supplement_refresh_keeps_manual_stage_summary_and_manual_blank():
    initial = derive_form_drafts(accepted_fields(), [], source_manifest=MANIFEST)
    for manual_value in ("人工只确认阶段工作，不确认全部服务终止。", ""):
        supplied = deepcopy(initial)
        supplied["阶段工作情况"] = WORK + "另完成一项核对。"
        supplied["_provenance"]["阶段工作情况"][0].update(
            value=supplied["阶段工作情况"], quote=supplied["阶段工作情况"])
        refreshed = derive_form_drafts(supplied, [], source_manifest=MANIFEST,
                                       manual_fields={"结案小结": manual_value})
        assert refreshed["结案小结"] == manual_value


def test_new_manual_result_alias_removes_only_previous_owned_stage_summary():
    initial = derive_form_drafts(accepted_fields(), [], source_manifest=MANIFEST)
    assert initial.get("结案小结")
    out = derive_form_drafts(initial, [], source_manifest=MANIFEST,
                             manual_fields={"审办结果": "人工保留的不同结果"})
    assert not out.get("结案小结") and out["审办结果"] == "人工保留的不同结果"
    again = derive_form_drafts(out, [], source_manifest=MANIFEST,
                               manual_fields={"审办结果": "人工保留的不同结果"})
    assert again == out


@pytest.mark.parametrize("value", [
    "未完成采购合同模板审查。",
    "不完成采购合同模板审查。",
    "对方完成采购合同模板审查。",
    "第三方完成采购合同模板审查。",
    "被告完成采购合同模板审查。",
    "完成采购合同模板审查，本案已终止。",
    "完成采购合同模板审查，本项目全部完成。",
])
def test_stage_action_must_be_actual_own_specific_work(value):
    page = "法律顾问工作记录\n服务对象：虚构星岚科技有限公司。" + value
    assert not validate_stage_fact("阶段工作情况", value, value, page)


@pytest.mark.parametrize("name", ["本公司", "该公司", "贵公司", "本单位"])
def test_generic_subject_is_not_an_identified_service_subject(name):
    page = WORK_PAGE.replace("虚构星岚科技有限公司", name)
    assert not validate_stage_fact("阶段工作情况", WORK, WORK, page)


@pytest.mark.parametrize("bad", ["other_subject", "manual_change", "no_client", "no_client_provenance",
                                  "client_conflict", "missing_subject", "client_source_removed"])
def test_stage_source_is_bound_to_current_unambiguous_case_client(bad):
    fields = accepted_fields()
    manifest = deepcopy(MANIFEST)
    manual = {}
    if bad == "other_subject": fields["_provenance"]["阶段工作情况"][0]["subject"] = "虚构另外公司"
    elif bad == "manual_change": manual["委托人"] = "人工改为另一家公司"
    elif bad == "no_client": fields.pop("委托人")
    elif bad == "no_client_provenance": fields["_provenance"].pop("委托人")
    elif bad == "client_conflict": fields["_field_conflicts"] = [{"field": "委托人", "values": [CLIENT, "另一家公司"]}]
    elif bad == "missing_subject": fields["_provenance"]["阶段工作情况"][0].pop("subject")
    else: manifest = [item for item in manifest if item['path'] != CLIENT_PATH]
    out = derive_form_drafts(fields, [], source_manifest=manifest, manual_fields=manual)
    assert not out.get("结案小结")
    assert out["_form_drafts"]["fields"]["结案小结"]["reason_codes"][0] in ("stage_subject_mismatch", "stage_subject_unverified")


def test_same_explicit_manual_client_can_bind_current_stage_without_invented_source():
    fields = accepted_fields()
    del fields["_provenance"]["委托人"]
    out = derive_form_drafts(fields, [], source_manifest=MANIFEST, manual_fields={"委托人": CLIENT})
    assert WORK in out["结案小结"] and STATUS in out["结案小结"]
    refs = out["_form_draft_sources"]["结案小结"]
    identity = [ref for ref in refs if ref["field"] == "委托人"]
    assert identity == [{"field": "委托人", "method": "human", "value": CLIENT}]


def test_stage_subject_is_local_full_identity_and_keeps_distinct_names():
    assert stage_subject(WORK_PAGE) == CLIENT
    assert stage_subject(STATUS_PAGE) == CLIENT
    assert stage_subject(WORK_PAGE.replace(CLIENT, "虚构星蓝科技有限公司")) == "虚构星蓝科技有限公司"
    assert stage_subject(WORK_PAGE.replace(CLIENT, "星岚（简称）")) is None


@pytest.mark.parametrize("name,expected", [("虚构和丰公司", "虚构和丰公司"), ("虚构及丰公司", "虚构及丰公司"),
                                          ("甲公司和乙公司", None), ("张甲和李乙", None), ("甲和乙两人", None)])
def test_identity_conjunction_is_not_a_single_character_company_name_ban(name, expected):
    assert stage_subject(WORK_PAGE.replace(CLIENT, name)) == expected


@pytest.mark.parametrize("state", ["中止", "终止", "解除"])
def test_explicit_agreement_state_is_not_silently_discarded_as_not_ongoing(state):
    value = f"截至2026年10月20日，该顾问协议已{state}。"
    page = "法律顾问协议状态说明\n聘方：" + CLIENT + "。" + value
    assert validate_stage_fact("顾问协议状态", value, value, page)
    assert validate_fact("顾问协议状态", value, value, page)


@pytest.mark.parametrize("prefix", ["拟", "计划", "若", "对方声称：", "参考案例：", "另一顾问协议的情况："])
def test_termination_claim_condition_plan_or_other_agreement_does_not_pass(prefix):
    value = "顾问协议已终止。"
    page = "法律顾问协议状态说明\n聘方：" + CLIENT + "。" + prefix + value
    assert not validate_stage_fact("顾问协议状态", value, value, page)


def test_conflicting_stage_records_invalidate_previous_generated_summary_without_latest_guess():
    initial = derive_form_drafts(accepted_fields(), [], source_manifest=MANIFEST)
    assert STATUS in initial["结案小结"]
    initial["_field_conflicts"] = [{"field": "顾问协议状态", "values": [STATUS, "顾问协议已终止。"]}]
    out = derive_form_drafts(initial, [], source_manifest=MANIFEST)
    assert not out.get("结案小结")
    assert out["_form_drafts"]["fields"]["结案小结"]["reason_codes"] == ["stage_fact_conflict"]
    assert out["_field_conflicts"] == initial["_field_conflicts"]


def test_manual_summary_wins_even_if_underlying_stage_records_need_review():
    fields = accepted_fields()
    fields["_field_conflicts"] = [{"field": "阶段工作情况", "values": [WORK, "另一项具体工作"]}]
    out = derive_form_drafts(fields, [], source_manifest=MANIFEST,
                             manual_fields={"结案小结": "人工只采用已核对的阶段工作，协议状态待核。"})
    assert out["结案小结"] == "人工只采用已核对的阶段工作，协议状态待核。"


@pytest.mark.parametrize("value", [
    "演示乙有限公司完成采购合同审查。",
    "本所为演示乙有限公司完成采购合同审查。",
    "李乙完成采购合同审查。",
])
def test_other_named_event_actor_is_not_owned_by_the_page_service_subject(value):
    page = "法律顾问工作记录\n服务对象：" + CLIENT + "。" + value
    assert not validate_stage_fact("阶段工作情况", value, value, page)


@pytest.mark.parametrize("prefix", ["演示乙有限公司声称：", "李乙转述："])
def test_named_allegation_scope_cannot_be_cropped(prefix):
    value = "完成采购合同审查。"
    page = "法律顾问工作记录\n服务对象：" + CLIENT + "。" + prefix + value
    assert not validate_stage_fact("阶段工作情况", value, value, page)


@pytest.mark.parametrize("tail", ["上述为拟开展工作，不是已完成记录。", "以上为工作安排。"])
def test_later_plan_disclaimer_is_not_discarded(tail):
    value = "完成采购合同审查后发送修订意见。"
    page = "法律顾问工作记录\n服务对象：" + CLIENT + "。" + value + tail
    assert not validate_stage_fact("阶段工作情况", value, value, page)


@pytest.mark.parametrize("body", [
    "2026年1月该顾问协议仍在履行。2026年10月该顾问协议已经终止。",
    "此前该顾问协议仍在履行，目前该顾问协议已终止。",
])
def test_conflicting_statuses_on_same_page_remain_reviewable_without_latest_guess(body):
    page = "法律顾问协议状态说明\n聘方：" + CLIENT + "。" + body
    for value in ("该顾问协议仍在履行", "该顾问协议已终止", "该顾问协议已经终止"):
        if value in body:
            assert not validate_stage_fact("顾问协议状态", value, value, page)


def test_explicit_human_blank_provenance_survives_without_manual_map():
    fields = accepted_fields()
    fields["结案小结"] = ""
    fields["_provenance"]["结案小结"] = [{"method": "human", "value": ""}]
    out = derive_form_drafts(fields, [], source_manifest=MANIFEST)
    assert out["结案小结"] == ""
    assert out["_form_drafts"]["fields"]["结案小结"]["status"] == "human_modified"


@pytest.mark.parametrize("state", ["已经终止", "已经中止", "已解除"])
def test_status_heading_is_not_a_competing_body_fact(state):
    value = "该顾问协议" + state + "。"
    page = "法律顾问协议存续情况说明\n聘方：" + CLIENT + "。" + value
    assert validate_stage_fact("顾问协议状态", value, value, page)
    assert validate_fact("顾问协议状态", value, value, page)


@pytest.mark.parametrize("money", ["已收到全部律师费", "实收律师费12000元", "尚欠律师费1000元",
                                    "已退律师费1000元", "应退律师费1000元", "退款1000元", "退费1000元"])
def test_work_fact_cannot_carry_receipts_refunds_or_debt(money):
    value = "本所完成采购合同审查，" + money + "。"
    page = "法律顾问工作记录\n服务对象：" + CLIENT + "。" + value
    assert not validate_stage_fact("阶段工作情况", value, value, page)
    assert not validate_fact("阶段工作情况", value, value, page)


@pytest.mark.parametrize("field,value,page", [
    ("阶段工作情况", WORK, WORK_PAGE),
    ("顾问协议状态", STATUS, STATUS_PAGE),
])
def test_actual_fixture_header_and_line_boundaries_survive_production_entry(field, value, page):
    title, body = page.split("\n", 1)
    # Literal frozen synthetic source header, independently checked before v8.
    original = title + "\n全虚构验收材料 仅供软件功能测试 非真实法律文书\n" + body
    assert stage_subject(original) == CLIENT
    assert validate_stage_fact(field, value, value, original)
    assert validate_fact(field, value, value, original)
