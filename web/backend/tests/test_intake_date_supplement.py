from copy import deepcopy
from types import SimpleNamespace
import hashlib

import pytest
from tests.test_fee_supplement import setup, context
from tests.test_task_workflow import fixture_analysis
from app.services import task_workflow as workflow
from app.services.task_sources import source_version
from app.services.evidence_links import supporting_refs
from app.services.party_binding_state import reconcile_party_bindings
import archive_pipeline as ap
from pdf_doc_locator import DocumentUnit
from source_fact_recall import recall_cached_source_facts
from intake_contract_date import FIELD, KEY, recall, current_support

CONTRACT = ('委托代理合同\n委托人（甲方）：虚构银行。受托人：虚构律师事务所。\n'
    '代理虚构银行诉虚构甲公司金融借款合同纠纷。\n合同载明签订日期：2026年1月5日。')


def arrange(tmp_path, text=None, manual=None):
    parts = setup(tmp_path)
    parent, task, previous, snapshot, fee = parts
    first = parent.source_manifest[0]
    first['sha256'] = hashlib.sha256(CONTRACT.encode()).hexdigest()
    fields = previous.fields
    fields.update(对方当事人='虚构甲公司', 案由='金融借款合同纠纷')
    cache = {(first['path'], 1): CONTRACT}
    cache[(parent.source_manifest[1]['path'], 1)] = fields['_provenance']['案号'][0]['quote']
    units = [DocumentUnit(0, 'contract', 0, 0, source_path=first['path'])]
    assert recall(fields, fields['_provenance'], [], page_cache=cache, allowed_sources=set(cache), document_units=units) == 1
    if manual is not None:
        parent.manual_fields[FIELD] = manual; fields[FIELD] = manual
    parent.fields = deepcopy(fields)
    parent.source_version = source_version(parent.source_manifest, 'civil', '')
    text = fee if text is None else text
    task.source_manifest[-1]['sha256'] = hashlib.sha256(text.encode()).hexdigest()
    task.source_version = source_version(task.source_manifest, 'civil', '')
    snapshot['workflow'].update(source_version=parent.source_version, source_manifest=deepcopy(parent.source_manifest),
                                manual_fields=deepcopy(parent.manual_fields))
    return parent, task, previous, snapshot, text


def run(parts, monkeypatch, *, skip_page=False, ocr=False, low_confidence=False):
    parent, task, previous, snapshot, text = parts
    before = deepcopy(previous)
    monkeypatch.setattr(workflow, 'snapshot_exists', lambda *_: True)
    monkeypatch.setattr(workflow, 'load_analysis', lambda *_: (deepcopy(previous), deepcopy(snapshot)))
    calls = []
    def analyze(case_type, *, sources, local_recall_context, **kwargs):
        calls.append([s.path for s in sources])
        source = sources[0].path
        result = fixture_analysis(source, {})
        result.fields = {}
        refs, conflicts, review = {}, [], []
        cache = {} if skip_page else {(source, 1): text}
        recall_cached_source_facts(result.fields, refs, conflicts, page_cache=cache, allowed_sources={(source,1)},
            document_units=result.doc_spans, fact_review=review, local_recall_context=local_recall_context)
        result.fields.update(_provenance=refs, _field_conflicts=conflicts, _fact_review=review)
        if ocr: result.fields['_ocr_review'] = [dict(source_path=source, page=1, reason='低质量')]
        if low_confidence: result.low_confidence_items = [dict(doc_id=0)]
        return result
    engine = SimpleNamespace(analyze_archive=analyze, compute_found_seqs=ap.compute_found_seqs,
        compute_missing_items=ap.compute_missing_items)
    files = [SimpleNamespace(id=r['file_id'], abs_path=r['path'], doc_type=r['doc_type']) for r in task.source_manifest]
    out, manual, conflicts = workflow.analyze_with_parent(engine, task, parent, files,
        dict(workflow_case_type='civil'), 'fictional-org', lambda _: None)
    assert calls == [[task.source_manifest[-1]['path']]] and previous == before
    out.fields = reconcile_party_bindings(out.fields, manual, task.source_manifest)
    return out, conflicts


