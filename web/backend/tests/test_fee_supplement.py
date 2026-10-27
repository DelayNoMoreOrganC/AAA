"""Fictional immutable-parent evidence, without reading old pages or calling AI."""
from copy import deepcopy
from types import SimpleNamespace
import hashlib

import pytest
from app.core.v4_bridge import init_v4_path
init_v4_path()
from app.services.supplement_identity_context import build_supplement_identity_context
from app.services.task_sources import source_version
from app.services.field_assurance import field_assurance
from app.services.party_binding_state import reconcile_party_bindings
from source_fact_recall import recall_cached_source_facts
from fee_settlement_evidence import FIELDS
from tests.test_task_workflow import fixture_analysis


def setup(tmp_path, identity='案号', manual=None):
    value = '（2026）粤0999民初7001号' if identity == '案号' else 'GD-2026-70'
    originals = [('委托人', '虚构银行', '委托人（甲方）：虚构银行。'),
                 (identity, value, ('本案案号：' if identity == '案号' else '委托代理合同编号：') + value + '。')]
    old, refs, fields = [], {}, {}
    for n, (key, val, text) in enumerate(originals):
        row = dict(file_id=str(n), path=str(tmp_path / f'identity-{n}.pdf'), filename=f'identity-{n}.pdf',
                   pages=1, sha256=hashlib.sha256(text.encode()).hexdigest(), doc_type='default')
        old.append(row); fields[key] = val
        refs[key] = [dict(method='local_agent', value=val, quote=text, source_path=row['path'], page=1)]
    fields.update(manual or {})
    fields['_provenance'] = refs
    text = ('律师费结算单\n委托人：虚构银行\n' + ('案号：' if identity == '案号' else '委托合同编号：') + value
            + '\n应收业务费：5000元\n已收业务费：2000元\n尚欠业务费：3000元\n应退业务费：0元')
    new = dict(file_id='new', path=str(tmp_path / 'supplement.pdf'), filename='supplement.pdf', pages=1,
               sha256=hashlib.sha256(text.encode()).hexdigest(), doc_type='invoice')
    previous = fixture_analysis(old[0]['path'], deepcopy(fields))
    from pdf_doc_locator import DocumentUnit
    previous.doc_spans.append(DocumentUnit(1, 'evidence', 0, 0, catalog_seq=7, source_path=old[1]['path']))
    previous.source_paths = [r['path'] for r in old]
    parent = SimpleNamespace(id=1, revision=1, case_id='fictional-fees', source_manifest=old,
        source_version=source_version(old, 'civil', ''), fields=deepcopy(fields), manual_fields=manual or {}, issues=[])
    task = SimpleNamespace(id=2, case_id=parent.case_id, parent_task_id=1, source_manifest=old + [new],
        source_version=source_version(old + [new], 'civil', ''))
    snapshot = dict(case_type='civil', workflow=dict(revision=1, source_version=parent.source_version,
        source_manifest=deepcopy(old), manual_fields=deepcopy(parent.manual_fields)))
    return parent, task, previous, snapshot, text


def context(parts):
    parent, task, previous, snapshot, _ = parts
    return build_supplement_identity_context(task, parent, previous, snapshot,
        org_id='fictional-org', case_type='civil')


def extract(parts, supplied, extra=None):
    _, task, _, _, text = parts
    path = task.source_manifest[-1]['path']
    fields, refs, conflicts, review = deepcopy(extra or {}), {}, [], []
    cache = {(path, 1): text}  # No old-page content is available to the extractor.
    recall_cached_source_facts(fields, refs, conflicts, page_cache=cache, allowed_sources=set(cache),
        fact_review=review, local_recall_context=supplied)
    fields.update(_provenance=refs, _field_conflicts=conflicts)
    return fields, review


@pytest.mark.parametrize('identity', ['案号', '合同号'])
def test_fee_only_supplement_reuses_frozen_identity_without_inventing_new_identity(tmp_path, identity):
    parts = setup(tmp_path, identity)
    supplied = context(parts)
    assert supplied is not None
    before = deepcopy(supplied)
    delta, review = extract(parts, supplied)
    assert delta['已收业务费'] == '2000元' and not review
    assert all(key not in delta and key not in delta['_provenance'] for key in ('委托人', identity))
    assert supplied == before
    parent, task, previous, _, _ = parts
    merged = {**previous.fields, **delta, '_provenance': {**previous.fields['_provenance'], **delta['_provenance']}}
    for field in FIELDS:
        assert field_assurance(field, merged[field], merged, source_manifest=task.source_manifest)['status'] == 'source_supported'
    assert reconcile_party_bindings(merged, {}, task.source_manifest) == merged
    for index in range(3):
        changed = deepcopy(task.source_manifest); changed[index]['sha256'] = 'f' * 64
        assert field_assurance('已收业务费', '2000元', merged, source_manifest=changed)['status'] == 'unverified'
        assert reconcile_party_bindings(merged, {}, changed)['已收业务费'] == ''
        from form_drafts import _accepted, _scope
        assert _accepted(merged, '已收业务费', {}, _scope(changed)) == ('', [])


