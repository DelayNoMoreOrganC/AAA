from copy import deepcopy
from app.core.v4_bridge import init_v4_path
from app.services.preview_fields import build_preview
from app.services.original_template_service import _values, approval_custom_value
from app.services.form_fill_audit import build_form_fill_audit

init_v4_path()
from fee_display import collect
from pdf_doc_locator import DocumentUnit


def fixture():
    terms = '一审基础律师费5000元；另按实际收回款项的2%收取风险代理费。基础费于合同订立后十日内支付，风险费于实际回款后结算。'
    page = '委托代理合同\n委托人（甲方）：虚构银行。\n收费约定：' + terms + '\n合同签订日期：2026年1月5日。'
    refs = {'收费标准': [{'value': terms, 'quote': '收费约定：' + terms, 'method': 'local_agent', 'source_path': 'contract.pdf', 'page': 1}]}
    fields = {'收费标准': terms, '委托人': '虚构银行'}
    collect(fields, refs, [], page_cache={('contract.pdf', 1): page}, allowed_sources={('contract.pdf', 1)},
        document_units=[DocumentUnit(0, 'contract', 0, 0, '委托代理合同', source_path='contract.pdf', confidence=.95)], manual_fields={})
    fields['_provenance'] = refs
    return fields


def test_editor_keeps_full_terms_renderer_and_preview_share_explicit_short_value():
    fields = fixture(); before = deepcopy(fields)
    entry = next(f for f in build_preview('立案审批表', fields)['fields'] if f['key'] == '收费标准')
    assert entry['value'] == fields['收费标准'] and entry['multiline']
    assert entry['display_value'] == _values('立案审批表', fields, '', {})['收费标准']
    note, automatic = approval_custom_value(fields, 9)
    assert automatic and note == entry['display_note'] and '一审' in note
    assert fields == before


def test_manual_note_is_never_overwritten_and_disables_dependent_fee_shortening():
    fields = fixture(); fields['_preview_custom_values'] = {'立案审批表': {'p0-b0-r9-c0': '人工备注'}}
    assert approval_custom_value(fields, 9) == ('人工备注', False)
    assert _values('立案审批表', fields, '', {})['收费标准'] == fields['收费标准']


def test_fill_audit_distinguishes_printed_summary_and_saved_complete_terms():
    fields = fixture()
    audit = build_form_fill_audit(fields, [{'path': 'contract.pdf', 'pages': 1, 'file_id': 'c', 'filename': '虚构合同.pdf'}])
    rows = audit['rows'] if isinstance(audit, dict) else audit
    row = next(r for r in rows if r['template'] == '立案审批表' and r['field'] == '收费标准')
    assert row['value'] == '基础5000元\n回款2%详合同'
    assert row['saved_value'] == fields['收费标准'] and '完整收费条款' in row['reason']
