"""Fictional facts only: drafts cannot manufacture legal/financial events."""
from copy import deepcopy
import json

import pytest

from form_drafts import derive_form_drafts, draft_review_summary, court_inventory_page_counts, METHOD
from pdf_doc_locator import DocumentUnit


PATH = "fictional-source.pdf"
MANIFEST = [{"path": PATH, "pages": 20, "file_id": "fictional-id"}]


def evidenced(**values):
    return {**values, "_provenance": {field: [{"method": "visual_agent_local_evidence", "value": value,
        "quote": f"{field}：{value}", "source_path": PATH, "page": 1}] for field, value in values.items()}}


def unit(number=0, kind="judgment", confidence=0.9, title="民事判决书", **kw):
    return DocumentUnit(number, kind, number, number, title, source_path=PATH, confidence=confidence, **kw)


def derive(fields, units=(), **kwargs):
    return derive_form_drafts(fields, units, source_manifest=MANIFEST, **kwargs)


def test_three_drafts_use_verified_values_and_keep_separate_provenance():
    fields = evidenced(委托人="虚构甲公司", 对方当事人="虚构乙公司", 案由="买卖合同纠纷", 案号="（2026）虚民初1号",
                       地址="虚构示例路1号", 委托人电话="00000000000", 结案小结="裁定驳回起诉。")
    before = deepcopy(fields)
    result = derive(fields, [unit()])
    assert fields == before
    assert "虚构甲公司" in result["案情简介"] and "买卖合同纠纷" in result["案情简介"]
    assert "裁定驳回起诉" not in result["案情简介"] and "原告" not in result["案情简介"] and "被告" not in result["案情简介"]
    assert result["法院文件清单"] == "《民事判决书》（原材料第1页）"
    assert result["委托人联系地址及电话"] == "虚构示例路1号；00000000000"
    assert all(item["status"] == "generated" for item in result["_form_drafts"]["fields"].values())
    assert "虚构甲公司" not in json.dumps(result["_form_drafts"], ensure_ascii=False)
    assert all(ref["method"] == METHOD for ref in result["_provenance"]["案情简介"])
    assert all(ref.get("draft") for ref in result["_provenance"]["法院文件清单"])
    assert draft_review_summary(result)["generated_count"] == 4
    assert not any(key in result for key in ("承办律师意见", "主任审批意见", "已收业务费", "委托人对服务质量意见", "送达日期"))


@pytest.mark.parametrize("mutation", ["no_provenance", "mismatched_value", "outside_source", "outside_page", "unknown_method", "quote_missing_value", "conflict"])
def test_unverified_or_conflicting_facts_do_not_create_brief(tmp_path, mutation):
    fields = evidenced(委托人="虚构甲", 案由="买卖合同纠纷")
    ref = fields["_provenance"]["委托人"][0]
    if mutation == "no_provenance": fields.pop("_provenance")
    elif mutation == "mismatched_value": fields["委托人"] = "未经核验的乙"
    elif mutation == "outside_source": ref["source_path"] = "other-case.pdf"
    elif mutation == "outside_page": ref["page"] = 21
    elif mutation == "unknown_method": ref["method"] = "model_guess"
    elif mutation == "quote_missing_value": ref["quote"] = "无对应内容"
    else: fields["_field_conflicts"] = [{"field": "委托人", "values": ["虚构甲", "虚构乙"]}]
    result = derive(fields)
    assert "案情简介" not in result
    assert result["_form_drafts"]["fields"]["案情简介"]["status"] == "insufficient"
    assert result["_form_draft_sources"]["案情简介"] == []


def test_human_correction_resolves_input_conflict_without_overwriting_human_draft_or_blank():
    fields = evidenced(委托人="虚构甲", 案由="买卖合同纠纷", 委托人电话="00000000000")
    fields["_field_conflicts"] = [{"field": "委托人", "values": ["虚构甲", "虚构乙"]}]
    generated = derive(fields, manual_fields={"委托人": "人工核对的乙"})
    assert "人工核对的乙" in generated["案情简介"]
    result = derive(generated, [unit()], manual_fields={"案情简介": "人工完整说明", "法院文件清单": "", "委托人联系地址及电话": ""})
    assert result["案情简介"] == "人工完整说明"
    assert result["法院文件清单"] == result["委托人联系地址及电话"] == ""
    assert all(result["_form_drafts"]["fields"][field]["status"] == "human_modified"
               for field in ("案情简介", "法院文件清单", "委托人联系地址及电话"))


