from copy import deepcopy
import pytest

from fact_evidence import validate_fact
from fee_settlement_evidence import FIELDS, amounts, current_support
from source_fact_recall import recall_cached_source_facts
from archive_pipeline import normalize_fields
from form_drafts import derive_form_drafts

NUMBER = '（2026）粤0999民初6801号'
TEXT = ('律师费结算单\n委托人：虚构样例银行\n案号：' + NUMBER + '\n'
        '应收业务费：5000元\n已收业务费：2000元\n尚欠业务费：3000元\n应退业务费：0元')
VALUES = dict(zip(FIELDS, ('5000元', '2000元', '3000元', '0元')))


def fixture(text=TEXT, extra=(), manual=None, model=None, allowed=None):
    client = '委托人（甲方）：虚构样例银行。'
    case = '本案案号：' + NUMBER + '。'
    fields = {'委托人': '虚构样例银行', '案号': NUMBER, **(model or {})}
    refs = {'委托人': [{'method': 'local_agent', 'value': fields['委托人'], 'quote': client, 'source_path': 'contract.pdf', 'page': 1}],
            '案号': [{'method': 'local_agent', 'value': NUMBER, 'quote': case, 'source_path': 'judgment.pdf', 'page': 1}]}
    cache = {('contract.pdf', 1): client, ('judgment.pdf', 1): case, ('fees.pdf', 1): text}
    for i, other in enumerate(extra): cache[('other-fees.pdf', i + 1)] = other
    conflicts, review = [], []
    metrics = recall_cached_source_facts(fields, refs, conflicts, page_cache=cache,
        allowed_sources=set(cache) if allowed is None else allowed, manual_fields=manual or {}, fact_review=review)
    fields.update(_provenance=refs, _field_conflicts=conflicts)
    return fields, review, metrics


def test_four_explicit_balances_reach_normalized_forms_with_case_sources():
    assert amounts(TEXT) == VALUES
    for key, value in VALUES.items():
        assert validate_fact(key, value, TEXT, TEXT)
    fields, _, metrics = fixture()
    for key, value in VALUES.items():
        assert fields[key] == value
        assert len(current_support(fields['_provenance'][key][-1], fields)) == 2
    normalized = normalize_fields(fields, case_type='civil', strict_evidence=True)
    draft = derive_form_drafts(normalized, [], source_manifest=[{'path': p, 'pages': 1} for p in ('fees.pdf','contract.pdf','judgment.pdf')])
    assert all(draft[key] == value for key, value in VALUES.items())
    assert metrics['additional_page_reads'] == metrics['additional_model_requests'] == 0


@pytest.mark.parametrize('text', [
    TEXT.replace('律师费结算单', '贷款发放凭证'),
    TEXT.replace('律师费结算单', '增值税发票'),
    TEXT.replace('律师费结算单', '委托代理合同'),
    TEXT.replace('律师费结算单', '律师费收据'),
    '引用模板\n' + TEXT, TEXT + '\n本单已作废。', TEXT + '\n其中含代垫费用。',
    TEXT.replace('已收业务费：2000元', '拟已收业务费：2000元'),
    TEXT.replace('已收业务费：2000元', '已收业务费：2000元（部分收款）'),
])
def test_invoice_loan_agreement_single_receipt_and_qualified_records_do_not_supply_balances(text):
    fields, _, _ = fixture(text)
    assert not any(fields.get(key) for key in FIELDS)


@pytest.mark.parametrize('replacement', ['200元', '2000', '2000万元', '-2000元', '2000元至3000元', '2000美元', '2000元另加2%'])
def test_cropped_or_changed_units_are_rejected(replacement):
    assert not validate_fact('已收业务费', replacement, TEXT, TEXT)


@pytest.mark.parametrize('text', [TEXT.replace('虚构样例银行', '虚构另一银行'),
    TEXT.replace('6801号', '9999号'), TEXT.replace('委托人：虚构样例银行\n', ''),
    TEXT.replace('案号：' + NUMBER + '\n', ''), TEXT + '\n案号：' + NUMBER,
    TEXT.replace('委托人：', '付款人：')])
