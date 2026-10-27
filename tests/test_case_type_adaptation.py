# -*- coding: utf-8 -*-
import pytest
import fitz

import archive_pipeline as ap
from archive_pipeline import detect_case_type, normalize_fields
from document_segmenter import DOC_TYPE_CONTRACT, DOC_TYPE_DEFAULT, DOC_TYPE_JUDGMENT, DocumentSource
from field_mapping import _build_case_brief, _build_case_project_name, expand_fields_for_template
from field_merger import merge_partial_fields
import pdf_doc_locator as pdl


def test_detects_criminal_case_from_legal_roles():
    text = "某人民检察院起诉书 公诉机关某市人民检察院 被告人张三涉嫌诈骗罪"
    assert detect_case_type(text) == "criminal"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("民事判决书 原告甲公司 被告乙公司 买卖合同纠纷", "civil"),
        ("刑事判决书 公诉机关某检察院 被告人张三 辩护人李律师", "criminal"),
        ("行政判决书 原告甲公司 被告某区市场监督管理局 被诉行政处罚", "admin"),
        ("非诉讼法律事务委托合同 专项法律服务 法律尽职调查", "nonlit"),
        ("常年法律顾问合同 顾问单位甲公司 合同审查与法律咨询", "counsel"),
    ],
)
def test_detect_case_type_matrix(text, expected):
    assert detect_case_type(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("中华人民共和国某区人民法院\n刑事判决书\n公诉机关某区人民检察院\n被告人张三", "criminal"),
        ("某市中级人民法院\n行政判决书\n原告甲公司\n被告某区人民政府", "admin"),
        ("专项法律服务合同\n委托事项：股权收购法律尽职调查", "nonlit"),
    ],
)
def test_case_type_detection_from_real_pdf_text_layer(tmp_path, text, expected):
    pdf_path = tmp_path / f"{expected}.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontname="china-s", fontsize=12)
    doc.save(pdf_path)
    doc.close()

    with fitz.open(pdf_path) as parsed:
        extracted = "\n".join(page.get_text() for page in parsed)
    assert detect_case_type(extracted) == expected


def test_criminal_judgment_page_routes_to_judgment_slot():
    doc_type, _title = pdl._classify_page_prefix("刑事判决书\n（2025）粤0101刑初123号\n被告人张三")
    assert doc_type == "judgment"


def test_criminal_normalization_preserves_roles_and_case_number():
    raw = {
        "被告人": "张三",
        "公诉机关": "某市人民检察院",
        "辩护人": "李律师",
        "罪名": "诈骗罪",
        "案号": "（2025）粤0101刑初123号",
        "审判法院": "某市某区人民法院",
        "结案小结": "法院判决被告人张三犯诈骗罪，判处有期徒刑三年。",
    }
    fields = normalize_fields(raw, case_type="criminal")
    assert fields["案件类别"] == "刑事"
    assert fields["当事人"] == "张三"
    assert fields["对方当事人"] == "某市人民检察院"
    assert fields["承办律师"] == "李律师"
    assert fields["案由"] == "诈骗罪"
    assert fields["法院收案号"] == "（2025）粤0101刑初123号"
    assert "执行终本" not in fields["结案小结"]


def test_criminal_brief_never_uses_loan_template():
    fields = {
        "案件类别": "刑事",
        "委托人": "张某父亲",
        "被告人": "张某",
        "罪名": "危险驾驶罪",
    }
    brief = _build_case_brief(fields)
    assert "危险驾驶罪" in brief
    assert "贷款" not in brief
    assert _build_case_project_name(fields) == "被告人张某危险驾驶罪一案"


def test_merger_does_not_force_civil_for_criminal():
    partials = {
        "indictment": {"被告人": "王某", "罪名": "盗窃罪"},
        "judgment": {"结案小结": "判处有期徒刑一年。"},
    }
    merged = merge_partial_fields(partials, case_type="criminal")
    assert merged["案件类别"] == "刑事"
    assert merged["被告人"] == "王某"
    assert merged["罪名"] == "盗窃罪"


@pytest.mark.parametrize(
    ("case_type", "raw", "expected"),
    [
        (
            "civil",
            {"原告": "甲公司", "被告": "乙公司", "案由": "买卖合同纠纷"},
            {"案件类别": "民事", "当事人": "甲公司", "对方当事人": "乙公司"},
        ),
        (
            "admin",
            {"行政相对人": "甲公司", "行政机关": "某区市场监管局", "案由": "行政处罚"},
            {"案件类别": "行政", "当事人": "甲公司", "对方当事人": "某区市场监管局"},
        ),
        (
            "nonlit",
            {"项目委托人": "甲公司", "项目事项": "股权收购尽职调查", "服务成果": "已出具尽职调查报告"},
            {"案件类别": "非诉", "委托人": "甲公司", "案由": "股权收购尽职调查", "结案小结": "已出具尽职调查报告"},
        ),
        (
            "counsel",
            {"顾问单位": "甲公司", "顾问事项": "合同审查与法律咨询", "服务成果": "完成年度合同审查"},
            {"案件类别": "法律顾问", "委托人": "甲公司", "案由": "合同审查与法律咨询", "结案小结": "完成年度合同审查"},
        ),
    ],
)
def test_normalize_fields_matrix(case_type, raw, expected):
    fields = normalize_fields(raw, case_type=case_type)
    for key, value in expected.items():
        assert fields[key] == value


