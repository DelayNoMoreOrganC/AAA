from copy import deepcopy
import pytest
from fee_display import collect, current, summarize
from pdf_doc_locator import DocumentUnit

TERMS = '一审基础律师费5000元；另按实际收回款项的2%收取风险代理费。基础费于合同订立后十日内支付，风险费于实际回款后结算。'
PAGE = '委托代理合同\n委托人（甲方）：虚构银行。\n收费约定：' + TERMS + '\n合同签订日期：2026年1月5日。'


def fixture():
    fields = {'收费标准': TERMS, '委托人': '虚构银行'}
    refs = {'收费标准': [{'value': TERMS, 'quote': '收费约定：' + TERMS,
                        'method': 'local_agent', 'source_path': 'contract.pdf', 'page': 1}]}
    unit = DocumentUnit(0, 'contract', 0, 0, '委托代理合同', source_path='contract.pdf', confidence=.95)
    collect(fields, refs, [], page_cache={('contract.pdf', 1): PAGE}, allowed_sources={('contract.pdf', 1)},
            document_units=[unit], manual_fields={})
    fields['_provenance'] = refs
    return fields


def test_summary_keeps_core_price_and_explicit_reference_without_replacing_terms():
    fields = fixture(); before = deepcopy(fields)
    display = current(fields)
    assert display['value'] == '基础5000元\n回款2%详合同'
    assert '一审' in display['note'] and '付款、结算条件' in display['note']
    assert fields == before and fields['收费标准'] == TERMS


@pytest.mark.parametrize('change', ['value', 'client', 'reference', 'source', 'conflict', 'human', 'custom_note'])
def test_summary_is_disabled_when_evidence_or_explicit_user_content_changes(change):
    fields = fixture()
    if change == 'value': fields['收费标准'] = TERMS.replace('5000', '8000')
    if change == 'client': fields['委托人'] = '另一客户'
    if change == 'reference': fields['_provenance']['收费标准'] = []
    if change == 'source': fields['_contract_fee_display']['page_text'] = PAGE.replace('5000', '8000')
    if change == 'conflict': fields['_field_conflicts'] = [{'field': '收费标准'}]
    if change == 'human': fields['_provenance']['收费标准'].append({'method': 'human', 'value': TERMS})
    if change == 'custom_note': fields['_preview_custom_values'] = {'立案审批表': {'p0-b0-r9-c0': ''}}
    assert current(fields) is None


@pytest.mark.parametrize('terms', [TERMS + '最高收费一万元。', TERMS + '另收差旅费1000元。',
    TERMS.replace('实际收回款项', '诉讼标的额'), TERMS.replace('2%', '200%'), TERMS.replace('5000元', '0元'),
    TERMS.replace('基础律师费', '已收律师费'), TERMS.replace('2%', '2%至5%')])
def test_unknown_extra_terms_basis_or_paid_status_is_not_shortened(terms):
    assert summarize(terms) is None


def test_amount_rate_and_stage_variants_are_not_tied_to_one_fixture():
    value = TERMS.replace('一审', '二审').replace('5000元', '1万元').replace('2%', '3.5%')
    assert summarize(value) == {'value': '基础1万元\n回款3.5%详合同', 'note': '二审收费条款及付款、结算条件详卷内委托代理合同。'}