def test_partial_contact_does_not_invent_address_or_phone():
    result = derive(evidenced(委托人="虚构甲", 委托人电话="00000000000"))
    assert result["委托人联系地址及电话"] == "委托人：虚构甲；电话：00000000000"
    assert result["_form_drafts"]["fields"]["委托人联系地址及电话"]["reason_codes"] == ["partial_contact"]
    assert "委托人联系地址及电话" not in derive(evidenced(委托人="虚构甲"))


def test_absent_business_values_remain_absent_while_insufficiency_is_reported():
    result = derive({"委托人": "虚构旧值", "合同号": "虚构合同"})
    assert {key: value for key, value in result.items() if not key.startswith("_")} == {
        "委托人": "虚构旧值", "合同号": "虚构合同"}
    assert all(item["status"] == "insufficient" for item in result["_form_drafts"]["fields"].values())


@pytest.mark.parametrize("units", [(), (unit(),)])
def test_repeated_derivation_does_not_turn_absent_values_into_new_empty_fields(units):
    first = derive({"委托人": "无证据的虚构旧值"}, units)
    assert "案情简介" not in first and "案件或项目名称" not in first
    assert "委托人联系地址及电话" not in first
    current = first
    for _ in range(3):
        current = derive(current, units)
        assert current == first


def test_workflow_conflict_blocks_derived_summary_without_changing_preserved_facts():
    fields = evidenced(委托人="虚构甲", 案由="虚构事项")
    previous = derive(fields)
    result = derive(previous, blocked_fields=["委托人"])
    assert result["案情简介"] == "" and result["委托人"] == "虚构甲"
    assert "_field_conflicts" not in result
    # The workflow removes a block only when the current conflict is resolved.
    resolved = derive(result, blocked_fields=[], manual_fields={"委托人": "核对的乙"})
    assert "核对的乙" in resolved["案情简介"]


def test_new_supplement_conflict_cannot_reuse_stale_human_input_in_automatic_drafts():
    fields = evidenced(委托人="虚构甲", 案由="合同纠纷")
    initial = derive(fields, manual_fields={"委托人":"虚构甲"})
    result = derive(initial, manual_fields={"委托人":"虚构甲"}, blocked_fields=["委托人"])
    assert result["委托人"] == "虚构甲"
    assert result["案情简介"] == result["案件或项目名称"] == ""
    assert "_form_draft_blocked_fields" not in result


def test_supplement_recomputes_only_machine_drafts_and_is_idempotent():
    first = derive(evidenced(委托人="虚构甲", 案由="买卖合同纠纷"), [unit()])
    next_fields = deepcopy(first)
    next_fields.update(evidenced(委托人="虚构甲", 案由="买卖合同纠纷", 委托人电话="00000000000"))
    result = derive(next_fields, [unit(), unit(1, "ruling", title="民事裁定书")])
    assert "民事判决书" in result["法院文件清单"] and "民事裁定书" in result["法院文件清单"]
    assert result["委托人联系地址及电话"]
    assert derive(result, [unit(), unit(1, "ruling", title="民事裁定书")]) == result
    assert len(result["_provenance"]["法院文件清单"]) == 2


def test_removed_source_invalidates_generated_values_without_dropping_human_values():
    previous = derive(evidenced(委托人="虚构甲", 案由="合同纠纷", 地址="虚构地址"), [unit()])
    result = derive_form_drafts(previous, [], source_manifest=[], manual_fields={"法院文件清单": "人工记录"})
    assert result["案情简介"] == result["委托人联系地址及电话"] == ""
    assert result["法院文件清单"] == "人工记录"
    assert result["_provenance"]["案情简介"] == []


def test_existing_legacy_value_is_preserved_but_never_marked_as_generated_evidence():
    result = derive({"案情简介": "历史描述，需核对"})
    assert result["案情简介"] == "历史描述，需核对"
    assert result["_form_drafts"]["fields"]["案情简介"]["status"] == "preserved"
    assert result["_form_draft_sources"]["案情简介"] == []


