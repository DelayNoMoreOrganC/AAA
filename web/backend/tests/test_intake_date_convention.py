from copy import deepcopy
from app.core.v4_bridge import init_v4_path
from app.services.preview_fields import build_preview, sanitize_preview_updates
from app.services.original_template_service import _values
from app.services.field_assurance import field_assurance
from app.services.form_fill_audit import build_form_fill_audit
from app.services.party_binding_state import reconcile_party_bindings

init_v4_path()
from intake_contract_date import FIELD, recall
from pdf_doc_locator import DocumentUnit


def fixture():
    fields={'委托人':'虚构银行','对方当事人':'虚构甲公司','案由':'金融借款合同纠纷'}
    page='委托代理合同\n委托人：虚构银行。受托人：虚构律师事务所。\n代理虚构银行诉虚构甲公司金融借款合同纠纷。律师费5000元。\n签订日期：2026年1月5日。'
    refs={};conflicts=[]
    recall(fields,refs,conflicts,page_cache={('c.pdf',1):page},allowed_sources={('c.pdf',1)},
           document_units=[DocumentUnit(0,'contract',0,0,source_path='c.pdf',confidence=.95)])
    fields.update(_provenance=refs,_field_conflicts=conflicts)
    manifest=[{'path':'c.pdf','pages':1,'file_id':'fixture-contract','filename':'虚构代理合同.pdf'}]
    return fields,manifest


def test_default_fills_intake_only_and_is_explicitly_marked():
    fields,manifest=fixture();before=deepcopy(fields)
    entry=next(r for r in build_preview('立案审批表',fields,source_manifest=manifest)['fields'] if r['key']==FIELD)
    assert entry['value']=='2026年1月5日'
    assert entry['assurance']['status']=='convention_default'
    assert entry['assurance']['anchors']==[{'file_id':'fixture-contract','page':1}]
    assert _values('立案审批表',fields,'',{})[FIELD]=='2026年1月5日（按合同日期默认）'
    assert _values('档案卷宗',fields,'',{})['收案日期']==''
    assert fields==before


def test_old_client_intake_edit_is_mapped_without_changing_cover_date():
    assert sanitize_preview_updates('立案审批表',{'收案日期':'2026年2月1日'})=={FIELD:'2026年2月1日'}
    assert sanitize_preview_updates('档案卷宗',{'收案日期':'2026年2月1日'})=={'收案日期':'2026年2月1日'}
    fields,manifest=fixture()
    fields.update(sanitize_preview_updates('立案审批表',{'收案日期':''}))
    fields['_provenance'][FIELD]=[{'method':'human','value':''}]
    fields['收案日期']='2025年1月1日'
    assert _values('立案审批表',fields,'',{})[FIELD]==''
    assert _values('档案卷宗',fields,'',{})['收案日期']=='2025年1月1日'


def test_legacy_manual_dates_remain_visible_without_becoming_convention():
    fields={'收案日期':'2025年1月1日','_provenance':{'收案日期':[{'method':'human','value':'2025年1月1日'}]}}
    entry=next(r for r in build_preview('立案审批表',fields)['fields'] if r['key']==FIELD)
    assert entry['value']=='2025年1月1日' and entry['assurance']['status']=='human_confirmed'
    assert 'display_value' not in entry


def test_source_removed_or_identity_changed_clears_only_automatic_value():
    fields,manifest=fixture()
    assert reconcile_party_bindings(fields,{},source_manifest=[])[FIELD]==''
    supplement=manifest+[{'path':'new-contract.pdf','pages':2,'file_id':'additional-contract','filename':'补充材料.pdf'}]
    assert reconcile_party_bindings(fields,{},source_manifest=supplement)[FIELD]==''
    fields['委托人']='另一客户'
    assert reconcile_party_bindings(fields,{},source_manifest=manifest)[FIELD]==''
    fields['_provenance'][FIELD].append({'method':'human','value':fields[FIELD]})
    assert reconcile_party_bindings(fields,{},source_manifest=[])[FIELD]=='2026年1月5日'


def test_audit_keeps_default_marker_and_does_not_assert_approval():
    fields,manifest=fixture()
    audit=build_form_fill_audit(fields,manifest)
    row=next(r for r in audit if r['template']=='立案审批表' and r['field']==FIELD)
    assert row['saved_value']=='2026年1月5日' and '按合同日期默认' in row['value']
    assert row['status']=='convention_default' and '不证明已签署' in row['reason']
    assert row['sources']==[{'filename':'虚构代理合同.pdf','page':1}]


def test_conflicting_date_does_not_get_convention_badge():
    fields,manifest=fixture();fields['_field_conflicts']=[{'field':FIELD,'values':['a','b']}]
    assert field_assurance(FIELD,fields[FIELD],fields,source_manifest=manifest)['status']=='conflict'
