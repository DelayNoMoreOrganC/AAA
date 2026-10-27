from types import SimpleNamespace
from copy import deepcopy
import pytest
from app.services.task_workflow import _evidence_ocr_is_advisory
from app.services.form_fill_audit import content_preflight
from app.services.preview_fields import build_preview
from app.services.original_template_service import fill_original_docx
from docx import Document

def test_minor_evidence_ocr_keeps_audit_without_user_decision_only_when_no_fields_depend_on_it():
    unit=SimpleNamespace(doc_id=3,source_path='fictional.pdf',start_page=4,end_page=5,
        doc_type='evidence',confidence=.9,manual_catalog_seq=None)
    analysis=SimpleNamespace(doc_spans=[unit],fields={'_evidence_bundles':[dict(source_path='fictional.pdf',
        entries=[dict(status='matched_range',doc_ids=[3])])]})
    entry=dict(source_path='fictional.pdf',page=5,reason_codes=['low_confidence'],mean_confidence=.98)
    assert _evidence_ocr_is_advisory(entry,analysis)
    analysis.fields['_provenance']={'费用':[dict(source_path='fictional.pdf',page=5,value='1000')]}
    assert not _evidence_ocr_is_advisory(entry,analysis)
    analysis.fields.pop('_provenance')
    for change in [dict(reason_codes=['empty_text']),dict(mean_confidence=.6),dict(page=6,reason_codes=['sparse_ocr'])]:
        assert not _evidence_ocr_is_advisory(dict(entry,**change),analysis)

def test_core_blank_grouping_excludes_manual_signatures_and_does_not_claim_accuracy():
    rows=[dict(template=t,field='委托人',value='',status='missing',reason='未识别') for t in ['封面','审批表']]
    rows.append(dict(template='审批表',field='主任审批意见',value='',status='manual_area',reason='签字'))
    report=content_preflight(rows)
    assert len(report['items'])==1 and len(report['items'][0]['templates'])==2
    assert report['status']=='needs_review' and report['accuracy_independently_verified'] is False

def test_separate_summaries_reach_the_original_cells_without_alias_merging(tmp_path):
    fields={'案件类别':'民事','审（办）结果':'虚构案件结果摘要。','结案小结':'虚构案件办理过程与后续事项。'}
    for name,key,row in [('档案卷宗','审（办）结果',9),('结案报告表','结案小结',3)]:
        preview={f['key']:f['value'] for f in build_preview(name,fields)['fields']}
        assert preview[key]==fields[key]
        path=fill_original_docx(name,fields,'虚构律所',tmp_path/(name+'.docx'))
        text=Document(path).tables[0].rows[row].cells[1].text
        assert fields[key] in text
        assert fields['结案小结' if key=='审（办）结果' else '审（办）结果'] not in text