def test_court_inventory_excludes_applications_unknown_and_low_confidence_until_human_classifies():
    units = [unit(0, "complaint", title="起诉状"), unit(1, "execution", title="执行申请书"),
             unit(2, "unknown", title="受理通知书"), unit(3, "ruling", confidence=0.2, title="民事裁定书"),
             unit(4, "execution", title="执行裁定书")]
    result = derive({}, units)
    assert result["法院文件清单"] == "《执行裁定书》（原材料第5页）"
    units[3].manual_catalog_seq = 14
    result = derive(result, units)
    assert "民事裁定书" in result["法院文件清单"]
    assert "执行申请书" not in result["法院文件清单"] and "受理通知书" not in result["法院文件清单"]
    assert "已送达" not in result["法院文件清单"]
    assert "classification_requires_review" in result["_form_drafts"]["fields"]["法院文件清单"]["reason_codes"]


def test_inventory_keeps_all_documents_above_five_and_distinguishes_same_titles():
    result = derive({}, [unit(i) for i in range(12)])
    assert len(result["法院文件清单"].splitlines()) == 12
    assert "原材料第12页" in result["法院文件清单"]
    assert len(result["_form_draft_sources"]["法院文件清单"]) == 12

def test_inventory_page_counts_use_exact_source_spans_and_preserve_manual_blank():
    first=unit();first.end_page=5
    second=unit(6,'ruling',title='民事裁定书')
    fields=derive({},[first,second])
    assert court_inventory_page_counts(fields)==[6,1]
    assert court_inventory_page_counts(derive(fields,[first,second],manual_fields={'法院文件清单':''}))==[]
    assert court_inventory_page_counts({'法院文件清单':fields['法院文件清单']})==[None,None]
    fields['法院文件清单']=fields['法院文件清单'].replace('1—6','1—9')
    assert court_inventory_page_counts(fields)==[None,None]

@pytest.mark.parametrize('change', ['missing_ref','duplicate','boolean','changed_title','changed_page','human'])
def test_inventory_page_counts_do_not_guess_from_stale_or_mismatched_metadata(change):
    fields=derive({},[unit(),unit(1)])
    refs=fields['_form_draft_sources']['法院文件清单']
    if change=='missing_ref':refs.pop()
    if change=='duplicate':refs[1]=deepcopy(refs[0])
    if change=='boolean':refs[0]['page']=True
    if change=='changed_title':refs[0]['document_title']='其他文书'
    if change=='changed_page':refs[0]['page_end']=3
    if change=='human':fields['_form_drafts']['fields']['法院文件清单']['status']='human_modified'
    assert court_inventory_page_counts(fields)==[None,None]

def test_grouped_inventory_counts_do_not_masquerade_as_single_document_pages():
    fields=derive({},[unit(i) for i in range(19)])
    assert len(fields['法院文件清单'].splitlines())==1
    assert court_inventory_page_counts(fields)==[None]

def notice_review(**changes):
    return {'source_path':PATH,'page':1,'method':'local_title_context_review',
            'independent_title_verified':True,'effective_doc_type':'unknown',
            'title':'受理案件通知书','procedure_stage':'trial',
            'reason_code':'acceptance_notice_no_dedicated_slot',**changes}

def test_verified_notice_enters_inventory_while_catalog_uncertainty_is_preserved():
    notice=unit(kind='unknown',confidence=.5,title='受理案件通知书',catalog_seq=7)
    fields={'_visual_classification_review':[notice_review()]}
    result=derive(fields,[notice])
    assert result['法院文件清单']=='《受理案件通知书》（原材料第1页）'
    assert result['_form_draft_sources']['法院文件清单'][0]['catalog_mapping_pending'] is True
    assert notice.doc_type=='unknown' and notice.catalog_seq==7 and notice.confidence==.5
    assert '已送达' not in result['法院文件清单']
    assert derive(result,[notice],manual_fields={'法院文件清单':''})['法院文件清单']==''
    assert derive_form_drafts(result,[notice],source_manifest=[])['法院文件清单']==''

