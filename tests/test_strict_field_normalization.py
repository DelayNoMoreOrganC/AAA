"""Fictional evidence only: source roles are not the firm's represented side."""
from copy import deepcopy

import pytest

import archive_pipeline as pipeline
from document_segmenter import DocumentSource
from field_mapping import _build_case_project_name
from field_sanitize import enrich_party_fields
from form_drafts import derive_form_drafts


def strict(raw, kind="civil"):
    return pipeline.normalize_fields(raw, case_type=kind, strict_evidence=True)


@pytest.mark.parametrize("raw", [None, {}])
def test_strict_empty_extraction_has_current_version_but_no_invented_fact(raw):
    from case_outcome import STRICT_EVIDENCE_VERSION
    result = strict(raw)
    assert result["_field_normalization_version"] == STRICT_EVIDENCE_VERSION
    assert result["_outcome_warnings"]
    assert set(result) == {"案件类别", "_field_normalization_version", "_outcome_warnings"}
    assert pipeline.normalize_fields(raw,case_type="civil") == {}


@pytest.mark.parametrize("client", ["虚构原告公司", "虚构被告公司"])
def test_court_roles_do_not_assign_represented_or_opposing_side(client):
    raw = {"委托人":client, "原告":"虚构原告公司", "被告":"虚构被告公司",
           "判决书上代理律师":"虚构对方律师", "案由":"买卖合同纠纷"}
    saved = deepcopy(raw)
    result = strict(raw)
    assert all(result[key] == value for key, value in raw.items())
    assert not any(result.get(key) for key in ("当事人","对方当事人","承办律师","案件或项目名称"))
    assert raw == saved


@pytest.mark.parametrize("kind,raw", [
    ("criminal", {"委托人":"虚构被害人", "当事人":"虚构被害人", "被告人":"虚构被告人", "罪名":"诈骗罪", "案由":"诈骗案"}),
    ("admin", {"委托人":"虚构行政机关", "当事人":"虚构行政机关", "原告":"虚构公民", "行政相对人":"虚构公民", "被诉行政机关":"虚构行政机关", "案由":"行政许可争议"}),
    ("civil", {"委托人":"虚构被告", "当事人":"虚构被告", "对方当事人":"虚构原告", "原告":"虚构原告", "被告":"虚构被告", "案由":"买卖合同纠纷"}),
])
def test_explicit_represented_party_is_preserved_without_a_fabricated_case_name(kind,raw):
    result = strict(raw,kind)
    assert all(result[key] == value for key,value in raw.items())
    assert "案件或项目名称" not in result
    assert ("对方当事人" in result) == ("对方当事人" in raw)


@pytest.mark.parametrize("kind", ["civil","admin","criminal","nonlit","counsel","arbitration","consultation"])
def test_client_alone_does_not_silently_populate_a_party_slot(kind):
    result = strict({"委托人":"虚构主体"},kind)
    assert result["委托人"] == "虚构主体"
    assert not any(result.get(key) for key in ("当事人","对方当事人","原告","被告","案件或项目名称"))


def test_court_filing_contract_date_and_combined_contact_are_not_receipt_or_phone_aliases():
    raw = {"立案日期":"2026年1月2日", "委托代理合同中落款日期":"2026年1月1日",
           "委托人联系地址及电话":"虚构主体；虚构地址；联系电话00000000000"}
    result = strict(raw)
    assert all(result[key] == value for key,value in raw.items())
    assert "收案日期" not in result and "委托人电话" not in result


def test_explicit_values_and_deliberate_blanks_survive_conflicting_aliases_and_sanitization():
    raw = {"委托人":"", "委托人名称":"旧虚构委托人", "当事人":"", "原告":"虚构原告",
           "对方当事人":"", "被告":"虚构被告", "承办律师":"", "代理律师":"其他律师",
           "收案日期":"", "立案日期":"2026-01-02", "案件或项目名称":"人工短名", "案由":""}
    result = strict(raw)
    assert all(result[key] == value for key,value in raw.items())
    raw["案件或项目名称"] = ""
    assert strict(raw)["案件或项目名称"] == ""


def test_strict_helpers_do_not_reparse_combined_party_or_rewrite_explicit_project_name():
    raw = {"当事人":"原告：虚构甲，被告：虚构乙", "案件或项目名称":"人工短名"}
    assert enrich_party_fields(raw, strict_evidence=True) == raw
    assert _build_case_project_name(raw, strict_evidence=True) == "人工短名"
    assert _build_case_project_name({"当事人":"虚构被害人","案件类别":"刑事","案由":"诈骗罪"}, strict_evidence=True) == ""