def test_unrelated_missing_or_duplicate_identity_cannot_fill_even_valid_model_amounts(text):
    fields, review, _ = fixture(text, model={'已收业务费': '2000元'})
    assert not any(fields.get(key) for key in FIELDS)
    assert any(r['reason_code'] in ('fee_record_other_case', 'fee_record_scope_unverified')
               and r['source_path'] == 'fees.pdf' for r in review)


def test_conflicting_records_are_not_summed_or_latest_wins():
    fields, _, _ = fixture(extra=[TEXT.replace('2000元', '2500元')])
    assert not fields.get('已收业务费')
    assert any(r['field'] == '已收业务费' for r in fields['_field_conflicts'])
    assert fields['应收业务费'] == '5000元'
    fields, _, _ = fixture(extra=[TEXT])
    assert fields['已收业务费'] == '2000元'


def test_no_arithmetic_and_human_blank_and_value_are_preserved():
    text = TEXT.replace('尚欠业务费：3000元\n', '').replace('应退业务费：0元', '')
    fields, _, _ = fixture(text)
    assert not fields.get('尚欠业务费') and not fields.get('应退业务费')
    for value in ('', '人工另填'):
        fields, _, _ = fixture(manual={'已收业务费': value}, model={'已收业务费': value})
        assert fields['已收业务费'] == value


def test_identity_and_source_changes_invalidate_machine_balances():
    fields, _, _ = fixture()
    ref = deepcopy(fields['_provenance']['已收业务费'][0])
    fields['委托人'] = '虚构另一银行'
    assert current_support(ref, fields) is None
    fields, _, _ = fixture()
    fields['案号'] = NUMBER.replace('6801', '7777')
    assert current_support(ref, fields) is None
    fields, _, _ = fixture(allowed={('fees.pdf', 1), ('judgment.pdf', 1)})
    assert not fields.get('已收业务费')


def test_second_amount_label_cannot_hide_in_unparsed_qualified_row():
    fields, _, _ = fixture(TEXT + '\n已收业务费：2500元（含税）')
    assert not fields.get('已收业务费')


def test_conflicting_identity_alias_cannot_certify_balances():
    fields, _, _ = fixture()
    ref = fields['_provenance']['已收业务费'][0]
    fields['法院收案号'] = NUMBER.replace('6801', '9999')
    assert current_support(ref, fields) is None


def test_settlement_is_fee_catalog_material_not_proof_of_payment():
    from document_title_review import title_evidence
    result = title_evidence(TEXT, case_type='civil')
    assert result['verified'] and result['doc_type'] == 'invoice'
    assert result['reason_code'] == 'fee_settlement_document_not_payment_proof'
    other = title_evidence('民事起诉状\n原告诉称费用如下。\n' + TEXT, case_type='civil')
    assert other['doc_type'] == 'complaint'


def test_receipt_event_is_preserved_but_not_printed_as_cumulative_balance():
    text = '收据：实收律师费2000元'
    assert validate_fact('已收业务费', '2000元', text, text)
    fields, review, _ = fixture(text, model={'已收业务费': '2000元'})
    assert not fields['已收业务费']
    assert any(row['field'] == '已收业务费' for row in review)
    assert not validate_fact('已收业务费', '2000元', text, '如果' + text)


def test_recall_is_idempotent_and_does_not_accumulate_duplicate_fee_evidence():
    fields, _, _ = fixture()
    before = deepcopy(fields['_provenance'])
    cache = {('contract.pdf',1): '委托人（甲方）：虚构样例银行。',
             ('judgment.pdf',1): '本案案号：' + NUMBER + '。', ('fees.pdf',1): TEXT}
    stats = recall_cached_source_facts(fields, fields['_provenance'], fields['_field_conflicts'],
        page_cache=cache, allowed_sources=set(cache), fact_review=[])
    assert fields['_provenance'] == before and stats['accepted_count'] == 0


