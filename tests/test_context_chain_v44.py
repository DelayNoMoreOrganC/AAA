from copy import deepcopy

import pytest

from complaint_brief import collect, summarize, current_support
from document_title_review import title_evidence
from form_drafts import derive_form_drafts
from pdf_doc_locator import DocumentUnit


@pytest.mark.parametrize('title,body', [
    ('评估结果通知书', '本院执行中委托评估，现告知评估结果。'),
    ('拍卖事项通知', '本院拟于下月拍卖案涉财产。'),
    ('拍卖事项通知书', '本院拟于下月拍卖案涉财产。'),
    ('执行情况告知书', '本院现将执行情况告知如下。'),
])
def test_execution_process_notices_are_placement_not_completion(title, body):
    source = f'虚构区人民法院\n{title}\n（2026）虚0101执88号\n{body}'
    result = title_evidence(source)
    assert result['verified'] and result['doc_type'] == 'execution'
    for wrong in ('民初', '执保'):
        assert not title_evidence(source.replace('执88', wrong+'88'))['verified']
    assert not title_evidence(source.replace('（2026）虚0101执88号', ''))['verified']
    assert title_evidence('证据清单\n'+source)['doc_type'] == 'evidence'


def test_preservation_execution_ruling_uses_case_stage_not_word_execution():
    text = '虚构区人民法院\n执行裁定书\n（2026）虚0101执保88号\n本院裁定如下：冻结被申请人财产。'
    result = title_evidence(text)
    assert result['verified'] and result['doc_type'] == 'preservation'
    assert result['procedure_stage'] == 'trial'
    assert not title_evidence(text.replace('冻结被申请人财产', '驳回其他事项'))['verified']


def test_preservation_future_renewal_does_not_negate_completed_clause():
    prefix = '虚构区人民法院\n财产保全情况告知书\n（2026）虚0101执保88号\n'
    assert title_evidence(prefix+'本院已经冻结案涉账户。如需继续冻结，请申请续封。')['verified']
    assert not title_evidence(prefix+'本院拟冻结案涉账户。如需继续冻结，请申请续封。')['verified']


def test_reviewed_execution_notice_enters_inventory_without_claiming_service():
    unit = DocumentUnit(1,'execution',0,0,'评估结果通知书',source_path='fictional.pdf',confidence=.85)
    fields={'_visual_classification_review':[{'source_path':'fictional.pdf','page':1,
        'method':'local_title_context_review','independent_title_verified':True,
        'reason_code':'execution_process_notice_verified','effective_doc_type':'execution',
        'title':'评估结果通知书','procedure_stage':'enforcement'}]}
    result=derive_form_drafts(fields,[unit],source_manifest=[{'path':'fictional.pdf','pages':1}])
    assert result['法院文件清单']=='《评估结果通知书》（原材料第1页）'
    assert '送达日期' not in result


PATH = 'fictional.pdf'
TEXT = '民事起诉状\n原告：虚构甲。被告：虚构乙。\n诉讼请求：一、判令被告返还借款10万元。\n事实与理由：双方订立借款合同，被告未按约还款。此致\n虚构区人民法院'


def prepared(text=TEXT):
    fields = {'案件类别':'民事', '委托人':'虚构甲', '案由':'民间借贷纠纷', '结案小结':'法院裁定驳回起诉。'}
    unit = DocumentUnit(1,'complaint',0,0,'民事起诉状',source_path=PATH, confidence=.9)
    collect(fields, page_cache={(PATH,1):text}, allowed_sources={(PATH,1)}, document_units=[unit])
    return fields, [unit]


def test_intake_draft_uses_allegations_and_requests_not_outcome():
    fields, units = prepared()
    result = derive_form_drafts(fields, units, source_manifest=[{'path':PATH,'pages':1,'file_id':'a'}])
    assert result['案情简介'] == '原告诉称：双方订立借款合同，被告未按约还款。诉请摘录：判令被告返还借款10万元。'
    assert '驳回' not in result['案情简介']
    for ref in result['_provenance']['案情简介']:
        assert current_support(ref, result) is not None
        changed=deepcopy(result); changed['案情简介']='任意改写'
        assert current_support(ref, changed) is None
    manual=derive_form_drafts(result,units,manual_fields={'案情简介':''},source_manifest=[{'path':PATH,'pages':1}])
    assert manual['案情简介'] == ''


def test_extract_never_cuts_money_or_guesses_missing_section():
    fields,_=prepared(TEXT.replace('判令被告返还借款10万元。','判令被告'+ '补充条件'*45+'支付10万元。'))
    assert '_intake_complaint_source' not in fields
    fields,_=prepared(TEXT.replace('事实与理由','其他说明'))
    assert '_intake_complaint_source' not in fields


def test_source_bundle_cannot_cross_scope_change_unit_or_use_partial_document():
    fields,units=prepared()
    for manifest in ([], [{'path':'other.pdf','pages':1}]):
        assert not derive_form_drafts(fields,units,source_manifest=manifest).get('案情简介')
    units[0].end_page=1
    assert not derive_form_drafts(fields,units,source_manifest=[{'path':PATH,'pages':2}]).get('案情简介')
    collect(fields,page_cache={(PATH,1):TEXT},allowed_sources={(PATH,1)},document_units=units)
    assert '_intake_complaint_source' not in fields
    fields,units=prepared()
    collect(fields,page_cache={(PATH,1):TEXT},allowed_sources={(PATH,1)},document_units=units*2)
    assert '_intake_complaint_source' not in fields


def test_quoted_pleading_in_judgment_is_not_a_pleading():
    fields,_=prepared('虚构区人民法院\n民事判决书\n原告起诉状载明：\n'+TEXT)
    assert '_intake_complaint_source' not in fields


def test_long_structured_loan_claim_keeps_categories_without_truncating_interest_formula():
    claim = ('【合计：虚构金额】1、判令被告向原告清偿贷款本金10万元及利息、罚息、复利'
             '（按合同约定计算。'+'附带计算说明'*30+'）；'
             '2、判令被告向原告支付律师费2000元；'
             '3、判令原告对被告提供抵押的虚构房产处置款享有优先受偿权；'
             '4、判令被告承担本案全部诉讼费用。')
    text = TEXT.replace('一、判令被告返还借款10万元。',claim)
    fields,_=prepared(text)
    value=summarize(fields['_intake_complaint_source'])
    assert '诉请概括：清偿借款本金及利息、罚息、复利' in value
    assert '10万元' not in value and '已支付' not in value
    fields,_=prepared(text.replace('2、判令被告向原告支付','2、不请求被告向原告支付'))
    assert '_intake_complaint_source' not in fields