@pytest.mark.parametrize('mutation', ['revision', 'case', 'old_hash', 'snapshot_fields', 'conflict', 'manual_blank'])
def test_invalid_parent_or_disputed_identity_cannot_supply_amounts(tmp_path, mutation):
    parts = setup(tmp_path)
    parent, task, previous, snapshot, _ = parts
    if mutation == 'revision': snapshot['workflow']['revision'] = 2
    if mutation == 'case': task.case_id = 'other-case'
    if mutation == 'old_hash': task.source_manifest = [dict(row, sha256='f'*64) for row in task.source_manifest]
    if mutation == 'snapshot_fields': parent.fields['委托人'] = '虚构另一银行'
    if mutation == 'conflict':
        previous.fields['_field_conflicts'] = [dict(field='案号', resolved=False)]
        parent.fields = deepcopy(previous.fields)
    if mutation == 'manual_blank':
        parent.manual_fields['案号'] = ''
        parent.fields['案号'] = previous.fields['案号'] = ''
        snapshot['workflow']['manual_fields'] = deepcopy(parent.manual_fields)
    delta, _ = extract(parts, context(parts))
    assert not delta.get('已收业务费')


@pytest.mark.parametrize('mutation', ['missing', 'source_hash', 'page', 'quote', 'primary_hash', 'duplicate_scope', 'delta_identity'])
def test_broken_certificates_or_new_identity_disagreement_require_review(tmp_path, mutation):
    parts = setup(tmp_path); supplied = context(parts)
    extra = None
    if mutation == 'missing': supplied.pop('fee_provenance')
    if mutation == 'source_hash': supplied['fee_provenance']['委托人'][0]['source_sha256'] = 'f'*64
    if mutation == 'page': supplied['fee_provenance']['委托人'][0]['page'] = 2
    if mutation == 'quote': supplied['fee_provenance']['委托人'][0]['quote'] = '没有委托依据'
    if mutation == 'primary_hash': supplied['fee_source_scope'][-1]['sha256'] = 'invalid'
    if mutation == 'duplicate_scope': supplied['fee_source_scope'].append(supplied['fee_source_scope'][0])
    if mutation == 'delta_identity': extra = {'委托人': '虚构另一银行'}
    delta, _ = extract(parts, supplied, extra)
    assert not delta.get('已收业务费')


@pytest.mark.parametrize('saved', [None, '', '人工另填', '9000元'])
def test_real_incremental_merge_preserves_original_pages_manual_and_old_snapshot(tmp_path, monkeypatch, saved):
    from app.services import task_workflow as workflow
    import archive_pipeline as ap
    manual = {'已收业务费': saved} if saved in ('', '人工另填') else None
    parts = setup(tmp_path, manual=manual)
    parent, task, previous, snapshot, text = parts
    if saved == '9000元':
        previous.fields['已收业务费'] = parent.fields['已收业务费'] = saved
    before = deepcopy(previous)
    monkeypatch.setattr(workflow, 'snapshot_exists', lambda *_: True)
    monkeypatch.setattr(workflow, 'load_analysis', lambda *_: (deepcopy(previous), deepcopy(snapshot)))
    calls = []
    def analyze(case_type, *, sources, local_recall_context, **kwargs):
        calls.append([source.path for source in sources])
        fields, review = extract(parts, local_recall_context)
        assert '委托人' not in fields
        fields['_fact_review'] = review
        return fixture_analysis(sources[0].path, fields)
    engine = SimpleNamespace(analyze_archive=analyze, compute_found_seqs=ap.compute_found_seqs,
                             compute_missing_items=ap.compute_missing_items)
    files = [SimpleNamespace(id=row['file_id'], abs_path=row['path'], doc_type=row['doc_type']) for row in task.source_manifest]
    out, human, conflicts = workflow.analyze_with_parent(engine, task, parent, files,
        {'workflow_case_type': 'civil'}, 'fictional-org', lambda _: None)
    assert calls == [[task.source_manifest[-1]['path']]]
    assert previous == before
    assert [(u.source_path, u.start_page, u.end_page) for u in out.doc_spans] == [(r['path'], 0, 0) for r in task.source_manifest]
    assert out.fields['已收业务费'] == ('2000元' if saved is None else saved)
    fee_conflicts = [row for row in conflicts if row['detail'].get('field') == '已收业务费']
    assert bool(fee_conflicts) == (saved == '9000元')
    if saved is None:
        assert field_assurance('已收业务费', out.fields['已收业务费'], out.fields,
            source_manifest=task.source_manifest)['status'] == 'source_supported'