@pytest.mark.parametrize('changes',[
    {'page':2},{'source_path':'another.pdf'},{'independent_title_verified':False},
    {'effective_doc_type':'summons'},{'procedure_stage':'unknown'},{'title':'传票'},
    {'reason_code':'model_guess'},{'method':'model_title'},
])
def test_notice_inventory_requires_matching_independent_review(changes):
    result=derive({'_visual_classification_review':[notice_review(**changes)]},
                  [unit(kind='unknown',confidence=.5,title='受理案件通知书')])
    assert not result.get('法院文件清单')

def test_notice_inventory_rejects_ambiguous_span_and_contradictory_review():
    notice=unit(kind='unknown',confidence=.5,title='受理案件通知书')
    reviews=[notice_review(),notice_review(independent_title_verified=False)]
    assert not derive({'_visual_classification_review':reviews},[notice]).get('法院文件清单')
    notice.end_page=1
    assert not derive({'_visual_classification_review':[notice_review()]},[notice]).get('法院文件清单')


def test_field_and_source_instructions_are_data_and_never_execute():
    fields = evidenced(委托人="虚构甲<script>无脚本</script>", 案由="虚构争议")
    result = derive(fields)
    assert "<script>" in result["案情简介"]  # Rendering layers escape it; draft generation performs no I/O.
    assert "<script>" not in json.dumps(result["_form_drafts"], ensure_ascii=False)


def test_project_name_is_grounded_without_inventing_litigation_role_or_completion():
    result = derive(evidenced(委托人="虚构被告公司", 案由="买卖合同纠纷"))
    assert result["案件或项目名称"] == "虚构被告公司：买卖合同纠纷"
    assert "诉" not in result["案件或项目名称"] and "结案" not in result["案件或项目名称"]
    assert {ref["field"] for ref in result["_form_draft_sources"]["案件或项目名称"]} == {"委托人", "案由"}
    manual = derive(result, manual_fields={"案件或项目名称":""})
    assert manual["案件或项目名称"] == ""
    assert derive(result, blocked_fields=["委托人"])["案件或项目名称"] == ""
    too_long = derive(evidenced(委托人="虚构"*60, 案由="合同纠纷"))
    assert "案件或项目名称" not in too_long


@pytest.mark.parametrize("client_size,address_size,reference", [
    (9,8,False),
    (59,8,False),
    (30,14,True), # Full address is retained in the filing form, not truncated.
])
def test_automatic_contact_fits_original_cell_without_shortening_any_fact(client_size,address_size,reference):
    client="虚构"+"甲"*(client_size-2)
    address="虚构示例路"+"乙"*(address_size-5)
    phone="00000000000"
    fields=evidenced(委托人=client,地址=address,委托人电话=phone)
    before=deepcopy(fields)
    result=derive(fields)
    contact=result["委托人联系地址及电话"]
    assert phone in contact
    assert ('地址见立案审批表' in contact) if reference else (address in contact)
    assert client not in contact
    assert all(result[key]==before[key] for key in ("委托人","地址","委托人电话")) and fields==before
    status=result["_form_drafts"]["fields"]["委托人联系地址及电话"]
    assert status["status"]=="generated"
    assert status["reason_codes"]==(['contact_address_in_filing_form'] if reference else [])
    refs=result["_form_draft_sources"]["委托人联系地址及电话"]
    assert {ref["field"] for ref in refs}=={"地址","委托人电话"}
    assert {ref["value"] for ref in refs if ref["field"] in ("地址","委托人电话")}=={address,phone}


def test_contact_that_cannot_fit_is_explicitly_empty_and_retains_complete_source_evidence():
    address="虚构示例路"+"乙"*80
    fields=evidenced(委托人="虚构甲",地址=address,委托人电话="00000000000")
    result=derive(fields)
    assert not result.get("委托人联系地址及电话") and result["地址"]==address
    status=result["_form_drafts"]["fields"]["委托人联系地址及电话"]
    assert status["status"]=="insufficient" and "draft_too_long_for_original_cell" in status["reason_codes"]
    ref=next(ref for ref in result["_form_draft_sources"]["委托人联系地址及电话"] if ref["field"]=="地址")
    assert ref["value"]==address and address in ref["quote"]
    assert "委托人联系地址及电话" in draft_review_summary(result)["layout_review_fields"]


