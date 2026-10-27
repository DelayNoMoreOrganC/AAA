"""Fictional text fixtures; diagnostics must never include source body text."""
import json

import pytest

from ocr_review import find_ocr_review_issues


def block(page, text, confidence):
    return {'page_idx':page, 'type':'text', 'text':text, 'confidence':confidence}


def test_blank_page_after_contract_is_independent_and_keeps_its_own_page():
    path = 'fictional-contract.pdf'
    pages = ['虚构委托代理合同，双方约定律师代理范围及工作内容。', ' \n\t', '虚构合同签署页，委托人与代理人确认。']
    issues = find_ocr_review_issues({path:pages}, {})
    assert len(issues) == 1
    assert issues[0]['source_path'] == path and issues[0]['page'] == 2
    assert issues[0]['reason_codes'] == ['empty_text']
    assert issues[0]['mean_confidence'] is None


def test_sparse_scanned_page_is_reported_even_when_ocr_score_is_high():
    issue, = find_ocr_review_issues({'scan.pdf':['虚构签章']}, {'scan.pdf':[block(0,'虚构签章',.98)]})
    assert issue['reason_codes'] == ['sparse_ocr']
    assert issue['recognized_characters'] == 4 and issue['mean_confidence'] == .98


def test_low_confidence_page_requires_review_and_does_not_copy_body():
    body = '虚构保密正文标记，不应出现在页面问题、日志或界面摘要中。'
    issue, = find_ocr_review_issues({'scan.pdf':[body]}, {'scan.pdf':[block(0,body,.54)]})
    assert issue['reason_codes'] == ['low_confidence']
    assert issue['mean_confidence'] == .54 and issue['min_confidence'] == .54
    assert body not in json.dumps(issue, ensure_ascii=False)
    assert 'text' not in issue and 'quote' not in issue


def test_clear_ocr_and_short_text_layer_pages_are_not_flagged():
    text = '虚构清晰文书，记录委托事项和材料来源，不记载真实客户资料。'
    assert find_ocr_review_issues({'clear.pdf':[text], 'text.pdf':['签名','收据1000元']}, {'clear.pdf':[block(0,text,.99)]}) == []


def test_low_confidence_substantive_number_is_not_hidden_by_long_clear_text():
    text = '虚构清晰材料' * 60
    issue, = find_ocr_review_issues({'scan.pdf':[text+'100000']}, {'scan.pdf':[block(0,text,.99),block(0,'100000',.51)]})
    assert issue['mean_confidence'] > .95 and issue['low_confidence_blocks'] == 1
    assert issue['reason_codes'] == ['low_confidence']
    assert '1个文字片段' in issue['reason'] and '不代表全页' in issue['reason']


def test_one_uncertain_page_number_does_not_condemn_an_otherwise_clear_page():
    text = '虚构清晰材料' * 30
    assert find_ocr_review_issues({'scan.pdf':[text+'3']}, {'scan.pdf':[block(0,text,.99),block(0,'3',.3)]}) == []


@pytest.mark.parametrize('text', ['3','第 2 页','1/2','2共10页'])
def test_footer_only_result_is_reported_without_ocr_blocks(text):
    issue, = find_ocr_review_issues({'scan.pdf':[text]}, {})
    assert issue['reason_codes'] == ['page_number_only']


@pytest.mark.parametrize('score', [float('nan'),float('inf'),1.1,-.1,'unknown',True])
def test_invalid_confidence_is_not_treated_as_success(score):
    text = '虚构测试文书正文完整，需要核对识别质量。'
    issue, = find_ocr_review_issues({'scan.pdf':[text]}, {'scan.pdf':[block(0,text,score)]})
    assert issue['reason_codes'] == ['invalid_confidence']
    assert issue['mean_confidence'] is None


def test_pages_and_paths_do_not_share_layout_scores_or_shift_on_bad_indices():
    text = '虚构清晰文书正文，以下仅用于独立页码测试。'
    result = find_ocr_review_issues({'a.pdf':[text,text], 'b.pdf':[text]}, {'a.pdf':[block(-1,text,.1),block(1,text,.5),block(9,text,.1)]})
    assert [(row['source_path'],row['page']) for row in result] == [('a.pdf',2)]
