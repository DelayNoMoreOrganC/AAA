"""Whole source forms that replace a generated form, never proof of execution.

Quality card/client notice are tracked separately; only both replace the whole
combined template. The measured volume cover is still generated.
"""
FORM_TYPES = {
    '立案审批表': 'intake_approval',
    '结案报告表': 'closure_report',
    '送达材料清单': 'service_list',
}
QUALITY_COMPONENTS = ('quality_card', 'client_notice')
DRAFT_FIELD_FORMS = {
    '立案审批日期':'立案审批表',
    '案情简介':'立案审批表', '法院文件清单':'送达材料清单',
    '委托人联系地址及电话':'质量监督卡', '案件或项目名称':'结案报告表', '结案小结':'结案报告表',
}
SOURCE_FORM_TYPES = frozenset(FORM_TYPES.values()) | frozenset(QUALITY_COMPONENTS)


def source_units_for_item(item, units):
    if not item or item.source != 'system' or not item.templates:
        return []
    kinds=QUALITY_COMPONENTS if item.templates[0]=='质量监督卡' else (FORM_TYPES.get(item.templates[0]),)
    return [u for u in units or [] if u.doc_type in kinds and u.catalog_seq==item.seq]


def original_form_sources(fields, name):
    fields=fields or {}
    if name not in FORM_TYPES and name!='质量监督卡':return []
    forms=fields.get('_original_forms') or {}
    refs=forms.get(name,[]) if isinstance(forms,dict) else []
    # Old saved tasks retain the intake-specific projection until their next edit.
    if not refs and name=='立案审批表':refs=fields.get('_source_intake_approval') or []
    return refs if isinstance(refs,list) else []


def quality_component_sources(fields):
    value=(fields or {}).get('_original_form_components') or {}
    refs=value.get('质量监督卡',[]) if isinstance(value,dict) else []
    return refs if isinstance(refs,list) else []


def missing_quality_components(refs):
    present={r.get('component') for r in refs or [] if isinstance(r,dict)}
    return tuple(kind for kind in QUALITY_COMPONENTS if kind not in present)


def form_fields_preserved(fields,name):
    return bool(original_form_sources(fields,name) or (name=='质量监督卡' and any(
        r.get('component')=='quality_card' for r in quality_component_sources(fields))))


def draft_field_needs_generated_form(fields,field):
    return not form_fields_preserved(fields,DRAFT_FIELD_FORMS.get(field))