@pytest.mark.parametrize(
    ("case_type", "doc_type", "prompt_marker", "result"),
    [
        ("civil", DOC_TYPE_DEFAULT, "民事案件文档分析助手", {"案由": "劳动争议"}),
        ("criminal", DOC_TYPE_JUDGMENT, "刑事裁判文书分析助手", {"被告人": "张三", "罪名": "诈骗罪"}),
        ("admin", DOC_TYPE_JUDGMENT, "行政裁判文书分析助手", {"行政相对人": "甲公司", "行政机关": "某区政府"}),
        ("nonlit", DOC_TYPE_CONTRACT, "非诉专项法律服务合同分析助手", {"项目委托人": "甲公司", "项目事项": "尽职调查"}),
        ("counsel", DOC_TYPE_CONTRACT, "常年法律顾问合同分析助手", {"顾问单位": "甲公司", "顾问事项": "合同审查"}),
    ],
)
def test_segmented_extraction_selects_case_specific_prompt(monkeypatch, case_type, doc_type, prompt_marker, result):
    prompts = []

    def fake_chat(user_content, system_content, **_kwargs):
        prompts.append(user_content)
        return result

    monkeypatch.setattr(ap, "_deepseek_chat", fake_chat)
    merged = ap.extract_fields_segmented(
        {doc_type: "示例法律文档正文" * 20},
        case_type=case_type,
        log=lambda _msg: None,
    )
    assert any(prompt_marker in prompt for prompt in prompts)
    assert merged["案件类别"] == ap.CASE_TYPE_LABELS[case_type]
    for key, value in result.items():
        assert merged[key] == value


def test_nonlit_remaining_work_records_are_not_dropped(monkeypatch):
    calls = []

    def fake_chat(user_content, system_content, **_kwargs):
        calls.append(user_content)
        return {"服务成果": "已出具法律意见书"}

    monkeypatch.setattr(ap, "_deepseek_chat", fake_chat)
    result = ap.extract_fields_segmented(
        {"legal_work": "法律意见书与项目工作记录" * 20},
        case_type="nonlit",
        log=lambda _msg: None,
    )
    assert calls
    assert "非诉讼法律事务文档分析助手" in calls[0]
    assert result["服务成果"] == "已出具法律意见书"


@pytest.mark.parametrize("case_type", ["civil", "criminal", "admin", "nonlit", "counsel"])
def test_archive_analysis_passes_explicit_case_type_through_pipeline(monkeypatch, tmp_path, case_type):
    source_path = str(tmp_path / f"{case_type}.pdf")
    sample_text = {
        "civil": "民事判决书 原告甲 被告乙 买卖合同纠纷",
        "criminal": "刑事判决书 公诉机关某检察院 被告人张三",
        "admin": "行政判决书 行政相对人甲公司 行政机关某区政府",
        "nonlit": "非诉讼法律事务 股权收购尽职调查",
        "counsel": "常年法律顾问合同 顾问单位甲公司",
    }[case_type]
    seen = []

    monkeypatch.setattr(
        ap,
        "ingest_archive_sources",
        lambda *_args, **_kwargs: (
            {source_path: sample_text},
            {source_path: [sample_text]},
            {},
            1,
            0,
        ),
    )
    monkeypatch.setattr(ap.pdl, "build_units_from_sources", lambda *_args, **_kwargs: [])

    def fake_extract(_text, segmented=None, log=print, case_type=None):
        seen.append(case_type)
        return {"案由": "测试事项", "委托人": "甲"}

    monkeypatch.setattr(ap, "extract_fields_auto", fake_extract)
    analysis = ap._analyze_archive_impl(
        case_type,
        config={"output": {"preview_only": True}},
        sources=[DocumentSource(path=source_path, doc_type="default")],
        log=lambda _msg: None,
    )
    assert seen == [case_type]
    assert analysis.case_type == case_type
    assert analysis.fields["案件类别"] == ap.CASE_TYPE_LABELS[case_type]
    assert analysis.generated_templates == {}


def test_criminal_fields_fill_legacy_form_slots_with_criminal_roles():
    mapped = expand_fields_for_template(
        "档案卷宗",
        {
            "案件类别": "刑事",
            "委托人": "张三之父",
            "被告人": "张三",
            "公诉机关": "某区人民检察院",
            "辩护人": "李律师",
            "罪名": "诈骗罪",
            "审判法院": "某区人民法院",
        },
    )
    assert mapped["民事"] == "刑事"
    assert mapped["判决书中的原告"] == "张三"
    assert mapped["判决书中的被告"] == "某区人民检察院"
    assert mapped["判决书原告的委托诉讼代理人"] == "李律师"
    assert mapped["判决书内确认的案由（被告主体信息后的下一段会注明原告XXX诉被告XXXAAA一案，AAA就是案由）"] == "诈骗罪"


def test_nonlit_fields_fill_project_name_and_service_result_slots():
    mapped = expand_fields_for_template(
        "结案报告表",
        {
            "案件类别": "非诉",
            "项目委托人": "甲公司",
            "项目事项": "股权收购尽职调查",
            "服务成果": "已出具尽职调查报告",
        },
    )
    assert mapped["委托代理合同中委托人"] == "甲公司"
    assert mapped["判决书内的（原告XXX诉被告XXXAAA一案）"] == "甲公司股权收购尽职调查项目"
    assert mapped["《律师业务卷宗（银行案)》sheet1的I列，根据判决书、执行裁定书的内容，匹配最相近的选项填写"] == "已出具尽职调查报告"
