"""Field-protocol fixtures, not a synthetic case or recognition benchmark."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

import visual_fact_readback as readback
from visual_document_workflow import _verify_facts


@pytest.fixture
def sample(tmp_path):
    path = str(tmp_path / 'scope.pdf')
    text = '委托人：甲公司\n受托人：乙律师事务所\n委托办理本案。'
    cached = text.replace('甲公司', '申公司')
    first = {'field': '委托人', 'value': '甲公司', 'quote': '委托人：甲公司', 'page_id': 'f1p1'}
    source = {'source_path': path, 'sha256': 'a' * 64, 'page_count': 1}
    pages = SimpleNamespace(pages={'f1p1': (path, 0)}, source_identities={path: source},
        texts={path: [cached]}, read_pages={'f1p1'}, text_views={}, read=lambda key: cached)
    action = {'tool': 'record_fields', 'document_id': 'd1', 'facts': [first]}
    _, rejects, _, seen = _verify_facts(action['facts'], pages, {'f1p1'}, {'f1p1'}, set(), set())
    frozen = readback.proposal_scope(action, [('委托人', 'f1p1')], rejects, pages)
    second = deepcopy(action)
    second['facts'][0]['source_box'] = [0, 0, 1, .5]
    second['page_readbacks'] = [{'page_id': 'f1p1', 'text': text,
                               'full_page_complete': True, 'legibility': 'clear'}]
    return pages, frozen, second, seen


def verify(sample, response=None):
    pages, frozen, second, seen = sample
    response = response or second
    return _verify_facts(response['facts'], pages, {'f1p1'}, {'f1p1'}, set(), seen,
        visual_receipts=readback.receipts(response, frozen, pages), visual_required=frozen)


def test_image_readback_can_support_same_proposal_without_rewriting_ocr(sample):
    pages, frozen, second, _ = sample
    before = deepcopy(pages.texts)
    verified, refused, _, _ = verify(sample)
    assert len(verified) == 1 and not refused and pages.texts == before
    field, value, ref = verified[0]
    assert readback.reference_supported(ref, field, value)
    assert ref['text_basis']['original_ocr_retained'] is True
    assert ref['visual_readback']['body']['accuracy_verified'] is False


@pytest.mark.parametrize('change', ['uncertain', 'partial', 'missing', 'different', 'duplicate', 'wrong_role', 'box', 'scope', 'source_changed'])
def test_readback_never_wins_without_all_required_checks(sample, change):
    pages, frozen, response, _ = sample
    if change == 'uncertain': response['page_readbacks'][0]['legibility'] = 'uncertain'
    if change == 'partial': response['page_readbacks'][0]['full_page_complete'] = False
    if change == 'missing': response.pop('page_readbacks')
    if change == 'different':
        # Even when the new value matches OCR, visual disagreement stays open.
        response['facts'][0].update(value='申公司', quote='委托人：申公司')
        response['page_readbacks'][0]['text'] = response['page_readbacks'][0]['text'].replace('甲公司', '申公司')
    if change == 'duplicate': response['page_readbacks'].append(deepcopy(response['page_readbacks'][0]))
    if change == 'wrong_role': response['page_readbacks'][0]['text'] = '受委托人：甲公司'
    if change == 'box': response['facts'][0]['source_box'] = [1, 0, 0, 1]
    if change == 'scope': response['page_readbacks'][0]['page_id'] = 'f2p1'
    if change == 'source_changed': next(iter(pages.source_identities.values()))['sha256'] = 'b' * 64
    verified, refused, _, _ = verify(sample)
    assert not verified and refused[0]['verification_code'] == 'visual_readback_unconfirmed'


def test_receipt_bound_to_value_page_full_context_and_source(sample):
    field, value, ref = verify(sample)[0][0]
    manifest = [{'path': ref['source_path'], 'pages': 1, 'sha256': 'a' * 64}]
    assert readback.reference_supported(ref, field, value, manifest)
    for key, replacement in [('value', '申公司'), ('page', 2), ('source_sha256', 'b' * 64), ('quote', '无依据')]:
        altered = deepcopy(ref); altered[key] = replacement
        assert not readback.reference_supported(altered, field, altered['value'], manifest)
    altered = deepcopy(ref); altered['visual_readback']['body']['page_text'] += '任意修改'
    assert not readback.reference_supported(altered, field, value, manifest)
    manifest[0]['sha256'] = 'b' * 64
    assert not readback.reference_supported(ref, field, value, manifest)


def test_model_cannot_mint_a_receipt_inside_its_fact(sample):
    _, _, response, _ = sample
    response['facts'][0]['visual_readback'] = {'body': {}, 'sha256': 'anything'}
    response.pop('page_readbacks')
    assert not verify(sample)[0]


def test_previously_accepted_value_is_not_replaced(sample):
    pages, frozen, second, seen = sample
    result = _verify_facts(second['facts'], pages, {'f1p1'}, {'f1p1'}, {('委托人', '甲公司')}, seen,
        visual_receipts=readback.receipts(second, frozen, pages), visual_required=frozen)
    assert not result[0] and result[2] == 1