def test_legacy_cli_default_still_supports_its_old_slot_equivalences():
    result = pipeline.normalize_fields({"原告":"虚构甲","被告":"虚构乙","立案日期":"2026-01-02"},case_type="civil")
    assert result["当事人"] == "虚构甲" and result["对方当事人"] == "虚构乙"
    assert result["收案日期"] == "2026-01-02"


@pytest.mark.parametrize("kind,other_number", [
    ("civil", "（2024）粤0604民初999号"),
    ("admin", "（2024）粤0604行初999号"),
    ("criminal", "（2024）粤0604刑初999号"),
])
@pytest.mark.parametrize("numbers", [{}, {"案号":"", "法院收案号":""}])
def test_strict_case_numbers_are_not_backfilled_from_another_case_in_full_text(kind, other_number, numbers):
    raw = {"委托人":"虚构委托人", **numbers}
    text = f"证据目录：以下为另案参考资料。\n判决书\n{other_number}\n非本案案号。"
    result = pipeline.normalize_fields(raw, pdf_text=text, case_type=kind, strict_evidence=True)
    assert {key:result[key] for key in ("案号", "法院收案号") if key in result} == numbers


@pytest.mark.parametrize("kind", ["civil", "admin", "criminal", "nonlit", "counsel", "arbitration", "consultation"])
@pytest.mark.parametrize("numbers", [
    {"案号":"（2024）粤0604民初100号"},
    {"法院收案号":"（2024）粤0604民初100号"},
    {"案号":"", "法院收案号":"（2024）粤0604民初100号"},
    {"案号":"（2024）粤0604民初100号", "法院收案号":""},
    {"案号":"（2024）粤0604民初100号", "法院收案号":"（2025）粤0604执200号"},
    {"案号":"（2024）粤0604民初100号、（2024）粤0604民初101号"},
    {"案号":"  (2024) 粤 0604 民初 100 号  "},
])
def test_strict_case_numbers_keep_each_adopted_value_and_its_own_key(kind, numbers):
    raw = {"委托人":"虚构委托人", **numbers}
    saved = deepcopy(raw)
    text = "另案参考民事判决书\n（2024）粤0604民初999号\n不属于本案。"
    result = pipeline.normalize_fields(raw, pdf_text=text, case_type=kind, strict_evidence=True)
    assert {key:result[key] for key in ("案号", "法院收案号") if key in result} == numbers
    assert raw == saved


def test_legacy_cli_case_number_full_text_fallback_is_unchanged():
    number = "（2024）粤0604民初999号"
    result = pipeline.normalize_fields({"委托人":"虚构委托人"},
        pdf_text=f"民事判决书\n{number}\n", case_type="civil")
    assert result["案号"] == number and result["法院收案号"] == number


@pytest.mark.parametrize("mode", ["workstation_agent", "visual_agent"])
@pytest.mark.parametrize("kind,client,matter", [
    ("civil","虚构原告公司","买卖合同纠纷"),
    ("civil","虚构被告公司","买卖合同纠纷"),
    ("criminal","虚构被害人","诈骗案"),
    ("admin","虚构行政机关","行政许可争议"),
])
def test_actual_workstation_branches_defer_project_draft_until_evidence_is_available(monkeypatch, mode, kind, client, matter):
    import workstation_agent
    import visual_archive_agent
    path = "fictional-source.pdf"
    raw = {"委托人":client, "案由":matter}
    provenance = {key:[{"method":"visual_agent_local_evidence" if mode=="visual_agent" else "local_agent",
        "value":value,"quote":f"{key}：{value}","source_path":path,"page":1}] for key,value in raw.items()}
    metadata = {"_provenance":provenance}
    text = "\n".join(f"{key}：{value}" for key,value in raw.items())
    monkeypatch.setattr(pipeline,"ingest_archive_sources",lambda *a,**kw:({path:text},{path:[text]}, {},0,0))
    monkeypatch.setattr(pipeline.pdl,"build_units_from_sources",lambda *a,**kw:[])
    monkeypatch.setattr(workstation_agent,"extract_with_agent",lambda *a,**kw:(dict(raw),deepcopy(metadata)))
    monkeypatch.setattr(visual_archive_agent,"analyze_visual_sources",lambda *a,**kw:([],dict(raw),deepcopy(metadata),{path:[text]}))
    result = pipeline.analyze_archive(kind,sources=[DocumentSource(path,"default")],
        config={"extraction":{"mode":mode},"output":{"preview_only":True}},log=lambda _:None)
    assert "案件或项目名称" not in result.fields
    assert "当事人" not in result.fields and "对方当事人" not in result.fields
    manifest = [{"path":path,"file_id":"fictional","pages":1}]
    drafted = derive_form_drafts(result.fields,[],source_manifest=manifest)
    assert drafted["案件或项目名称"] == f"{client}：{matter}"
    assert drafted["_form_drafts"]["fields"]["案件或项目名称"]["status"] == "generated"
    conflicted = deepcopy(result.fields)
    conflicted["_field_conflicts"] = [{"field":"委托人","values":[client,"另一虚构主体"]}]
    assert "案件或项目名称" not in derive_form_drafts(conflicted,[],source_manifest=manifest)
    manual = derive_form_drafts(result.fields,[],source_manifest=manifest,manual_fields={"案件或项目名称":""})
    assert manual["案件或项目名称"] == ""


