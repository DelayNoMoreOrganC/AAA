"""Five-business gaps, exercised with invented PDFs and mock model actions."""
from copy import deepcopy

import pytest

import archive_catalog as catalog
from fact_evidence import validate_fact
from page_classifier import collect_low_confidence_units
from pdf_archive_merger import _catalog_item_matches_unit
import visual_archive_agent as agent
from tests.test_visual_document_workflow import (CONFIG, classified, coverage, extracted,
    mock_client, offline_only, pdf)


BUSINESS_TYPES = [
    ("criminal", "meeting_record", 7),
    ("nonlit", "legal_work", 7),
    ("counsel", "client_intro", 3),
    ("counsel", "work_record", 5),
    ("counsel", "agreement_status", 6),
]


@pytest.mark.parametrize("case_type,kind,seq", BUSINESS_TYPES)
def test_known_business_document_crosses_batch_into_its_existing_slot(tmp_path, monkeypatch, case_type, kind, seq):
    source = pdf(tmp_path, 5)
    original = open(source.path, "rb").read()
    client = mock_client(monkeypatch, lambda ctx, *_:
                         classified(ctx, kind=kind, stage="other")
                         if ctx["phase"] == "classification" else extracted(ctx))
    units, fields, metadata, _ = agent.analyze_visual_sources([source], case_type, deepcopy(CONFIG), log=lambda _: None)
    assert len(units) == 1 and units[0].doc_type == kind and units[0].catalog_seq == seq
    assert (units[0].start_page, units[0].end_page) == (0, 4)
    assert len(coverage(units)) == 5 and all(count == 1 for count in coverage(units).values())
    matches = [item for item in catalog.get_catalog(case_type)
               if _catalog_item_matches_unit(item, units[0], catalog.MANUAL_KEY_DOC_TYPES)]
    assert [item.seq for item in matches] == [seq]
    assert not collect_low_confidence_units(units)
    assert fields == {} and metadata["_provenance"] == {}
    assert metadata["_agent_summary"]["accepted_fact_count"] == 0
    assert client.metrics["model_requests"] == 3
    assert open(source.path, "rb").read() == original


def test_invented_business_type_is_still_rejected_with_original_bounded_budget(tmp_path, monkeypatch):
    source = pdf(tmp_path)
    client = mock_client(monkeypatch, lambda ctx, *_: classified(ctx, kind="invented_legal_certificate"))
    with pytest.raises(agent.GlmVisionError, match="操作上限"):
        agent.analyze_visual_sources([source], "nonlit", deepcopy(CONFIG), log=lambda _: None)
    assert client.metrics["model_requests"] == 5


@pytest.mark.parametrize("quote,value", [
    ("罪名：盗窃罪。", "盗窃罪"),
    ("项目事项：股权收购尽职调查。", "股权收购尽职调查"),
    ("顾问事项：劳动用工合规。", "劳动用工合规"),
])
def test_business_matter_label_proves_only_the_neutral_matter_field(quote, value):
    assert validate_fact("案由", value, quote, quote)
    assert not validate_fact("结案小结", value, quote, quote)


@pytest.mark.parametrize("quote", [
    "本所接受委托并指派李某律师担任本案辩护人。",
    "本所指派本案辩护人：李某。",
    "委托方聘请虚构星河律师事务所指派李某律师担任顾问律师。",
    "本所委派项目律师：李某。",
])
def test_special_lawyer_label_requires_explicit_engagement_and_law_firm_assignment(quote):
    assert validate_fact("承办律师", "李某", quote, quote)


@pytest.mark.parametrize("quote,page", [
    ("辩护人：李某，虚构星河律师事务所律师。", None),
    ("顾问律师：李某。", None),
    ("项目律师：李某。", None),
    ("本所指派李某律师担任本案辩护人。", "本所拟指派李某律师担任本案辩护人。"),
    ("本所指派李某律师担任本案辩护人", "对方称本所指派李某律师担任本案辩护人。"),
    ("委托方聘请虚构星河律师事务所指派李某律师担任顾问律师", "对方委托方聘请虚构星河律师事务所指派李某律师担任顾问律师。"),
    ("本所委派李某律师担任项目律师", "参考案例：本所委派李某律师担任项目律师。"),
    ("本所委派李某律师担任项目律师", "参考案例。\n本所委派李某律师担任项目律师。"),
    ("本所指派李某律师担任本案辩护人", "请在模板填写本所指派李某律师担任本案辩护人。"),
    ("本所指派李某律师担任本案辩护人", "本所指派李某律师担任本案辩护人是否属实？"),
    ("辩护人：李某", "本所指派陈某律师承办。辩护人：李某，虚构另一律师事务所律师。"),
])
def test_special_lawyer_is_not_inferred_from_unbound_opposing_proposed_or_reference_roles(quote, page):
    assert not validate_fact("承办律师", "李某", quote, page or quote)


