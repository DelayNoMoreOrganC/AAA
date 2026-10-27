"""A healthy server or empty evidence must never become an acceptance pass."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('hourly_check', Path(__file__).resolve().parents[1] / 'scripts/hourly_workstation_check.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(checker, 'ROOT', tmp_path)
    monkeypatch.setattr(checker, 'OUT', tmp_path / 'evidence')
    checker.OUT.mkdir()
    (tmp_path / 'example.py').write_bytes(b'synthetic source')
    patch = {'sha256': {'example.py': sha(b'synthetic source')},
             'runtime': {'expected_health_policy': 'fixed-errors-v1'}}
    (checker.OUT / 'privacy-hardening.json').write_text(json.dumps(patch), encoding='utf-8')
    delivery = checker.OUT / 'fictional-delivery'
    delivery.mkdir()
    names = ['volume.pdf', *[f'form{n}.docx' for n in range(5)], 'quality.json', 'quality.html', 'package.zip']
    entries = []
    for name in names:
        data = ('synthetic bytes ' + name).encode()
        (delivery / name).write_bytes(data)
        entries.append({'path': str(Path('synthetic') / name), 'sha256': sha(data)})
    record = checker.OUT / 'render-upgrade-12.json'
    record.write_text(json.dumps({'new_artifacts': entries}), encoding='utf-8')
    return tmp_path, delivery, record, entries


def test_healthy_old_services_do_not_prove_patch_activation(evidence):
    checks = {name: {'http_status': 200, 'status': 'ok'} for name in
              ('production', 'synthetic_acceptance', 'https_explicit_local_ca')}
    result = checker.check_privacy_patch(checks)
    assert result['source_fingerprints_match'] is True
    assert result['all_runtime_markers_present'] is False
    assert result['full_flow_reaccepted'] is False
    for check in checks.values():
        check['diagnostic_policy'] = 'fixed-errors-v1'
    result = checker.check_privacy_patch(checks)
    assert result['all_runtime_markers_present'] is True
    assert result['full_flow_reaccepted'] is False


def test_patch_code_changes_invalidate_regression_evidence(evidence):
    root, *_ = evidence
    (root / 'example.py').write_bytes(b'unverified edit')
    result = checker.check_privacy_patch({})
    assert result['source_fingerprints_match'] is False
    assert result['changed_source_files'] == ['example.py']


def test_later_regression_requires_complete_coverage_and_still_cannot_prove_runtime(evidence):
    root, *_ = evidence
    (root / 'example.py').write_bytes(b'new version with another feature')
    successor = {'status':'passed','supersedes_source_evidence':['privacy-hardening.json'], 'sha256':{}}
    path = checker.OUT / 'current-source-regression.json'
    path.write_text(json.dumps(successor), encoding='utf-8')
    with pytest.raises(ValueError):
        checker.check_privacy_patch({})
    successor['sha256']['example.py'] = sha(b'new version with another feature')
    path.write_text(json.dumps(successor), encoding='utf-8')
    result = checker.check_privacy_patch({})
    assert result['source_fingerprints_match'] is True
    assert result['all_runtime_markers_present'] is False
    assert result['full_flow_reaccepted'] is False


@pytest.mark.parametrize('fingerprints', [{}, {'web/backend/app/../../data/private.py': 'a' * 64}, {'workstation-data/private.py': 'a' * 64}])
def test_empty_or_non_code_fingerprints_are_rejected_without_reading(evidence, monkeypatch, fingerprints):
    def forbidden(*args):
        raise AssertionError('must reject before reading bytes')
    monkeypatch.setattr(checker, 'digest', forbidden)
    with pytest.raises(ValueError):
        checker.code_fingerprint_changes(fingerprints)


@pytest.mark.parametrize('invalid', ['empty', 'missing', 'duplicate'])
def test_incomplete_artifact_evidence_cannot_pass(evidence, invalid):
    _, _, record, entries = evidence
    data = [] if invalid == 'empty' else entries[:-1] if invalid == 'missing' else entries[:-1] + [entries[0]]
    record.write_text(json.dumps({'new_artifacts': data}), encoding='utf-8')
    with pytest.raises(ValueError):
        checker.verify_synthetic_delivery(12, 'fictional-delivery')


@pytest.mark.parametrize('mutation', ['changed', 'deleted'])
def test_nine_deliverables_all_have_to_match(evidence, mutation):
    _, delivery, _, _ = evidence
    assert checker.verify_synthetic_delivery(12, 'fictional-delivery') == {'hashes_match': True, 'files': 9}
    if mutation == 'changed':
        (delivery / 'form2.docx').write_bytes(b'changed bytes')
    else:
        (delivery / 'form2.docx').unlink()
    assert checker.verify_synthetic_delivery(12, 'fictional-delivery')['hashes_match'] is False
