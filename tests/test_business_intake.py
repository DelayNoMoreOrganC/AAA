from copy import deepcopy
from types import SimpleNamespace as NS
import pytest
from business_intake import collect, draft, current_support, KEY
from form_drafts import derive_form_drafts

TEXT = ('非诉讼法律事务委托合同\n甲方：虚构甲。乙方：虚构律所。'
        '一、甲方委托的具体事项详述如下：1、协助办理遗嘱公证手续。'
        '2、仅为本次事项提供法律咨询，不包括诉讼代理。二、甲方可了解进展。')


def bundle(text=TEXT):
    u = NS(doc_type='contract', doc_id=1, source_path='fictional.pdf', start_page=0, end_page=0, confidence=.95)
    fields = {'案件类别': '非诉'}
    collect(fields, page_cache={('fictional.pdf', 1): text}, allowed_sources={('fictional.pdf', 1)}, document_units=[u])
    return fields, [u]


def test_nonlit_intake_keeps_limit_and_does_not_invent_completion():
    fields, units = bundle()
    result = derive_form_drafts(fields, units, source_manifest=[{'path':'fictional.pdf','pages':1}])
    assert '不包括诉讼代理' in result['案情简介']
    assert '委托合同约定' in result['案情简介']
    assert '已完成' not in result['案情简介'] and not result.get('结案小结')
    ref = result['_form_draft_sources']['案情简介'][0]
    assert current_support(ref, result)
    changed = deepcopy(result)
    changed[KEY]['pages'][0]['quote'] += '附件变化'
    assert current_support(ref, changed) is None


@pytest.mark.parametrize('value', ['', '人工确认的内容'])
def test_manual_value_including_blank_wins(value):
    fields, units = bundle()
    result = derive_form_drafts(fields, units, source_manifest=[{'path':'fictional.pdf','pages':1}], manual_fields={'案情简介':value})
    assert result['案情简介'] == value


def test_partial_scope_is_not_accepted_and_another_contract_invalidates_bundle():
    fields, units = bundle(TEXT.replace('二、', ''))
    assert KEY not in fields
    fields, units = bundle()
    assert draft(fields, units + units, lambda r: True) is None
    assert draft(fields, units, lambda r: False) is None
    units[0].end_page = 1
    assert draft(fields, units, lambda r: True) is None


def test_counsel_intake_is_explicitly_scope_excerpt_not_full_performance():
    text = ('常年法律顾问合同一、乙方律师担任常年法律顾问的主要工作内容：'
            '1、提供法律咨询；2、草拟、审查和修改合同；3、代理诉讼另行收费。二、工作方式')
    fields, units = bundle(text)
    fields['案件类别'] = '法律顾问'
    result = draft(fields, units, lambda r: True)[0]
    assert '部分服务范围' in result and '另行收费' in result
    assert '已完成' not in result


@pytest.mark.parametrize('category', ['民事','刑事','行政'])
def test_business_brief_never_replaces_litigation_intake(category):
    fields, units = bundle()
    fields['案件类别'] = category
    assert draft(fields, units, lambda r: True) is None

def test_blocked_field_and_category_mismatch_do_not_autofill():
    fields, units = bundle()
    fields['_form_draft_blocked_fields'] = {'案情简介'}
    assert draft(fields, units, lambda r: True) is None
    fields.pop('_form_draft_blocked_fields')
    fields['案件类别'] = '法律顾问'
    assert draft(fields, units, lambda r: True) is None
