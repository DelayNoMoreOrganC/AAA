"""Independent POA identity must be usable with a complete pleading roster."""
from copy import deepcopy
import pytest
from source_fact_recall import recall_cached_source_facts
from pleading_parties import current_support, recall
from pdf_doc_locator import DocumentUnit
from form_drafts import derive_form_drafts
from tests.test_source_engagement_evidence import PAGE

PLEADING=('民事起诉状\n原告：星河演示公司，住所地虚构星河路。\n'
          '被告一：虚构甲公司。被告二：虚构乙。\n案由：金融借款合同纠纷。\n'
          '诉讼请求：判令被告偿还借款1000元。事实与理由：被告未按约还款。此致虚构法院。')


def run(client='星河演示公司',manual=()):
    fields={'案件类别':'民事'};refs={};conflicts=[]
    cache={('poa.pdf',1):PAGE.replace('星河演示公司',client),('complaint.pdf',1):PLEADING}
    units=[DocumentUnit(0,'poa',0,0,source_path='poa.pdf',confidence=.95),
           DocumentUnit(1,'complaint',0,0,source_path='complaint.pdf',confidence=.95)]
    if '当事人' in manual:fields['当事人']=''
    recall_cached_source_facts(fields,refs,conflicts,page_cache=cache,allowed_sources=set(cache),
        document_units=units,fact_review=[],manual_fields=manual)
    fields.update(_provenance=refs,_field_conflicts=conflicts)
    return fields,units,cache


@pytest.mark.parametrize('client,opponent',[('星河演示公司','虚构甲公司、虚构乙'),('虚构乙','星河演示公司')])
def test_locally_recalled_poa_links_pleading_without_guessing_client_role(client,opponent):
    fields,units,_=run(client)
    assert fields['当事人']==client and fields['对方当事人']==opponent
    assert fields['_provenance']['委托人'][0]['derivation']=='labelled_poa_roster'
    support=current_support(fields['_provenance']['当事人'][0],fields)
    assert {r['source_path'] for r in support}=={'poa.pdf','complaint.pdf'}
    assert fields['案件或项目名称']=='星河演示公司诉虚构甲公司、虚构乙的金融借款合同纠纷'
    manifest=[dict(path=p,pages=1) for p in ('poa.pdf','complaint.pdf')]
    result=derive_form_drafts(fields,units,source_manifest=manifest)
    assert result['当事人']==client and result['对方当事人']==opponent
    assert not any(k in result for k in ('授权已生效','已签署','已送达'))


def test_no_matching_litigant_and_manual_blank_remain_unfilled():
    assert not run('虚构其他客户')[0].get('当事人')
    assert run(manual=('当事人',))[0]['当事人']==''


@pytest.mark.parametrize('change',['quote','derivation','subject','client','conflict','scope'])
def test_changed_or_untrusted_identity_does_not_support_party(change):
    fields,units,cache=run()
    ref=deepcopy(fields['_provenance']['当事人'][0])
    if change=='quote':fields['_provenance']['委托人'][0]['quote']+='本授权已失效。'
    if change=='derivation':fields['_provenance']['委托人'][0]['derivation']='model_guessed_client'
    if change=='subject':fields['_provenance']['委托人'][0]['subject']='另一客户'
    if change=='client':fields['委托人']='另一客户'
    if change=='conflict':fields['_field_conflicts']=[dict(field='委托人',values=['星河演示公司','另一客户'])]
    if change=='scope':
        for k in ('当事人','对方当事人','地址'):
            fields.pop(k,None);fields['_provenance'].pop(k,None)
        recall(fields,fields['_provenance'],[],page_cache=cache,allowed_sources={('complaint.pdf',1)},
            document_units=units,manual_fields=(),method='local_agent',fact_review=[])
        assert not fields.get('当事人') and not fields.get('对方当事人')
    else:assert current_support(ref,fields) is None
