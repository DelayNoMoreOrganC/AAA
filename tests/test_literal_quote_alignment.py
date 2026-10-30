"""Literal/source protocol examples, not recognition accuracy benchmarks."""
from types import SimpleNamespace
from copy import deepcopy
import pytest

from literal_quote_alignment import recover
from visual_document_workflow import _verify_facts


@pytest.mark.parametrize('submitted,source', [
    ('本案案由：__买卖合同纠纷。', '本案案由：买卖合同纠纷。'),
    ('本人与虚构乙买卖合同纠纷一案。', '本人与__虚构乙__买卖合同纠纷一案。'),
    ('本案案由：＿买卖合同纠纷。', '本案案由：_\n买卖合同纠纷。'),
])
def test_recover_exact_original_span_without_changing_value(submitted, source):
    row = recover('案由', '买卖合同纠纷', submitted, source)
    if submitted.replace('＿', '_').replace('\n', '') == source.replace('\n', ''):
        assert row is None  # Existing whitespace/NFKC comparison already works.
        return
    assert row['quote'] == source and row['accepted_field'] == '案由'
    left, right = row['alignment']['source_char_span']
    assert source[left:right] == row['quote']
    assert row['alignment']['submitted_quote'] == submitted


@pytest.mark.parametrize('field,value,quote,text', [
    ('案由','买卖合同纠纷','案由：_买卖合同纠纷。','案由：借款合同纠纷。'),
    ('案由','买卖合同纠纷','案由：_买卖合同纠纷。','案由：买卖合同纠纷。案由：买卖合同纠纷。'),
    ('案由','买卖合同纠纷','案由：_买卖合同纠纷。','案由：买卖合_同纠纷。'),
    ('案由','买卖合同纠纷','案由：买卖合同纠纷。','案由：__买卖合同纠纷。'),
    ('案由','买卖合同纠纷','案由：_买卖合同纠纷。','案由；买卖合同纠纷。'),
    ('案由','买卖合同纠纷','案由：_借款合同纠纷。','案由：买卖合同纠纷。'),
    ('收案日期','2024年1月2日','落款：_2024年1月2日。','落款：2024年1月2日。'),
    ('收案日期','2024年1月2日','收案日期：_2024年1月2日。','收案日期：2024年1月3日。'),
    ('合同号','ABC123','编号：_ABC123。','编号：ABC123。'),
    ('委托人','甲公司','委托人：_甲公司。','受委托人：甲公司。'),
    ('委托人','甲公司','委托人：_甲公司。','拟委托人：甲公司。'),
    ('案件或项目名称','甲诉乙','案件名称：_甲诉乙。','案件名称：甲诉乙。'),
    ('收费标准','9000元','固定律师费：_9000元。','固定律师费：8000元。'),
    ('案由','A_B事项','案由：__A_B事项。','案由：A_B事项。'),
])
def test_alignment_does_not_rewrite_values_drop_qualifiers_or_infer_roles(field,value,quote,text):
    assert recover(field,value,quote,text) is None


def test_pipeline_uses_original_source_quote_and_keeps_submitted_quote_for_audit():
    text = '授权委托书。现委托律师在委托人与_虚构乙_买卖合同纠纷一案中代理。'
    quote = '现委托律师在委托人与虚构乙买卖合同纠纷一案中代理'
    pages = SimpleNamespace(pages={'p': ('source.pdf', 0)}, texts={'source.pdf':[text]},
        read_pages={'p'}, text_views={}, source_identities={'source.pdf': {'sha256':'a'*64}}, read=lambda _:text)
    facts = [{'field':'案由','value':'买卖合同纠纷','quote':quote,'page_id':'p'}]
    before = deepcopy(pages.texts)
    accepted, refused, _, _ = _verify_facts(facts,pages,{'p'},{'p'},set(),set())
    assert len(accepted)==1 and refused==[] and pages.texts==before
    field,value,ref=accepted[0]
    assert field=='案由' and value=='买卖合同纠纷' and ref['quote'] in text
    assert ref['quote_alignment']['submitted_quote']==quote and ref['source_sha256']=='a'*64
    from form_drafts import _accepted, _scope
    fields={field:value,'_provenance':{field:[ref]}}
    manifest=[{'path':'source.pdf','pages':1,'sha256':'a'*64}]
    accepted_value,refs=_accepted(fields,field,set(),_scope(manifest))
    assert accepted_value==value and refs[0]['quote_alignment']==ref['quote_alignment']
    manifest[0]['sha256']='b'*64
    assert _accepted(fields,field,set(),_scope(manifest))==('',[])


def test_failed_visual_agreement_cannot_fall_back_to_underscore_recovery():
    text='案由：_买卖合同纠纷。'
    pages=SimpleNamespace(pages={'p':('source.pdf',0)},read=lambda _:text)
    facts=[{'field':'案由','value':'买卖合同纠纷','quote':'案由：买卖合同纠纷。','page_id':'p'}]
    accepted,refused,_,_=_verify_facts(facts,pages,{'p'},{'p'},set(),set(),visual_required={('案由','p')})
    assert not accepted and refused[0]['verification_code']=='visual_readback_unconfirmed'