def test_contract_identifier_can_bind_when_court_case_number_is_not_on_fee_record():
    from fee_settlement_evidence import bound_amounts
    fields, _, _ = fixture()
    fields['合同号'] = 'GD-2026-68'
    fields['_provenance']['合同号'] = [{'method':'human', 'value':fields['合同号']}]
    text = TEXT.replace('案号：' + NUMBER, '委托合同编号：GD-2026-68')
    values, support = bound_amounts(text, fields)
    assert values == VALUES and support[1]['field'] == '合同号'
    assert not bound_amounts(text + '\n案号：（2026）粤0999民初999号', fields)[0]


@pytest.mark.parametrize('value', ['人民币5,000.00元', '1.5万元', '0元'])
def test_currency_and_units_remain_literal_through_normalization(value):
    text = TEXT.replace('应收业务费：5000元', '应收业务费：' + value)
    fields, _, _ = fixture(text)
    out = normalize_fields(fields, case_type='civil', strict_evidence=True)
    assert out['应收业务费'] == value


def mixed_model_fees(other, *, manual=None, unknown_conflict=False):
    fields, _, _ = fixture()
    client = '委托人（甲方）：虚构样例银行。'
    case = '本案案号：' + NUMBER + '。'
    def raw(text, path, value):
        return dict(source_path=path,page=1,quote=text,value=value,method='visual_agent_local_evidence')
    # Model first sees the unrelated amount and raises a provisional conflict
    # when it later reads this case's record. Both pages remain in the archive.
    fields['已收业务费'] = '9000元'
    fields['_provenance']['已收业务费'] = [raw(other,'other.pdf','9000元'), raw(TEXT,'fees.pdf','2000元')]
    conflict = {'field':'已收业务费','values':['9000元','2000元'],
                'source':deepcopy(fields['_provenance']['已收业务费'][1])}
    if unknown_conflict:
        conflict['values'].append('来源不明金额')
    fields['_field_conflicts'] = [conflict]
    cache = {('contract.pdf',1):client, ('judgment.pdf',1):case, ('fees.pdf',1):TEXT, ('other.pdf',1):other}
    review = []
    recall_cached_source_facts(fields, fields['_provenance'], fields['_field_conflicts'],
        page_cache=cache, allowed_sources=set(cache), manual_fields=manual or {}, fact_review=review)
    return fields, review


def test_existing_legacy_conflict_is_not_silently_rewritten_by_new_candidate_order():
    other = TEXT.replace('6801号','9999号').replace('2000元','9000元')
    fields, review = mixed_model_fees(other)
    assert not fields['已收业务费']
    assert any(not r.get('resolved') for r in fields['_field_conflicts'] if r['field']=='已收业务费')
    assert len(fields['_provenance']['已收业务费']) == 2


@pytest.mark.parametrize('other', [TEXT.replace('2000元','9000元'),
    TEXT.replace('案号：' + NUMBER + '\n','').replace('2000元','9000元'),
    TEXT.replace('6801号','9999号').replace('2000元','9000元') + '\n案号：' + NUMBER])
def test_ambiguous_identity_or_real_amount_conflict_stays_pending(other):
    fields, _ = mixed_model_fees(other)
    assert not fields.get('已收业务费')
    assert any(not r.get('resolved') for r in fields['_field_conflicts'])


def test_unknown_conflict_or_human_decision_cannot_be_auto_dismissed():
    other = TEXT.replace('6801号','9999号').replace('2000元','9000元')
    fields, _ = mixed_model_fees(other, unknown_conflict=True)
    assert not fields.get('已收业务费') and not fields['_field_conflicts'][0].get('resolved')
    fields, _ = mixed_model_fees(other, manual={'已收业务费':'9000元'})
    assert fields['已收业务费'] == '9000元'
    assert not fields['_field_conflicts'][0].get('resolved')
