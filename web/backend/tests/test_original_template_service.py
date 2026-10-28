"""Original blank templates and fictional data only; no Word/model/network."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile
import json
import os
import threading
import time
import traceback

import fitz
import pytest
from lxml import etree as ET

from app.services import original_template_service as service
from app.services import browser_pdf_service


@pytest.mark.parametrize("name,category", [
    ("立案审批表", "民事"), ("送达材料清单", "民事"), ("档案卷宗", "民事"),
    ("档案卷宗", "非诉"), ("结案报告表", "民事"), ("质量监督卡", "民事"),
])
def test_original_package_and_fixed_frame_structure_are_preserved(tmp_path, name, category):
    fields = {"案件类别": category, "委托人": "虚构甲", "法院文件清单": "虚构裁定书"}
    meta = service.template_metadata(name, fields)
    output = service.fill_original_docx(name, fields, "虚构律所", tmp_path / "filled.docx",
        derived_output={"volume_page_count": 123})
    source = service.TEMPLATES / "word-converted" / (service.FILES[meta["template_key"]] + ".docx")
    with ZipFile(source) as original, ZipFile(output) as filled:
        assert original.namelist() == filled.namelist()
        assert service.frame_signature(original.read("word/document.xml")) == service.frame_signature(filled.read("word/document.xml"))
        for key in original.namelist():
            if key not in ("word/document.xml", "word/settings.xml"):
                if key.startswith('word/footer') and key.endswith('.xml'):
                    assert service._without_template_page_fields(original.read(key)) == filled.read(key)
                else:
                    assert original.read(key) == filled.read(key)
        document = ET.fromstring(filled.read("word/document.xml"))
        heights = document.xpath("//w:trPr/w:trHeight", namespaces=service.NS)
        assert heights and all(item.get(service._tag("hRule")) == "exact" for item in heights)
        geometry = json.loads((service.TEMPLATES / "layout-geometry.json").read_text(encoding="utf8"))[meta["template_key"]]
        assert [int(item.get(service._tag("val"))) for item in heights] == geometry["native_row_heights_twips"]
    assert meta["row_height_policy"] == "freeze_native_reference" and meta["reference_pdf_sha256"]
    assert meta["filled_cell_typography"] == "songti_12pt_field_spacing_v2"


def test_filled_fixed_cells_normalize_strut_and_paragraph_mark_without_losing_labels(tmp_path):
    output = service.fill_original_docx("立案审批表", {"委托人":"虚构"+"甲"*18,
        "地址":"虚构示例路"+"乙"*22, "案情简介":"完整虚构说明"}, "虚构律所", tmp_path / "form.docx")
    with ZipFile(output) as package:root=ET.fromstring(package.read("word/document.xml"))
    for phrase in ("虚构"+"甲"*18, "虚构示例路"+"乙"*22, "完整虚构说明"):
        paragraph=root.xpath("//w:p[w:r/w:t[text()=$text]]", namespaces=service.NS, text=phrase)[0]
        spacing=paragraph.find(service._tag("pPr")+"/"+service._tag("spacing"))
        assert {key:spacing.get(service._tag(key)) for key in ("line","lineRule","before","after")} == {
            "line":"360" if phrase == "完整虚构说明" else "280", "lineRule":"exact", "before":"0", "after":"0"}
        for properties in paragraph.xpath("./w:r/w:rPr|./w:pPr/w:rPr", namespaces=service.NS):
            assert properties.find(service._tag("sz")).get(service._tag("val")) == "24"
            assert properties.find(service._tag("szCs")).get(service._tag("val")) == "24"
            assert properties.find(service._tag("rFonts")).get(service._tag("eastAsia")) == "宋体"
    assert "案情简介：" in root.xpath("//w:t/text()", namespaces=service.NS)


@pytest.mark.parametrize('category',['民事','行政','刑事','非诉','法律顾问'])
def test_archive_metadata_and_fax_reach_editable_original_cells_for_all_five_categories(tmp_path,category):
    fields={'案件类别':category,'委托人传真':'0000-12345678','档案号':'虚构归档-2026-001','保存期限':'核定测试值'}
    for name in ('立案审批表','档案卷宗'):
        output=service.fill_original_docx(name,fields,'',tmp_path/(name+'.docx'))
        with ZipFile(output) as package:root=ET.fromstring(package.read('word/document.xml'))
        key=service.template_metadata(name,fields)['template_key']
        expected={'传真':fields['委托人传真']} if name=='立案审批表' else {k:fields[k] for k in ('档案号','保存期限')}
        rows=root.xpath('//w:body/w:tbl[1]/w:tr',namespaces=service.NS)
        for field,value in expected.items():
            slot=next(slot for slot in service.SLOTS[key] if slot[0]==field)
            cell=rows[slot[1]].findall(service._tag('tc'))[slot[2]]
            assert ''.join(cell.xpath('.//w:t/text()',namespaces=service.NS))==value
            assert cell.xpath('.//w:permStart',namespaces=service.NS)


def test_identity_cells_remove_handwriting_indent_without_moving_frames(tmp_path):
    fields={"收案日期":"2026年3月1日","结案日期":"2026年6月30日"}
    fields['_provenance']={k:[{'method':'human','value':v}] for k,v in fields.items()}
    output = service.fill_original_docx("档案卷宗", fields, "", tmp_path / "form.docx")
    with ZipFile(output) as package:root=ET.fromstring(package.read("word/document.xml"))
    for text in ("2026年3月1日", "2026年6月30日"):
        cell=root.xpath("//w:tc[.//w:t[text()=$value]]",namespaces=service.NS,value=text)[0]
        indent=cell.find(service._tag('p')+'/'+service._tag('pPr')+'/'+service._tag('ind'))
        assert indent is not None and set(indent.attrib.values()) == {'0'}
        assert '\u200b' not in cell.xpath('./w:p/w:r/w:t/text()',namespaces=service.NS)
        assert cell.find(service._tag('tcPr')+'/'+service._tag('vAlign')).get(service._tag('val')) == 'center'


def test_delivery_identity_keeps_full_names_in_two_fixed_header_lines(tmp_path):
    client = "星河演示银行股份有限公司示例市分行"
    lawyers = "虚构陈律师、虚构李律师"
    output = service.fill_original_docx("送达材料清单", {"委托人":client,
        "承办律师":lawyers}, "", tmp_path / "delivery.docx")
    with ZipFile(output) as package:root=ET.fromstring(package.read("word/document.xml"))
    paragraph=root.find(service._tag('body')).findall(service._tag('p'))[2]
    assert ''.join(paragraph.xpath('.//w:t/text()',namespaces=service.NS)) == '委托方：'+client+'承办律师：'+lawyers
    assert len(paragraph.xpath('.//w:br',namespaces=service.NS)) == 1
    spacing=paragraph.find(service._tag('pPr')+'/'+service._tag('spacing'))
    assert spacing.get(service._tag('line')) == '312'
    assert spacing.get(service._tag('lineRule')) == 'exact'


def test_extractable_text_outside_its_cell_is_not_accepted_as_visible(tmp_path):
    path=tmp_path/'clipped.pdf'
    with fitz.open() as doc:
        page=doc.new_page()
        page.insert_text((100,100),'Visible candidate',fontsize=12)
        doc.save(path)
    # This used to pass solely because the PDF text layer contains the value.
    service.verify_original_pdf(path,expected_pages=1,expected_texts=['Visible candidate'])
    with pytest.raises(service.OriginalTemplateError) as failure:
        service.verify_original_pdf(path,expected_pages=1,expected_texts=['Visible candidate'],
            field_regions=[{'field':'委托人','page':0,'rect':(90,80,250,95),'text':'Visible candidate'}])
    assert failure.value.code=='overflow' and failure.value.fields==['委托人']
    service.verify_original_pdf(path,expected_pages=1,
        field_regions=[{'field':'委托人','page':0,'rect':(90,80,250,110),'text':'Visible candidate'}])


def test_outside_table_paragraph_retains_original_strut_and_spacing():
    paragraph=ET.fromstring(f'<w:p xmlns:w="{service.W}"><w:pPr><w:spacing w:before="200" w:after="120" w:line="360"/></w:pPr>'
        '<w:r><w:rPr><w:rFonts w:eastAsia="黑体"/><w:sz w:val="32"/></w:rPr><w:t>案号：</w:t></w:r></w:p>')
    before=ET.tostring(paragraph.find(service._tag("pPr")))
    service._fill(paragraph,"虚构案号", "案号：")
    assert ET.tostring(paragraph.find(service._tag("pPr"))) == before
    fixed=paragraph.find(service._tag("r"))
    assert fixed.find(service._tag("rPr")+"/"+service._tag("sz")).get(service._tag("val")) == "32"
    assert fixed.find(service._tag("t")).text == "案号："


def test_derived_page_count_is_read_only_but_checked_for_visible_output(tmp_path, monkeypatch):
    seen = {}
    def convert(docx, output, **kwargs):
        seen.update(kwargs)
        with ZipFile(docx) as package:
            root = ET.fromstring(package.read("word/document.xml"))
        cells = root.xpath("//w:tc[.//w:t[contains(., '123 页')]]", namespaces=service.NS)
        assert len(cells) == 1
        assert not cells[0].xpath(".//w:permStart", namespaces=service.NS)
        return str(output)
    monkeypatch.setattr(service, "convert_docx_to_pdf", convert)
    service.render_original_pdf("档案卷宗", {}, "虚构律所", tmp_path / "cover.pdf", derived_output={"volume_page_count": 123})
    assert "123 页" in seen["expected_texts"]


@pytest.mark.parametrize("name,fields,key", [
    ("立案审批表", {"案情简介": "私密虚构测试" * 80}, "案情简介"),
    ("送达材料清单", {"法院文件清单": "\n".join("虚构裁定书" for _ in range(19))}, "法院文件清单"),
    ("送达材料清单", {"法院文件清单": "虚构长标题" * 10}, "法院文件清单"),
])
def test_overflow_is_safe_and_cannot_truncate_or_append_pages(tmp_path, name, fields, key):
    before = dict(fields)
    with pytest.raises(service.OriginalTemplateError) as error:
        service.fill_original_docx(name, fields, "虚构律所", tmp_path / "filled.docx")
    assert error.value.code == "overflow" and error.value.fields == [key]
    assert fields == before and not (tmp_path / "filled.docx").exists()
    assert "私密虚构测试" not in str(error.value)


def make_pdf(path, pages=1, dx=0, text="Fictional complete content"):
    with fitz.open() as document:
        for _ in range(pages):
            page = document.new_page()
            page.draw_rect((50 + dx, 50, 300 + dx, 200))
            page.insert_text((60 + dx, 80), text)
        document.save(path)


@pytest.mark.parametrize("failure", ["page_count", "frame", "overflow"])
def test_native_pdf_validation_rejects_added_pages_moved_frames_or_missing_text(tmp_path, failure):
    reference = tmp_path / "reference.pdf"
    actual = tmp_path / "actual.pdf"
    make_pdf(reference)
    make_pdf(actual, pages=2 if failure == "page_count" else 1,
        dx=5 if failure == "frame" else 0, text="Fictional clipped" if failure == "overflow" else "Fictional complete content")
    with pytest.raises(service.OriginalTemplateError) as error:
        service.verify_original_pdf(actual, expected_pages=1, reference_pdf=reference,
            expected_texts=["Fictional complete content"])
    assert error.value.code == failure


def test_production_pdf_has_no_html_or_browser_fallback(tmp_path, monkeypatch):
    marker = "FICTIONAL_PRIVATE_PATH"
    seen = []
    def original(*args, **kwargs):
        seen.append((args, kwargs))
        raise service.OriginalTemplateError("overflow", ["案情简介"])
    monkeypatch.setattr(service, "render_original_pdf", original)
    monkeypatch.setattr(browser_pdf_service, "render_form_html", lambda *_a, **_k: pytest.fail("redrawn fallback"))
    with pytest.raises(service.OriginalTemplateError):
        browser_pdf_service.render_form_pdf("立案审批表", {"委托人": marker}, "虚构律所", str(tmp_path / "form.pdf"))
    assert len(seen) == 1 and not list(tmp_path.iterdir())


def test_native_export_failure_never_exposes_process_arguments_or_exception(tmp_path, monkeypatch):
    marker = "FICTIONAL_PRIVATE_ARGUMENT"
    observed = {}
    def fail(command, **kwargs):
        observed.update(kwargs)
        raise service.subprocess.TimeoutExpired(command, 90, output=marker, stderr=marker)
    monkeypatch.setattr(service.subprocess, "run", fail)
    monkeypatch.setattr(service, "_word_render_lock", nullcontext)
    with pytest.raises(service.OriginalTemplateError) as error:
        service.convert_docx_to_pdf(tmp_path / (marker + ".docx"), tmp_path / "out.pdf", expected_pages=1)
    assert observed["stdout"] == service.subprocess.DEVNULL == observed["stderr"]
    assert marker not in "".join(traceback.format_exception(error.value))
    assert not list(tmp_path.glob("*.pdf"))


@pytest.mark.skipif(os.name != "nt", reason="native Word rendering is Windows-only")
def test_word_lock_serializes_concurrent_threads():
    inside = 0
    maximum = 0
    gate = threading.Barrier(2)
    def enter():
        nonlocal inside, maximum
        gate.wait()
        with service._word_render_lock():
            inside += 1
            maximum = max(maximum, inside)
            time.sleep(.03)
            inside -= 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: enter(), range(2)))
    assert maximum == 1


def test_clipped_field_is_named_without_returning_its_text(tmp_path):
    actual = tmp_path / "clipped.pdf"
    make_pdf(actual)
    missing = "FICTIONAL_PRIVATE_CONTENT_THAT_MUST_NOT_DISAPPEAR"
    with pytest.raises(service.OriginalTemplateError) as error:
        service.verify_original_pdf(actual, expected_pages=1, expected_texts=[missing],
            field_texts={"结案小结": [missing]})
    assert error.value.code == "overflow" and error.value.fields == ["结案小结"]
    assert missing not in str(error.value)