@pytest.mark.parametrize("mode", ["workstation_agent", "visual_agent"])
@pytest.mark.parametrize("kind,source_type,source,accepted", [
    ("civil", "judgment", "民事判决书\n原告诉称：请求被告偿还虚构借款三万元。尚未提供裁判主文。", {}),
    ("admin", "ruling", "行政裁定书\n当事人援引另案裁定如下：终结该案审查。\n本案尚待处理。", {}),
    ("civil", "execution", "申请执行书\n申请强制执行虚构借款五万元，尚未受偿。", {}),
    ("civil", "judgment", "判决如下：支付本金五万元；但已还款部分应予扣除。", {"审（办）结果":"判决如下：支付本金五万元；但已还款部分应予扣除。"}),
    ("civil", "execution", "执行申请书\n申请调查财产。", {"结案小结":"", "审（办）结果":""}),
    ("criminal", "judgment", "刑事判决书\n裁判主文。", {"结案小结":"人工保留完整裁判内容：" + "虚构金额、义务及条件说明；" * 20 + "但未认定被害人已实际获赔。"}),
])
def test_workstation_outcomes_only_use_accepted_values_not_classified_full_text(monkeypatch, mode, kind, source_type, source, accepted):
    import workstation_agent
    import visual_archive_agent
    from case_outcome import OUTCOME_FIELDS, STRICT_EVIDENCE_VERSION
    from pdf_doc_locator import DocumentUnit
    path = "fictional-outcome.pdf"
    unit = DocumentUnit(0,source_type,0,0,catalog_seq=15 if source_type=="execution" else 14,
        source_path=path,confidence=0.3)
    raw = {"委托人":"虚构委托人", **accepted}
    metadata = {"_provenance":{key:[{"method":"local_agent","value":value,"source_path":path,"page":1}]
        for key,value in accepted.items() if value}}
    monkeypatch.setattr(pipeline,"ingest_archive_sources",lambda *a,**kw:({path:source},{path:[source]}, {},0,0))
    monkeypatch.setattr(pipeline.pdl,"build_units_from_sources",lambda *a,**kw:[unit])
    monkeypatch.setattr(workstation_agent,"extract_with_agent",lambda *a,**kw:(dict(raw),deepcopy(metadata)))
    monkeypatch.setattr(visual_archive_agent,"analyze_visual_sources",lambda *a,**kw:([unit],dict(raw),deepcopy(metadata),{path:[source]}))
    def legacy_forbidden(*args, **kwargs):
        raise AssertionError("strict workstation must not invoke legacy outcome synthesis")
    for helper in ("build_outcome_from_units","ensure_outcome_covers_execution","unify_case_outcome_fields","detect_outcome_warnings"):
        monkeypatch.setattr(pipeline,helper,legacy_forbidden)
    result = pipeline.analyze_archive(kind,sources=[DocumentSource(path,"default")],
        config={"extraction":{"mode":mode},"output":{"preview_only":True}},log=lambda _:None)
    for key in OUTCOME_FIELDS:
        assert (key in result.fields) == (key in accepted)
        if key in accepted:
            assert result.fields[key] == accepted[key]
    assert result.fields["_provenance"] == metadata["_provenance"]
    assert result.fields["_field_normalization_version"] == STRICT_EVIDENCE_VERSION
    assert bool(result.outcome_warnings) == (not any(accepted.values()))


@pytest.mark.parametrize("raw", [
    {"法院文件清单":"未收到判决书，也未向委托人送达裁定书。"},
    {"法院文件清单":"", "法院文书":"旧别名中的判决书"},
    {"法院文书":"法院尚未出具执行裁定书。"},
    {"法院文件清单":"甲材料\n乙材料\n" + "虚构完整标题" * 30},
])
def test_strict_document_inventory_preserves_negative_statement_alias_and_blank(monkeypatch, raw):
    def forbidden(*args, **kwargs):
        raise AssertionError("accepted source values must not enter legacy inventory parsing")
    monkeypatch.setattr(pipeline,"parse_court_document_list",forbidden)
    result = strict(raw)
    assert all(result[key] == value for key,value in raw.items())
    for key in ("法院文件清单", "法院文书"):
        assert (key in result) == (key in raw)