@pytest.mark.parametrize("label,value", [("罪名", "盗窃罪"), ("项目事项", "股权收购尽职调查"), ("顾问事项", "劳动用工合规")])
def test_proposed_or_unrelated_business_matter_does_not_become_a_fact(label, value):
    assert not validate_fact("案由", value, "拟" + label + "：" + value, "拟" + label + "：" + value)
    quote = f"材料名称：{value}；正文仅提及{label}。"
    assert not validate_fact("案由", value, quote, quote)


BUSINESS_HEADINGS = [
    ("criminal", "meeting_record", 7, "会见笔录", "会见时间：虚构时间；被会见人：虚构当事人；律师记录了问答内容。"),
    ("nonlit", "legal_work", 7, "法律意见书", "本所针对本项目事项出具审查意见和建议，仅供虚构测试。"),
    ("counsel", "client_intro", 3, "聘方基本情况", "顾问单位：虚构公司；经营范围：虚构服务；住所：虚构地址。"),
    ("counsel", "work_record", 5, "法律顾问工作记录", "顾问事项：虚构合同审查；本所记录咨询问题及建议。"),
    ("counsel", "agreement_status", 6, "顾问协议存续情况说明", "法律顾问协议的服务期限及存续情况见本说明；不说明付款或实际履行。"),
]


@pytest.mark.parametrize("case_type,kind,seq,title,body", BUSINESS_HEADINGS)
def test_local_title_review_uses_business_context_and_preserves_actual_page_and_fact_boundaries(tmp_path, monkeypatch, case_type, kind, seq, title, body):
    source = pdf(tmp_path, texts=[title + "\n" + body])
    mock_client(monkeypatch, lambda ctx, *_: classified(ctx, kind="evidence")
                if ctx["phase"] == "classification" else extracted(ctx))
    config = deepcopy(CONFIG)
    config["vision"]["title_review_budget"] = 1
    units, fields, metadata, _ = agent.analyze_visual_sources([source], case_type, config, log=lambda _: None)
    assert len(units) == 1 and (units[0].doc_type, units[0].catalog_seq) == (kind, seq)
    assert (units[0].start_page, units[0].end_page) == (0, 0)
    assert fields == {} and metadata["_provenance"] == {}
    assert metadata["_visual_classification_review"][0]["independent_title_verified"] is True
    assert not collect_low_confidence_units(units)


def test_same_legal_opinion_title_does_not_force_nonlitigation_slot_on_counsel():
    from document_title_review import title_evidence
    page = "法律意见书\n本所就顾问单位咨询事项进行审查并提出法律建议。"
    assert title_evidence(page, case_type="nonlit")["doc_type"] == "legal_work"
    assert title_evidence(page, case_type="counsel")["doc_type"] == "work_record"
    assert title_evidence(page, case_type="civil") is None


@pytest.mark.parametrize("case_type,kind,seq,title,body", BUSINESS_HEADINGS)
def test_business_title_alone_or_cited_in_evidence_does_not_prove_that_document(case_type, kind, seq, title, body):
    from document_title_review import title_evidence
    assert title_evidence(title, case_type=case_type)["verified"] is False
    assert title_evidence("证据目录\n" + title + "\n" + body, case_type=case_type)["doc_type"] == "evidence"
    assert title_evidence("关于《" + title + "》的说明\n" + body, case_type=case_type) is None


@pytest.mark.parametrize("case_type,kind,matter_label,matter", [
    ("criminal", "meeting_record", "罪名", "盗窃罪"),
    ("nonlit", "legal_work", "项目事项", "股权收购尽职调查"),
    ("counsel", "work_record", "顾问事项", "劳动用工合规"),
])
def test_business_field_candidates_survive_actual_local_verification_and_strict_normalization(tmp_path, monkeypatch, case_type, kind, matter_label, matter):
    from archive_pipeline import normalize_fields
    matter_quote = matter_label + "：" + matter + "。"
    lawyer_quote = "本所委派项目律师：李某。" if case_type != "criminal" else "本所指派本案辩护人：李某。"
    source = pdf(tmp_path, texts=[matter_quote + "\n" + lawyer_quote])
    facts = [{"field": field, "value": value, "page_id": "f1p1", "quote": quote}
             for field, value, quote in [("案由", matter, matter_quote), ("承办律师", "李某", lawyer_quote)]]
    mock_client(monkeypatch, lambda ctx, *_: classified(ctx, kind=kind, stage="other")
                if ctx["phase"] == "classification" else extracted(ctx, facts))
    units, fields, metadata, _ = agent.analyze_visual_sources([source], case_type, deepcopy(CONFIG), log=lambda _: None)
    assert fields == {"案由": matter, "承办律师": "李某"}
    assert metadata["_fact_review"] == []
    for fact in facts:
        ref = metadata["_provenance"][fact["field"]][0]
        assert (ref["source_path"], ref["page"], ref["quote"]) == (source.path, 1, fact["quote"])
    normalized = normalize_fields(fields, case_type=case_type, strict_evidence=True)
    assert all(normalized[key] == value for key, value in fields.items())
    assert not any(normalized.get(key) for key in ("原告", "被告", "对方当事人", "结案小结", "审（办）结果"))