def test_fully_read_settlement_preserves_default_and_keeps_frozen_source_scope(tmp_path, monkeypatch):
    parts = arrange(tmp_path)
    out, conflicts = run(parts, monkeypatch)
    assert out.fields[FIELD] == '2026年1月5日' and not conflicts
    ref = out.fields['_provenance'][FIELD][-1]
    assert current_support(ref, out.fields) is not None
    assert supporting_refs(ref, out.fields, parts[1].source_manifest) is not None
    assert len(out.fields[KEY]['scope_certificates']) == 3
    assert len(out.fields[KEY]['supplement_checks']) == 1
    assert out.fields['已收业务费'] == '2000元'
    for i in range(3):
        changed = deepcopy(parts[1].source_manifest); changed[i]['sha256'] = 'f' * 64
        assert supporting_refs(ref, out.fields, changed) is None
    assert len(out.doc_spans) == 3


@pytest.mark.parametrize('text', [
    '无法识别的材料\n一些内容',
    '律师费结算单\n合同签订日期：2026年2月1日。',
    '律师费结算单\n原委托日期有误，应予更正。',
    '律师费结算单\n委托代理合同\n签订日期：2026年2月1日。',
    '委托代理合同\n签订日期：2026年1月5日。',
    CONTRACT.replace('合同载明签订日期', '拟签订日期'),
    CONTRACT.replace('虚构甲公司', '另一当事人'),
    CONTRACT.replace('委托代理合同', '补充协议'),
])
def test_unknown_new_contract_or_date_statement_requires_review(tmp_path, monkeypatch, text):
    out, _ = run(arrange(tmp_path, text), monkeypatch)
    assert out.fields[FIELD] == ''


@pytest.mark.parametrize('option', ['skip_page', 'ocr', 'low_confidence'])
def test_incomplete_or_poor_reading_does_not_extend_default_scope(tmp_path, monkeypatch, option):
    out, _ = run(arrange(tmp_path), monkeypatch, **{option: True})
    assert out.fields[FIELD] == ''


@pytest.mark.parametrize('date', ['2026年1月5日', '2026年2月1日'])
def test_new_contract_same_date_revalidates_different_date_conflicts(tmp_path, monkeypatch, date):
    parts = arrange(tmp_path, CONTRACT.replace('2026年1月5日', date))
    out, _ = run(parts, monkeypatch)
    if date == '2026年1月5日':
        assert out.fields[FIELD] == date and len(out.fields[KEY]['documents']) == 2
    else:
        assert out.fields[FIELD] == ''
        rows = [r for r in out.fields['_field_conflicts'] if r['field'] == FIELD]
        assert len(rows) == 1 and set(rows[0]['values']) == {'2026年1月5日', date}
        assert len(rows[0]['sources']) == 2


@pytest.mark.parametrize('manual', ['', '2025年12月1日'])
def test_manual_date_and_blank_survive_new_materials(tmp_path, monkeypatch, manual):
    out, _ = run(arrange(tmp_path, manual=manual), monkeypatch)
    assert out.fields[FIELD] == manual


@pytest.mark.parametrize('mutation', ['binding', 'scope', 'duplicate', 'omitted', 'old_source', 'identity'])
def test_recheck_receipt_cannot_expand_an_unrelated_or_incomplete_scope(tmp_path, monkeypatch, mutation):
    from intake_date_supplement import refresh, RECEIPT
    parts = arrange(tmp_path)
    out, _ = run(parts, monkeypatch)
    supplied = context(parts)
    delta = {RECEIPT: deepcopy(out.fields[KEY]['supplement_checks'][0])}
    if mutation == 'binding': delta[RECEIPT]['binding']['case_id'] = 'another-case'
    if mutation == 'scope': delta[RECEIPT]['sources'][0]['sha256'] = 'f'*64
    if mutation == 'duplicate': delta[RECEIPT]['documents'] *= 2
    if mutation == 'omitted': delta[RECEIPT]['documents'] = []
    candidate = deepcopy(parts[2].fields)
    if mutation == 'old_source': supplied['date_previous_scope'][0]['sha256'] = 'f'*64
    if mutation == 'identity': candidate['委托人'] = '虚构另一银行'
    before = deepcopy(candidate)
    assert not refresh(candidate, parts[2].fields, delta, supplied, {}, parts[1].source_manifest)
    assert candidate == before
