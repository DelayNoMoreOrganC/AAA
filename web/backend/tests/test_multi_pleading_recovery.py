from types import SimpleNamespace as NS
from source_fact_recall import recall_cached_source_facts
from form_drafts import derive_form_drafts
from pdf_doc_locator import DocumentUnit
from app.services.field_assurance import field_assurance
from app.services.field_decisions import field_candidates


def recovered():
    def text(defendant):
        return ('云帆\nABCD202601010001\n民事起诉状\n原告：虚构银行。\n被告：'+defendant+'。\n'
            '诉讼请求：判令被告在继承虚构丙遗产的范围内清偿借款本金1000元及利息。\n'
            '事实与理由：虚构丙借款后未归还。此致虚构法院。')
    cache={('a.pdf',1):text('虚构甲'),('b.pdf',1):text('虚构甲、虚构乙'),('contract.pdf',1):'委托人（甲方）：虚构银行。'}
    units=[DocumentUnit(i,'complaint',0,0,source_path=p,confidence=.8) for i,p in enumerate(('a.pdf','b.pdf'))]
    fields={'案件类别':'民事','委托人':'虚构银行'}
    refs={'委托人':[dict(method='local_agent',value='虚构银行',source_path='contract.pdf',page=1,quote=cache[('contract.pdf',1)])]}
    conflicts=[]
    recall_cached_source_facts(fields,refs,conflicts,page_cache=cache,allowed_sources=set(cache),document_units=units,fact_review=[])
    fields.update(_provenance=refs,_field_conflicts=conflicts)
    manifest=[dict(file_id=p,path=p,filename=p,pages=1) for p in ('a.pdf','b.pdf','contract.pdf')]
    fields=derive_form_drafts(fields,units,source_manifest=manifest)
    return fields,manifest


def test_common_brief_and_party_have_live_sources_and_version_candidates_are_clickable():
    fields,manifest=recovered()
    for name in ('案情简介','当事人'):
        state=field_assurance(name,fields[name],fields,source_manifest=manifest)
        assert state['source_count']>=2 and state['status'] in ('derived_draft','source_supported')
    task=NS(fields=fields,source_manifest=manifest,issues=[])
    candidates=field_candidates(task,'对方当事人')
    assert {c['value'] for c in candidates}=={'虚构甲','虚构甲、虚构乙'}
    assert {s['file_id'] for c in candidates for s in c['sources']}=={'a.pdf','b.pdf'}


def test_missing_one_pleading_source_cannot_keep_verified_form_content():
    fields,manifest=recovered()
    for name in ('案情简介','当事人'):
        state=field_assurance(name,fields[name],fields,source_manifest=[r for r in manifest if r['path']!='b.pdf'])
        assert state['status'] not in ('derived_draft','source_supported')


def test_batch_fee_and_contract_date_keep_sources_and_require_the_same_material_scope():
    from engagement_intake import recall
    fields, manifest = recovered()
    texts = [
        'ABCD202601010001\n委托代理合同\n（适用风险代理）\n委托人（甲方）：虚构银行。',
        '鉴于甲方与虚构丙等11户的需要。\n第四条律师代理的方式、费用、支付条件和方式\n'
        '本合同代理方式为风险代理，并按下列第1项执行：1.甲方不支付基础代理费。'
        '甲方按下列第4点向乙方计付律师代理费用：（4）其他付款条件：（1）无基础费用。'
        '（2）现金回款2.5%；调解另按1%。第五条其他事项',
        '合同各方签章：\n甲方（盖章）：2026年1月5日\n乙方（盖章）：2026年1月5日\n附件：清单',
    ]
    cache = {('contract.pdf', i+1): text for i,text in enumerate(texts)}
    scope = set(cache) | {('a.pdf',1), ('b.pdf',1)}
    manifest[-1]['pages'] = 3
    recall(fields,fields['_provenance'],fields['_field_conflicts'],page_cache=cache,
        allowed_sources=scope,document_units=[NS(doc_type='contract',source_path='contract.pdf',start_page=0,end_page=2)],
        manual_fields=(),method='local_agent')
    fields=derive_form_drafts(fields,[],source_manifest=manifest)
    for name,expected in [('收费标准','source_supported'),('立案审批日期','convention_default')]:
        assert fields[name]
        state=field_assurance(name,fields[name],fields,source_manifest=manifest)
        assert state['status']==expected
        assert state['source_count']>=3
        state=field_assurance(name,fields[name],fields,source_manifest=manifest+[dict(path='new.pdf',pages=1)])
        assert state['status'] not in ('source_supported','convention_default')
