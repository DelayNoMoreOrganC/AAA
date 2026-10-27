from copy import deepcopy
from types import SimpleNamespace as NS

from source_fact_recall import recall_cached_source_facts
from form_drafts import derive_form_drafts
from complaint_brief import current_support
from pleading_parties import current_support as party_support
from document_title_review import title_evidence


def text(defendants='虚构甲', amount='1000', extra=''):
    return ('云帆\nABCD202601010001\n民事起诉状\n原告：虚构银行。\n被告：'+defendants+'。\n'
        '案由：被继承人债务清偿纠纷。\n诉讼请求：1、判令被告在继承虚构丙遗产的范围内向原告清偿贷款本金'+amount+
        '元及利息（暂计至起诉日；此后按合同约定利率计算至清偿之日，全部明细另附），'+extra+
        '并承担诉讼费用。\n事实与理由：虚构丙申请贷款，双方签订合同。此致虚构法院。')


def run(second=None, missing=False, manual=None):
    cache={('a.pdf',1):text(), ('b.pdf',1):second or text(), ('engagement.pdf',1):'委托人（甲方）：虚构银行。'}
    if missing: cache.pop(('b.pdf',1))
    units=[NS(doc_type='complaint',doc_id=i,source_path=p,start_page=0,end_page=0,confidence=.8,manual_catalog_seq=None)
           for i,p in enumerate(('a.pdf','b.pdf'))]
    fields={'案件类别':'民事','委托人':'虚构银行'}
    refs={'委托人':[dict(source_path='engagement.pdf',page=1,quote=cache[('engagement.pdf',1)],value='虚构银行',method='local_agent')]}
    conflicts=[]
    recall_cached_source_facts(fields,refs,conflicts,page_cache=cache,allowed_sources=set(cache),document_units=units,
        manual_fields=manual or {},fact_review=[])
    fields.update(_provenance=refs,_field_conflicts=conflicts)
    manifest=[dict(path=p,file_id=p,pages=1) for p in ('a.pdf','b.pdf','engagement.pdf')]
    return derive_form_drafts(fields,units,source_manifest=manifest,manual_fields=manual),units,manifest


def test_reference_header_does_not_hide_real_pleading_but_prose_still_blocks_it():
    assert title_evidence(text())['doc_type']=='complaint'
    assert title_evidence('关于他案的说明\n'+text()) is None
    assert title_evidence('证据目录\n'+text())['doc_type']=='evidence'


def test_multiple_versions_keep_common_identity_and_source_bound_brief_with_choices():
    fields,units,manifest=run(text('虚构甲、虚构乙',extra='另请求支付律师费，'))
    assert fields['当事人']=='虚构银行'
    assert not fields.get('对方当事人')
    assert '遗产的范围内' in fields['案情简介'] and '1000元' in fields['案情简介']
    assert '待核对' in fields['案情简介'] and '律师费' not in fields['案情简介']
    conflict=next(c for c in fields['_field_conflicts'] if c['field']=='对方当事人')
    assert set(conflict['values'])=={'虚构甲','虚构甲、虚构乙'}
    assert {r['source_path'] for r in conflict['sources']}=={'a.pdf','b.pdf'}
    for ref in fields['_provenance']['案情简介']:
        assert {r['source_path'] for r in current_support(ref,fields)}=={'a.pdf','b.pdf'}
    assert party_support(fields['_provenance']['当事人'][0],fields)


def test_different_principal_is_not_reported_as_a_common_amount():
    fields,_,_=run(text(amount='2000'))
    assert '共同记载' in fields['案情简介']
    assert '1000' not in fields['案情简介'] and '2000' not in fields['案情简介']


def test_negative_or_additional_limit_cannot_be_removed_from_common_request():
    fields,_,_=run(text('虚构乙',extra='但不请求本金给付，'))
    assert '共同诉请' not in fields['案情简介']
    assert '待核对' in fields['案情简介']


def test_missing_version_cannot_be_silently_ignored_and_manual_blanks_survive():
    fields,_,_=run(missing=True)
    assert '_intake_complaint_source' not in fields and '_pleading_parties_source' not in fields
    fields,_,_=run(text('虚构乙'),manual={'案情简介':'','当事人':''})
    assert fields['案情简介']==fields['当事人']==''


def test_source_edit_invalidates_consensus_and_changed_unit_cannot_reuse_summary():
    fields,units,manifest=run(text('虚构甲、虚构乙'))
    old=deepcopy(fields['_provenance']['案情简介'][0])
    fields['_intake_complaint_source']['documents'][1]['pages'][0]['quote']=text(amount='3000')
    assert current_support(old,fields) is None
    fresh,units,manifest=run(text('虚构甲、虚构乙'))
    units[1].end_page=1
    assert not derive_form_drafts(fresh,units,source_manifest=manifest).get('案情简介')
