from copy import deepcopy

from app.core.v4_bridge import load
from app.services.field_assurance import field_assurance


def test_intake_excerpt_uses_all_source_pages_and_loses_assurance_after_tampering():
    path='fictional-complaint.pdf'
    unit=load('pdf_doc_locator').DocumentUnit(1,'complaint',0,1,'民事起诉状',source_path=path,confidence=.9)
    fields={}
    load('complaint_brief').collect(fields,page_cache={
        (path,1):'民事起诉状\n原告：虚构甲。被告：虚构乙。\n诉讼请求：判令被告返还借款10万元。',
        (path,2):'事实与理由：双方订立借款合同，被告未按约还款。此致虚构区人民法院。'},
        allowed_sources={(path,1),(path,2)},document_units=[unit])
    manifest=[{'file_id':'a','path':path,'pages':2}]
    result=load('form_drafts').derive_form_drafts(fields,[unit],source_manifest=manifest)
    check=lambda data,scope=manifest:field_assurance('案情简介',data['案情简介'],data,source_manifest=scope)
    assert check(result)['status']=='derived_draft'
    assert check(result)['source_count']==2
    assert check(result,[{'file_id':'other','path':'other.pdf','pages':2}])['status']=='unverified'
    changed=deepcopy(result);changed['_intake_complaint_source']['pages'][1]['quote']='无关材料'
    assert check(changed)['status']=='unverified'
