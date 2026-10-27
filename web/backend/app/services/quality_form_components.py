"""Generate only the missing half of the retained quality-card/notice template.

Component selection is explicit and must come from validated source units, never
from a model's assertion that the whole combined template is present. This module
does not infer receipt, signatures, client answers or service quality.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import fitz
from lxml import etree as ET

from . import original_template_service as original


COMPONENTS = {
    'quality_card': {'title': '律师办案质量监督卡', 'reference_page': 0},
    'client_notice': {'title': '委托人须知', 'reference_page': 1},
}
TEMPLATE = '质量监督卡'


def _component(component):
    if type(component) is not str or component not in COMPONENTS:
        raise original.OriginalTemplateError('missing')
    return COMPONENTS[component]


def _select_xml(xml, component):
    _component(component)
    root = ET.fromstring(xml)
    body = root.find(original._tag('body'))
    if body is None:
        raise original.OriginalTemplateError('missing')
    nodes = list(body)
    headings = {}
    for kind, definition in COMPONENTS.items():
        indices = [i for i, node in enumerate(nodes)
                   if node.tag == original._tag('p') and original._compact(
                       ''.join(node.xpath('.//w:t/text()', namespaces=original.NS))) == definition['title']]
        if len(indices) != 1:
            raise original.OriginalTemplateError('missing')
        headings[kind] = indices[0]
    boundary = headings['client_notice']
    if headings['quality_card'] != 0 or boundary < 2:
        raise original.OriginalTemplateError('missing')
    # The original uses a blank heading paragraph between the two pages.
    # It belongs to neither standalone form: retaining it can create page 2.
    end = boundary
    while end > 0 and nodes[end - 1].tag == original._tag('p') and not nodes[end - 1].xpath('.//w:t', namespaces=original.NS):
        end -= 1
    keep = nodes[:end] if component == 'quality_card' else nodes[boundary:]
    sections = [n for n in nodes if n.tag == original._tag('sectPr')]
    if len(sections) != 1 or nodes[-1] is not sections[0]:
        raise original.OriginalTemplateError('missing')
    if sections[0] not in keep:
        keep.append(sections[0])
    for node in nodes:
        if node not in keep:
            body.remove(node)
    table_count = len(body.findall(original._tag('tbl')))
    if table_count != (1 if component == 'quality_card' else 0):
        raise original.OriginalTemplateError('missing')
    return ET.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)


def fill_quality_component_docx(component, fields, organization_name, output_path):
    """Retain the original XML and package; never redraw a form or fill signatures."""
    _component(component)
    original.template_metadata(TEMPLATE)
    source = original.TEMPLATES / 'word-converted' / (original.FILES[TEMPLATE] + '.docx')
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='quality-component-', dir=output.parent) as temporary:
        # A static notice must not validate or consume fields belonging to the
        # already supplied card, even when those fields exceed card capacity.
        filled = original.fill_original_docx(TEMPLATE,
            fields if component == 'quality_card' else {},
            organization_name if component == 'quality_card' else '',
            Path(temporary) / 'combined.docx')
        with ZipFile(source) as source_zip, ZipFile(filled) as package:
            expected = _select_xml(source_zip.read('word/document.xml'), component)
            edited = _select_xml(package.read('word/document.xml'), component)
            if original.frame_signature(expected) != original.frame_signature(edited):
                raise original.OriginalTemplateError('frame')
            with ZipFile(output, 'w') as result:
                for entry in package.infolist():
                    result.writestr(entry, edited if entry.filename == 'word/document.xml' else package.read(entry.filename))
    return str(output)


def _verify_static_notice_layout(path, reference):
    """No table exists on this page, so frame checks alone cannot detect drift."""
    with fitz.open(path) as actual, fitz.open(reference) as expected:
        if len(actual) != 1 or len(expected) != 1:
            raise original.OriginalTemplateError('page_count')
        a, b = actual[0].get_text('words'), expected[0].get_text('words')
        if (actual[0].rect != expected[0].rect or not b or len(a) != len(b)
                or any(x[4] != y[4] or any(abs(x[i] - y[i]) > .201 for i in range(4))
                       for x, y in zip(a, b))):
            raise original.OriginalTemplateError('frame')


def render_quality_component_pdf(component, fields, organization_name, output_pdf):
    """Native-render the standalone Word and check the corresponding original page."""
    definition = _component(component)
    output = Path(output_pdf)
    docx = fill_quality_component_docx(component, fields, organization_name, output.with_suffix('.docx'))
    reference = original.TEMPLATES / 'word-reference-pdf' / (original.FILES[TEMPLATE] + '.pdf')
    with TemporaryDirectory(prefix='quality-reference-', dir=output.parent) as temporary:
        reference_part = Path(temporary) / 'reference.pdf'
        with fitz.open(reference) as combined, fitz.open() as selected:
            page = definition['reference_page']
            selected.insert_pdf(combined, from_page=page, to_page=page)
            selected.save(reference_part)
        with ZipFile(docx) as package:
            root = ET.fromstring(package.read('word/document.xml'))
        # Validate static notice text and unchecked questionnaire text too, not
        # merely the four fillable cells. No footer or last paragraph may vanish.
        texts = [''.join(p.xpath('.//w:t/text()', namespaces=original.NS))
                 for p in root.xpath('//w:body//w:p', namespaces=original.NS)]
        values = original._values(TEMPLATE, fields or {}, organization_name, None) if component == 'quality_card' else {}
        regions = original._field_regions(original.template_metadata(TEMPLATE), values) if component == 'quality_card' else ()
        result = original.convert_docx_to_pdf(docx, output, expected_pages=1,
            reference_pdf=reference_part, expected_texts=texts,
            field_texts={key: [value] for key, value in values.items()}, field_regions=regions)
        if component == 'client_notice':
            _verify_static_notice_layout(result, reference_part)
        return result