@pytest.mark.parametrize("manual_value",["", "人工完整联系信息"*30])
def test_automatic_contact_budget_never_rewrites_human_text_or_deliberate_clear(manual_value):
    fields=evidenced(委托人="虚构甲",地址="虚构路1号",委托人电话="00000000000")
    result=derive(fields,manual_fields={"委托人联系地址及电话":manual_value})
    assert result["委托人联系地址及电话"]==manual_value
    assert result["_form_drafts"]["fields"]["委托人联系地址及电话"]["status"]=="human_modified"


def test_old_oversized_machine_contact_is_recomputed_without_replacing_input_facts():
    import hashlib
    fields=evidenced(委托人="虚构"+"甲"*57,地址="虚构示例路"+"乙"*3,委托人电话="00000000000")
    old="；".join(label+"："+fields[key] for key,label in (("委托人","委托人"),("地址","联系地址"),("委托人电话","联系电话")))
    assert len(old)==94
    fields["委托人联系地址及电话"]=old
    fields["_form_drafts"]={"version":3,"fields":{"委托人联系地址及电话":{"status":"generated","value_digest":hashlib.sha256(old.encode()).hexdigest()}}}
    result=derive(fields)
    assert result["委托人联系地址及电话"]==fields['地址']+'；'+fields['委托人电话']
    assert all(result[key]==fields[key] for key in ("委托人","地址","委托人电话"))


@pytest.mark.parametrize("address",["虚构示例路"+"乙"*70,"虚构路\n第1栋\n第2层"])
def test_nominal_character_limit_does_not_certify_chinese_or_multiline_fit(address):
    result=derive(evidenced(委托人="虚构甲",地址=address,委托人电话="00000000000"))
    assert len(address)<90 and not result.get("委托人联系地址及电话")
    assert "draft_too_long_for_original_cell" in result["_form_drafts"]["fields"]["委托人联系地址及电话"]["reason_codes"]
    assert result["地址"]==address


def test_contact_refers_explicitly_to_complete_address_in_mandatory_filing_form():
    address="虚构示例路"+"乙"*35
    result=derive(evidenced(委托人="虚构甲",地址=address,委托人电话="00000000000"))
    assert result["委托人联系地址及电话"]=="电话：00000000000；地址见立案审批表"
    assert result["地址"]==address
    refs=result["_form_draft_sources"]["委托人联系地址及电话"]
    assert {ref["value"] for ref in refs}=={address,"00000000000"}
    assert "contact_address_in_filing_form" in result["_form_drafts"]["fields"]["委托人联系地址及电话"]["reason_codes"]


@pytest.mark.parametrize('field,template',[
    ('案情简介','立案审批表'),('法院文件清单','送达材料清单'),
    ('委托人联系地址及电话','质量监督卡'),('案件或项目名称','结案报告表'),('结案小结','结案报告表'),
])
def test_supplied_forms_do_not_create_redundant_fill_requests(field,template):
    from copy import deepcopy
    from form_drafts import draft_review_message
    fields={'_original_forms':{template:[{'file_id':'fictional','page':1,'page_end':1}]},
        field:'原提取值保留','_form_drafts':{'fields':{field:{'status':'insufficient','source_count':0}}},
        '_provenance':{field:[{'file_id':'fictional','page':1}]}}
    before=deepcopy(fields)
    message,summary=draft_review_message(fields)
    assert not message and not summary['insufficient_fields']
    assert fields==before


def test_original_notice_alone_does_not_hide_missing_quality_card_fields():
    from form_drafts import draft_review_message
    fields={'_original_form_components':{'质量监督卡':[{'component':'client_notice','file_id':'fictional','page':1}]},
        '_form_drafts':{'fields':{'委托人联系地址及电话':{'status':'insufficient'}}}}
    assert '委托人联系地址及电话' in draft_review_message(fields)[0]
    fields['_original_form_components']['质量监督卡'][0]['component']='quality_card'
    assert not draft_review_message(fields)[0]
