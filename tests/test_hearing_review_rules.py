from document_title_review import title_evidence
import pytest

MESSAGE='12368短信\n虚构市人民法院\n(2024)粤0604民初123号\n本案定于2024年8月9日上午9时在第三法庭开庭审理，请准时到庭。'

def test_hearing_message_requires_substantive_details():
    r=title_evidence(MESSAGE,case_type='civil')
    assert r['verified'] and r['doc_type']=='summons' and r['title']=='开庭通知截图'

@pytest.mark.parametrize('text',[
 MESSAGE.replace('开庭审理','缴费').replace('请准时到庭','请查收'),
 MESSAGE.replace('(2024)粤0604民初123号',''),
 MESSAGE.replace('第三法庭','本院'),
 MESSAGE+'本次开庭取消，时间另行通知。',
 '民事起诉状\n原告虚构甲。以下引用短信：\n'+MESSAGE,
 MESSAGE.replace('本案定于','本案拟定于'),
])
def test_other_messages_or_quoted_hearing_are_not_confirmed(text):
    r=title_evidence(text,case_type='civil')
    assert r is None or r['doc_type']!='summons' or not r['verified']

def test_dismissal_is_trial_ruling_not_preservation():
    r=title_evidence('虚构市人民法院\n民事裁定书\n(2024)粤0604民初123号\n本院认为本案不符合起诉条件。裁定如下：驳回原告虚构甲的起诉。')
    assert r['doc_type']=='ruling' and r['procedure_stage']=='trial'

def test_firm_conventions_preserve_distinct_material_types():
    letter='广东虚构律师事务所函\n虚构市人民法院：本所接受委托，指派虚构律师担任本案诉讼代理人。'
    assert title_evidence(letter,case_type='civil')['doc_type']=='firm_letter'
    assert title_evidence(letter,case_type='nonlit') is None
    notice='虚构市人民法院\n受理案件通知书\n(2024)粤0604民初123号\n本院已受理本案。'
    assert title_evidence(notice,case_type='admin')['doc_type']=='acceptance_notice'
    assert title_evidence(notice.replace('民初','执'),case_type='civil')['doc_type']=='execution'
