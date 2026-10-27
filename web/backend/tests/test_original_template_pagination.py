"""Only generated form footer fields are suppressed; retained sources are not edited."""
from zipfile import ZipFile
from lxml import etree as ET
import pytest
from app.services import original_template_service as s


def test_delivery_form_has_no_independent_page_field_or_cached_one(tmp_path):
    output=s.fill_original_docx('送达材料清单',{'委托人':'虚构甲'},'',tmp_path/'delivery.docx')
    with ZipFile(output) as z:
        for name in z.namelist():
            if name.startswith('word/footer') and name.endswith('.xml'):
                xml=ET.fromstring(z.read(name))
                assert not xml.xpath('//w:instrText[contains(., "PAGE")]',namespaces=s.NS)
                assert not xml.xpath('//w:t[text()="1"]',namespaces=s.NS)


def footer(body):
    return f'<w:ftr xmlns:w="{s.W}"><w:p><w:pPr><w:jc w:val="center"/></w:pPr>{body}</w:p></w:ftr>'.encode()


COMPLEX='<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'


@pytest.mark.parametrize('body',[COMPLEX,'<w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>'])
def test_removes_only_standalone_page_field_leaves_paragraph_geometry(body):
    original=footer(body)
    result=s._without_template_page_fields(original)
    root=ET.fromstring(result)
    assert not root.xpath('//w:fldChar|//w:instrText|//w:fldSimple|//w:t',namespaces=s.NS)
    assert ET.tostring(root.find('.//'+s._tag('pPr')))==ET.tostring(ET.fromstring(original).find('.//'+s._tag('pPr')))


@pytest.mark.parametrize('body',[
    '<w:r><w:t>1</w:t></w:r>',
    '<w:r><w:t>律所原件编号1</w:t></w:r>',
    '<w:r><w:t>第</w:t></w:r>'+COMPLEX+'<w:r><w:t>页</w:t></w:r>',
    COMPLEX.replace(' PAGE ',' DATE '),
    COMPLEX.replace(' PAGE ',' PAGEREF bookmark '),
    COMPLEX.replace(' PAGE ',' =PAGE+1 '),
    COMPLEX.replace('fldCharType="end"','fldCharType="begin"'),
    COMPLEX+'<w:r><w:drawing/></w:r>',
])
def test_does_not_guess_static_numbers_other_fields_or_mixed_footer_content(body):
    original=footer(body)
    assert s._without_template_page_fields(original)==original
