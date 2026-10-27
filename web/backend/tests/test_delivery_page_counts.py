from copy import deepcopy
from zipfile import ZipFile
from lxml import etree as ET
from app.services import original_template_service as service
from app.services.form_fill_audit import build_form_fill_audit
from app.core.v4_bridge import load
derive_form_drafts=load('form_drafts').derive_form_drafts
DocumentUnit=load('pdf_doc_locator').DocumentUnit


def fixture_fields(tmp_path):
    path=str(tmp_path/'fiction.pdf')
    units=[DocumentUnit(0,'judgment',0,5,'民事判决书',14,path,confidence=.9),
           DocumentUnit(1,'summons',6,6,'传票',12,path,confidence=.9)]
    manifest=[dict(file_id='f',path=path,filename='虚构.pdf',pages=7)]
    return derive_form_drafts({},units,source_manifest=manifest),manifest


def cells(path):
    with ZipFile(path) as z:root=ET.fromstring(z.read('word/document.xml'))
    return root.xpath('//w:tbl/w:tr',namespaces=service.NS)


def text(cell):
    # Empty editable cells contain a zero-width caret placeholder.
    return ''.join(cell.xpath('.//w:t/text()',namespaces=service.NS)).replace('\u200b','')


def test_counts_fill_only_page_column_and_are_in_geometry_checks(tmp_path):
    fields,_=fixture_fields(tmp_path)
    output=service.fill_original_docx('送达材料清单',fields,'',tmp_path/'filled.docx')
    rows=cells(output)
    for index,count in enumerate(('6','1'),1):
        row=rows[index].findall(service._tag('tc'))
        assert text(row[2])==count
        assert all(not text(cell) for cell in row[3:])  # Actual delivery remains unknown.
    assert all(not text(row.findall(service._tag('tc'))[2]) for row in rows[3:])
    values=service._values('送达材料清单',fields,'',None)
    regions=service._field_regions(service.template_metadata('送达材料清单',fields),values)
    assert {'6','1'} <= {region['text'] for region in regions}


def test_manual_names_and_stale_sources_never_create_page_measurements(tmp_path):
    fields,_=fixture_fields(tmp_path)
    fields['_form_draft_sources']['法院文件清单'].pop()
    output=service.fill_original_docx('送达材料清单',fields,'',tmp_path/'stale.docx')
    assert all(not text(row.findall(service._tag('tc'))[2]) for row in cells(output)[1:])


def test_audit_reports_same_counts_positions_and_source_pages_without_service_claim(tmp_path):
    fields,manifest=fixture_fields(tmp_path)
    original=deepcopy(fields)
    rows=build_form_fill_audit(fields,manifest)
    counts=[r for r in rows if r['field'] in ('文书1页数','文书2页数')]
    assert [r['value'] for r in counts]==['6','1']
    assert counts[0]['position']==dict(table=1,physical_row=2,physical_cell=3)
    assert counts[0]['sources']==[dict(filename='虚构.pdf',page=1),dict(filename='虚构.pdf',page=6)]
    assert all('不证明实际送达' in r['reason'] for r in counts)
    assert fields==original
