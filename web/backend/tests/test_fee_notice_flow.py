"""Fee source, UI review, original table and stale identity integration."""
from copy import deepcopy
from pathlib import Path
import runpy
from types import SimpleNamespace
import pytest
from app.core.v4_bridge import load
from app.services.field_assurance import field_assurance
from app.services.evidence_links import supporting_refs
from app.services.party_binding_state import reconcile_party_bindings
from app.services.task_workflow import analysis_issues
from app.services.original_template_service import _values, approval_custom_value, fill_original_docx

load('source_fee_notice')
PREPARED = runpy.run_path(str(Path(__file__).resolve().parents[3] / 'tests/test_source_fee_notice.py'))['prepared']
MANIFEST = [{'path': 'notice.pdf', 'file_id': 'notice', 'filename': 'notice.pdf', 'pages': 1}]


def issues(fields, manifest):
    return analysis_issues(SimpleNamespace(fields=fields, doc_spans=[], low_confidence_items=[],
        missing_items=[], case_type='民事'), manifest)


def test_fee_flows_into_original_form_and_removes_only_resolved_review():
    fields = PREPARED()
    value = fields['收费标准']
    assert _values('立案审批表', fields, '', {})['收费标准'] == value
    assert field_assurance('收费标准', value, fields, source_manifest=MANIFEST)['status'] == 'source_supported'
    drafts = load('form_drafts')
    accepted, refs = drafts._accepted(fields, '收费标准', set(), drafts._scope(MANIFEST))
    assert accepted == value and supporting_refs(refs[0], fields, MANIFEST) == []
    assert not any(i['kind'] == 'fact_review' for i in issues(fields, MANIFEST))


@pytest.mark.parametrize('change', ['identity', 'value', 'quote', 'rate', 'source_page', 'source_hash', 'deleted'])
def test_broken_fee_proof_keeps_review_and_cannot_get_source_badge(change):
    fields = PREPARED(); ref = fields['_provenance']['收费标准'][0]; manifest = deepcopy(MANIFEST)
    if change == 'identity': fields['对方当事人'] = '另一虚构人'
    if change == 'value': fields['收费标准'] = '已收2000元'
    if change == 'quote': ref['quote'] = ref['quote'].replace('2.5%', '3.5%')
    if change == 'rate': ref['fee_terms'] = ref['fee_terms'].replace('2.5%', '3.5%')
    if change == 'source_page': ref['page'] = 2
    if change == 'source_hash': ref['source_sha256'] = 'different'
    if change == 'deleted': manifest = []
    assert field_assurance('收费标准', fields['收费标准'], fields, source_manifest=manifest)['status'] == 'unverified'
    assert any(i['kind'] == 'fact_review' for i in issues(fields, manifest))


def test_stale_fee_is_cleared_but_manual_value_and_audit_survive():
    fields = PREPARED(); fields['案由'] = '另一纠纷'
    result = reconcile_party_bindings(fields, {}, MANIFEST)
    assert result['收费标准'] == '' and result['_provenance']['收费标准']
    human = reconcile_party_bindings(fields, {'收费标准': '人工核对的收费条款'}, MANIFEST)
    assert human['收费标准'] == '人工核对的收费条款'


def test_fee_note_is_visible_in_original_and_audit_and_never_written_as_approval(tmp_path):
    from zipfile import ZipFile
    from lxml import etree
    from app.services.form_fill_audit import build_form_fill_audit
    fields=PREPARED();fields['案件类别']='民事'
    note,automatic=approval_custom_value(fields,9)
    assert automatic and note=='其他收费约定详卷内委托代理通知书。'
    assert approval_custom_value(fields,6)==('',False)
    assert approval_custom_value(fields,7)==('',False)
    target=tmp_path/'approval.docx'
    fill_original_docx('立案审批表',fields,'虚构律所',str(target))
    with ZipFile(target) as z:
        root=etree.fromstring(z.read('word/document.xml'))
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    text=''.join(root.xpath('//w:t/text()',namespaces=ns))
    assert '风险基准2.5%' in text and note in text
    audit=build_form_fill_audit(fields,MANIFEST)
    row=next(r for r in audit if r['template']=='立案审批表' and r['field']=='备注')
    assert row['value']==note and row['status']=='source_reference'
    assert row['saved_value']=='' and row['sources']==[{'filename':'notice.pdf','page':1}]


@pytest.mark.parametrize('manual',['', '已按实际情况填写的备注'])
def test_explicit_custom_remarks_including_blank_override_automatic_note(manual):
    from app.services.form_fill_audit import build_form_fill_audit
    fields=PREPARED();fields['案件类别']='民事'
    fields['_preview_custom_values']={'立案审批表':{'p0-b0-r9-c0':manual}}
    assert approval_custom_value(fields,9)==(manual,False)
    row=next(r for r in build_form_fill_audit(fields,MANIFEST) if r['template']=='立案审批表' and r['field']=='备注')
    assert row['value']==manual and row['status']!='source_reference'


def test_stale_fee_does_not_generate_a_note():
    fields=PREPARED();fields['委托人']='另一虚构主体'
    assert approval_custom_value(fields,9)==('',False)
