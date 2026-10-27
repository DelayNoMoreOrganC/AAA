"""The fixed system-form name column is not a free-form document abstract."""
from form_drafts import derive_form_drafts
from pdf_doc_locator import DocumentUnit


def draft(units, **kw):
    return derive_form_drafts({}, units, source_manifest=[{"path":"fictional.pdf", "pages":50}], **kw)


def unit(index, title):
    return DocumentUnit(index, "judgment", index, index, title,
                        source_path="fictional.pdf", confidence=.9)


def test_long_model_title_keeps_complete_name_in_source_and_short_kind_in_fixed_cell():
    original = "虚构人民法院关于虚构当事人与另一虚构当事人的买卖合同纠纷民事判决书"
    result = draft([unit(0,original)])
    assert result["法院文件清单"] == "《判决书》（原材料第1页）"
    refs = result["_form_draft_sources"]["法院文件清单"]
    assert len(refs) == 1 and refs[0]["document_title"] == original and refs[0]["page"] == 1
    assert "document_titles_shortened_with_full_source_retained" in result["_form_drafts"]["fields"]["法院文件清单"]["reason_codes"]


def test_many_documents_group_without_dropping_a_source_or_changing_human_value():
    units = [unit(i,"民事判决书") for i in range(25)]
    result = draft(units)
    assert result["法院文件清单"] == "《判决书》（25份，详见本卷）"
    assert len(result["法院文件清单"]) <= 26
    assert len(result["_form_draft_sources"]["法院文件清单"]) == 25
    assert {ref["page"] for ref in result["_form_draft_sources"]["法院文件清单"]} == set(range(1,26))
    manual = "虚构人工完整描述" * 10
    assert draft(units, manual_fields={"法院文件清单":manual})["法院文件清单"] == manual
