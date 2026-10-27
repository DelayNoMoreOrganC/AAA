from copy import deepcopy
import pytest
from app.core.v4_bridge import load
from app.services.field_assurance import field_assurance


@pytest.mark.parametrize('client,opponent',[('虚构甲银行','虚构乙公司、虚构丙'),('虚构丙','虚构甲银行')])
def test_two_document_party_assurance_requires_current_poa_and_pleading(client,opponent):
    poa=('授权委托书\n委托人：'+client+'\n受委托人姓名：虚构律师甲\n工作单位：虚构明理律师事务所\n'
         '职务：律师\n代理权限：一般授权\n现委托上列受委托人作为我方诉讼代理人。')
    pleading=('民事起诉状\n原告：虚构甲银行。被告一：虚构乙公司。被告二：虚构丙。\n'
              '案由：金融借款合同纠纷。\n诉讼请求：判令被告偿还本金1000元。事实与理由：借款未还。')
    units=[load('pdf_doc_locator').DocumentUnit(i,kind,i,i,source_path='fiction.pdf',confidence=.95)
           for i,kind in enumerate(('poa','complaint'))]
    fields={'案件类别':'民事'};refs={};conflicts=[]
    cache={('fiction.pdf',1):poa,('fiction.pdf',2):pleading}
    load('source_fact_recall').recall_cached_source_facts(fields,refs,conflicts,page_cache=cache,
        allowed_sources=set(cache),document_units=units,fact_review=[])
    fields.update(_provenance=refs,_field_conflicts=conflicts)
    manifest=[dict(path='fiction.pdf',file_id='fiction',pages=2)]
    assert fields['当事人']==client and fields['对方当事人']==opponent
    for field in ('当事人','对方当事人'):
        status=field_assurance(field,fields[field],fields,source_manifest=manifest)
        assert status['status']!='unverified' and status['source_count']==2
        assert field_assurance(field,fields[field],fields,source_manifest=[dict(path='other.pdf',pages=2)])['status']=='unverified'
        changed=deepcopy(fields);changed['_provenance']['委托人'][0]['quote']+='撤销本授权。'
        assert field_assurance(field,changed[field],changed,source_manifest=manifest)['status']=='unverified'
