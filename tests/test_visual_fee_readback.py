"""Protocol fixtures only: no OCR, provider call, or model-accuracy claim."""
from copy import deepcopy
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest
import visual_fee_readback as visual
from source_fee_notice import recall_fee, reference_supported, current_support
from form_cell_contracts import optional_output

FIXTURES = runpy.run_path(str(Path(__file__).with_name('test_source_fee_notice.py')))
TEXT = FIXTURES['CHECKED_NOTICE']
FIELDS = FIXTURES['FIELDS']


def action(text=TEXT, **changes):
    return {'tool': 'record_fields', 'document_id': 'd1', 'facts': [],
        'page_readbacks': [{'page_id': 'f1p1', 'text': text,
            'full_page_complete': True, 'legibility': 'clear', **changes}]}


def proof_sample():
    cached = TEXT.replace('●', '').replace('□', '')
    pages = SimpleNamespace(pages={'f1p1': ('notice.pdf', 0)},
        source_identities={'notice.pdf': {'sha256': 'a' * 64, 'page_count': 1}},
        texts={'notice.pdf': [cached]})
    scope = visual.proposal_scope(action(), 'f1p1', pages)
    proof = visual.receipts(action(), scope, pages)[0]
    return pages, scope, proof


def fill(proof, fields=None, manual=()):
    fields = deepcopy(FIELDS if fields is None else fields)
    pages, _, _ = proof_sample()
    recall_fee(fields, fields.setdefault('_provenance', {}), fields.setdefault('_field_conflicts', []),
        page_cache={('notice.pdf', 1): pages.texts['notice.pdf'][0]}, allowed_sources={('notice.pdf', 1)},
        visual_candidates=[proof], manual_fields=manual, fact_review=[])
    return fields


def test_two_page_reads_preserve_conditions_and_original_ocr():
    pages, _, proof = proof_sample()
    before = deepcopy(pages.texts)
    fields = fill(proof)
    ref = fields['_provenance']['收费标准'][0]
    assert fields['收费标准'] == '固定9000元\n条件见通知书'
    assert ref['quote'] == TEXT and '扣减' in ref['fee_terms'] and '债权转让' in ref['fee_terms']
    assert reference_supported('收费标准', fields['收费标准'], ref, fields)
    assert optional_output('收费标准', fields['收费标准'], fields)['code'] == 'supported_optional'
    assert pages.texts == before
    assert not any(fields.get(k) for k in ('已收业务费', '应收业务费', '立案审批日期', '合同号'))


@pytest.mark.parametrize('change', ['amount', 'mark', 'condition', 'subject', 'incomplete', 'unclear', 'duplicate', 'wrong_page', 'hash'])
def test_disagreement_or_incomplete_observation_never_supplies_fee(change):
    pages, scope, _ = proof_sample()
    second = action()
    row = second['page_readbacks'][0]
    if change == 'amount': row['text'] = TEXT.replace('9000', '8000')
    if change == 'mark': row['text'] = TEXT.replace('●', '□')
    if change == 'condition': row['text'] = TEXT + '附加收费条款。'
    if change == 'subject': row['text'] = TEXT.replace(FIELDS['委托人'], '另一公司')
    if change == 'incomplete': row['full_page_complete'] = False
    if change == 'unclear': row['legibility'] = 'uncertain'
    if change == 'duplicate': second['page_readbacks'].append(deepcopy(row))
    if change == 'wrong_page': row['page_id'] = 'f1p2'
    if change == 'hash': pages.source_identities['notice.pdf']['sha256'] = 'b' * 64
    assert not visual.receipts(second, scope, pages)


def test_reading_does_not_override_case_identity_conflicts_or_manual_blank():
    _, _, proof = proof_sample()
    assert '收费标准' not in fill(proof, {**FIELDS, '对方当事人': '他案被告'})
    assert '收费标准' not in fill(proof, {k: v for k, v in FIELDS.items() if k != '案由'})
    assert '收费标准' not in fill(proof, manual=['收费标准'])
    assert '收费标准' not in fill(proof, {**FIELDS, '_field_conflicts': [{'field': '案由'}]})
    fields = fill(proof, {**FIELDS, '收费标准': '人工值'})
    assert fields['收费标准'] == '人工值'


def test_proof_must_remain_current_in_raw_and_derived_references():
    _, _, proof = proof_sample()
    fields = fill(proof)
    ref = fields['_provenance']['收费标准'][0]
    manifest = [{'path': 'notice.pdf', 'pages': 1, 'sha256': 'a' * 64}]
    assert current_support(ref, fields, manifest) == []
    derived = {**ref, 'method': 'derived_form_draft', 'input_method': ref['method'],
        'input_field': '收费标准', 'input_value': ref['value'], 'value': '归纳内容'}
    assert current_support(derived, fields, manifest) == []
    manifest[0]['sha256'] = 'b' * 64
    assert current_support(derived, fields, manifest) is None
    ref['notice_visual_readback']['body']['second_text'] += '修改'
    assert optional_output('收费标准', fields['收费标准'], fields)['value'] == ''


def test_already_readable_choices_do_not_spend_an_extra_review():
    pages, _, _ = proof_sample()
    pages.texts['notice.pdf'][0] = TEXT
    assert not visual.proposal_scope(action(), 'f1p1', pages)


def test_disagreement_with_readable_ocr_still_needs_review_and_keeps_conflict():
    pages, _, _ = proof_sample()
    pages.texts['notice.pdf'][0] = TEXT.replace('9000', '8000')
    scope = visual.proposal_scope(action(), 'f1p1', pages)
    assert scope
    proofs = visual.receipts(action(), scope, pages)
    fields, provenance, conflicts = deepcopy(FIELDS), {}, []
    recall_fee(fields, provenance, conflicts, page_cache={('notice.pdf', 1): pages.texts['notice.pdf'][0]},
        allowed_sources={('notice.pdf', 1)}, visual_candidates=proofs, fact_review=[])
    assert '收费标准' not in fields and conflicts[0]['reason_code'] == 'fee_notice_terms_conflict'


def test_page_text_is_not_accepted_as_a_receipt_from_model():
    pages, scope, proof = proof_sample()
    second = {'facts': [], 'notice_visual_readback': proof}
    assert not visual.receipts(second, scope, pages)
