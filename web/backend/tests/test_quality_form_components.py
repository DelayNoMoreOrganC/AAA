"""Fictional fields, retained form XML, no native renderer or network."""
from zipfile import ZipFile

import fitz
from lxml import etree as ET
import pytest

from app.services import original_template_service as original
from app.services import quality_form_components as components


@pytest.mark.parametrize('kind', ['quality_card', 'client_notice'])
def test_component_keeps_only_its_original_content_and_package(tmp_path, kind):
    output = components.fill_quality_component_docx(kind,
        {'法院收案号': '虚构案号', '承办律师': '示例律师', '律师事务所': '示例律师事务所'}, '账号组织', tmp_path / 'part.docx')
    source = original.TEMPLATES / 'word-converted' / (original.FILES['质量监督卡'] + '.docx')
    with ZipFile(source) as before, ZipFile(output) as after:
        assert before.namelist() == after.namelist()
        for name in before.namelist():
            if name not in {'word/document.xml', 'word/settings.xml'}:
                assert before.read(name) == after.read(name)
        root = ET.fromstring(after.read('word/document.xml'))
        text = original._compact(''.join(root.xpath('//w:t/text()', namespaces=original.NS)))
        paragraphs = [original._compact(''.join(p.xpath('.//w:t/text()', namespaces=original.NS)))
                      for p in root.xpath('//w:body/w:p', namespaces=original.NS)]
        assert components.COMPONENTS[kind]['title'] in paragraphs
        other = 'client_notice' if kind == 'quality_card' else 'quality_card'
        assert components.COMPONENTS[other]['title'] not in paragraphs
        assert len(root.xpath('//w:tbl', namespaces=original.NS)) == (kind == 'quality_card')
        assert len(root.xpath('//w:body/w:sectPr', namespaces=original.NS)) == 1
        if kind == 'quality_card':
            assert '虚构案号' in text and '示例律师事务所' in text
            assert len(root.xpath('//w:permStart', namespaces=original.NS)) == 4
            assert '是□' in text and '否□' in text
        else:
            assert '虚构案号' not in text and '示例律师' not in text
            assert original._compact('委托人（签章）：') in text
            assert not root.xpath('//w:permStart', namespaces=original.NS)
            assert after.read('word/document.xml') == components._select_xml(before.read('word/document.xml'), kind)


def test_notice_does_not_fail_on_irrelevant_card_field_overflow(tmp_path):
    components.fill_quality_component_docx('client_notice', {'法院收案号': '长' * 200}, '所' * 300, tmp_path / 'notice.docx')
    with pytest.raises(original.OriginalTemplateError, match='容量'):
        components.fill_quality_component_docx('quality_card', {'法院收案号': '长' * 200}, '', tmp_path / 'card.docx')


@pytest.mark.parametrize('invalid', [None, '', 'quality_card,client_notice', [], 'client'])
def test_invalid_component_never_writes_output(tmp_path, invalid):
    target = tmp_path / 'part.docx'
    with pytest.raises(original.OriginalTemplateError):
        components.fill_quality_component_docx(invalid, {}, '', target)
    assert not target.exists()


def test_changed_or_ambiguous_heading_is_rejected():
    xml = f'<w:document xmlns:w="{original.W}"><w:body><w:p><w:r><w:t>律师办案质量监督卡</w:t></w:r></w:p><w:sectPr/></w:body></w:document>'
    with pytest.raises(original.OriginalTemplateError):
        components._select_xml(xml.encode(), 'quality_card')


def test_static_notice_layout_rejects_shift_even_when_all_text_survives(tmp_path):
    for name, y in [('reference', 70), ('good', 70), ('shifted', 80)]:
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((70, y), 'Retained notice and signature line')
            document.save(tmp_path / (name + '.pdf'))
    components._verify_static_notice_layout(tmp_path / 'good.pdf', tmp_path / 'reference.pdf')
    with pytest.raises(original.OriginalTemplateError) as error:
        components._verify_static_notice_layout(tmp_path / 'shifted.pdf', tmp_path / 'reference.pdf')
    assert error.value.code == 'frame'
