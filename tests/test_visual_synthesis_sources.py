"""Metadata/source-contract fixtures, not case recognition or output benchmarks."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace as NS
import pytest

from visual_fact_readback import receipts, attach
import visual_synthesis_sources as visual
from form_synthesis import collect_sources, generate, current_support, scope_supported, validate_candidate, KEY
from form_cell_contracts import source_plan
from case_fact_ledger import build


def reference(path, sha, field, value, quote):
    text = quote + '\nPRIVATE_TRANSCRIPTION_ONLY\n'
    pages = NS(pages={'f1p1': (str(path), 0)}, source_identities={str(path): {'sha256': sha}})
    first = {'field': field, 'page_id': 'f1p1', 'value': value, 'quote': quote,
             'source_path': str(path), 'page': 1, 'source_sha256': sha}
    response = {'facts': [{k: v for k, v in first.items() if k in ('field', 'page_id', 'value', 'quote')}],
                'page_readbacks': [{'page_id': 'f1p1', 'text': text, 'full_page_complete': True, 'legibility': 'clear'}]}
    response['facts'][0]['source_box'] = [0, 0, 1, .5]
    receipt = receipts(response, {(field, 'f1p1'): first}, pages)[(field, 'f1p1')]
    ref = {'source_path': str(path), 'page': 1, 'quote': quote, 'value': value, 'method': 'visual_agent_local_evidence'}
    attach(ref, receipt)
    return ref


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / 'source-protocol.bin'
    path.write_bytes(b'protocol source; not a PDF or case')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    field, value, quote = '委托人', '甲公司', '本案委托人：甲公司。'
    ref = reference(path, sha, field, value, quote)
    units = [NS(source_path=str(path), start_page=n, end_page=n, doc_type=kind, doc_id=n+1, confidence=.95)
             for n, kind in enumerate(('contract', 'legal_work'))]
    cache = {(str(path), 1): quote.replace('甲', '申'), (str(path), 2): '本案办理记录：律师核对申请资料。'}
    manifest = [{'path': str(path), 'pages': 2, 'sha256': sha, 'file_id': 'protocol'}]
    return {'path': path, 'units': units, 'cache': cache, 'manifest': manifest,
            'fields': {field: value}, 'provenance': {field: [ref]}}


def pool(sample, **changes):
    raw, coverage = collect_sources(sample['units'], sample['cache'], set(sample['cache']))
    return visual.apply(raw, coverage, sample['units'], changes.get('fields', sample['fields']),
        sample['provenance'], changes.get('conflicts', []), changes.get('manifest', sample['manifest']),
        max_chars=changes.get('max_chars', 72000))


def test_only_checked_quote_enters_writing_and_ocr_remains_intact(sample):
    cache = deepcopy(sample['cache'])
    sources, coverage = pool(sample)
    image = next(s for s in sources if s.get('evidence_kind') == visual.VERSION)
    assert image['text'] == sample['provenance']['委托人'][0]['quote']
    public = json.dumps([visual.public_source(s) for s in sources], ensure_ascii=False)
    assert 'PRIVATE_TRANSCRIPTION_ONLY' not in public and 'source_path' not in public and 'visual_reference' not in public
    assert '申公司' not in public and '甲公司' in public
    assert sample['cache'] == cache
    assert coverage['documents'][0]['complete_pages'] == 0
    assert coverage['visual_fields']['quarantined_text_pages'] == 1


def test_field_changes_and_conflicts_cannot_restore_bad_ocr_or_keep_old_quote(sample):
    for changes in ({'fields': {'委托人': '修改后的主体'}}, {'conflicts': [{'field': '委托人'}]}):
        sources, coverage = pool(sample, **changes)
        assert not any(s['page'] == 1 for s in sources)
        assert coverage['visual_fields']['quarantined_text_pages'] == 1


def test_replaced_source_cannot_reuse_old_visual_readback(sample):
    sources, coverage = pool(sample, manifest=[{**sample['manifest'][0], 'sha256': 'b' * 64}])
    assert not any(s.get('evidence_kind') == visual.VERSION for s in sources)
    assert coverage['visual_fields']['quarantined_text_pages'] == 0


def test_budget_and_document_confidence_are_not_bypassed(sample):
    sources, coverage = pool(sample, max_chars=2)
    assert not sources and all(d['complete_pages'] == 0 for d in coverage['documents'])
    sample['units'][0].confidence = .4
    sources, _ = pool(sample)
    assert not any(s['page'] == 1 for s in sources)


def test_exact_field_quote_required_not_its_whole_transcription(sample):
    sources, _ = pool(sample)
    source = sources[0]
    row = {'claims': [{'text': '本案委托人为甲公司。', 'evidence': [{'id': source['id'], 'quote': source['text']}]}], 'missing': []}
    assert validate_candidate('结案小结', row, sources)
    row['claims'][0]['evidence'][0]['quote'] = '委托人：甲公司'
    assert validate_candidate('结案小结', row, sources) is None
    row['claims'][0]['evidence'][0]['quote'] = source['text']
    row['claims'][0]['text'] = '已经完成所有服务。'
    assert validate_candidate('结案小结', row, sources) is None


def test_source_plan_and_ledger_do_not_expand_field_permissions(sample):
    sources, coverage = pool(sample)
    source = sources[0]
    source['allowed_fields'] = ['结案小结']
    plan = source_plan(sources, 'nonlit', ['案情简介', '结案小结'])
    assert source['id'] not in plan['案情简介']['source_ids']
    assert source['id'] in plan['结案小结']['source_ids']
    ledger = build(sources, coverage)
    assert source['id'] not in ledger['field_sources']['案情简介']
    assert ledger['documents'][0]['document_date'] is None


class Writer:
    def __init__(self, sample, mutate=False):
        self.calls = []
        self.sample, self.mutate = sample, mutate
    def complete(self, messages):
        payload = json.loads(messages[-1]['content'])
        self.calls.append(payload)
        image = next(s for s in payload['sources'] if s.get('evidence_kind') == visual.VERSION)
        row = {'claims': [{'text': '本案委托人为甲公司。', 'evidence': [{'id': image['id'], 'quote': image['text']}]}], 'missing': ['missing_work', 'missing_result']}
        if 'candidates' in payload:
            if self.mutate:
                self.sample['path'].write_bytes(b'changed source')
            row.update(supported=True, reason='ok')
        return {'fields': {'结案小结': row}}


def run(sample, **kwargs):
    client = Writer(sample, kwargs.pop('mutate', False))
    status = generate(client, sample['fields'], sample['provenance'], [], sample['units'], sample['cache'], set(sample['cache']),
        case_type='nonlit', manual_fields=('案情简介', '案件或项目名称', '审（办）结果'), **kwargs)
    sample['fields']['_provenance'] = sample['provenance']
    return client, status


def test_existing_two_step_writer_uses_visual_source_and_preserves_proof(sample):
    client, status = run(sample, source_manifest=sample['manifest'])
    assert status['status'] == 'generated' and status['requests'] == len(client.calls) == 2
    fields = sample['fields']; ref = sample['provenance']['结案小结'][-1]
    assert current_support(ref, fields) is not None and scope_supported(fields, sample['manifest'], sample['units'])
    assert fields[KEY]['fields']['结案小结']['missing'] == ['missing_work', 'missing_result', 'incomplete_source']
    fields['委托人'] = '修改后的主体'
    assert current_support(ref, fields) is None


def test_missing_visual_scope_blocks_paid_generation(sample):
    client, status = run(sample)
    assert not client.calls and status['status'] == 'visual_source_scope_required'


def test_material_changed_during_writing_never_commits_generated_content(sample):
    client, status = run(sample, source_manifest=sample['manifest'], mutate=True)
    assert status['status'] == 'source_changed' and len(client.calls) == 2
    assert '结案小结' not in sample['fields'] and KEY not in sample['fields']


def test_reference_removed_or_tampered_invalidates_generated_support(sample):
    run(sample, source_manifest=sample['manifest'])
    ref = sample['provenance']['结案小结'][-1]
    sample['provenance']['委托人'].clear()
    assert current_support(ref, sample['fields']) is None


def test_literal_outcome_can_support_its_own_rewritten_cell_without_losing_input(sample):
    field, value, quote = '结案小结', '被告向原告支付货款人民币20000元。', '本院判决如下：被告向原告支付货款人民币20000元。'
    ref = reference(sample['path'], sample['manifest'][0]['sha256'], field, value, quote)
    fields, provenance = {field: value}, {field: [ref]}
    units = [NS(source_path=str(sample['path']), start_page=0, end_page=0, doc_id=1, doc_type='judgment', confidence=.95)]
    cache = {(str(sample['path']), 1): quote.replace('20000', '20001')}
    class OutcomeWriter:
        def complete(self, messages):
            payload = json.loads(messages[-1]['content']); source = payload['sources'][0]
            row = {'claims': [{'text': '法院判决被告向原告支付货款人民币20000元。',
                              'evidence': [{'id': source['id'], 'quote': source['text']}]}], 'missing': ['missing_work']}
            if 'candidates' in payload: row.update(supported=True, reason='ok')
            return {'fields': {field: row}}
    status = generate(OutcomeWriter(), fields, provenance, [], units, cache, set(cache), case_type='civil',
        source_manifest=sample['manifest'], manual_fields=('案情简介', '案件或项目名称', '审（办）结果'))
    assert status['status'] == 'generated' and fields[field] != value
    fields['_provenance'] = provenance
    generated_ref = provenance[field][-1]
    assert current_support(generated_ref, fields) is not None
    provenance[field].remove(ref)
    assert current_support(generated_ref, fields) is None
