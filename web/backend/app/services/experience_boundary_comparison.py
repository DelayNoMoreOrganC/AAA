"""Read existing model traces for a boundary comparison. Never runs a model.

This reports observed grouping, not a publication receipt or causal benchmark:
native forms, field accuracy and controlled experimental execution are separate.
"""
from sqlalchemy import select

from ..core.v4_bridge import load
from ..models import ArchiveTask, Case, ExperienceEvaluation, ExperienceEvent, TaskStatus
from ..case_access import can_access_case
from .experience_rules import ExperienceError, digest, normalize
from .experience_store import actor, visible, require_origin
from .experience_precheck import _current_manifest, _source_set
from .experience_binding import snapshot_for_task, PROFILE_KEY

VERSION = 'experience-boundary-comparison-v1'


def _stamp(task):
    return digest({'id': task.id, 'case_id': task.case_id, 'revision': task.revision,
        'status': task.status.value, 'created_by': task.created_by,
        'source_version': task.source_version, 'source_manifest': task.source_manifest,
        'execution_profile': task.execution_profile, 'fields': task.fields})


def _profile(task):
    profile = task.execution_profile or {}
    if (type(profile) is not dict or profile.get('processing_mode') not in {'deepseek_cloud', 'ollama_local'}
            or profile.get('workflow') != 'document_two_stage'):
        raise ExperienceError('EXPERIENCE_MODEL_RESULT_REQUIRED')
    expected_provider = 'deepseek' if profile['processing_mode'] == 'deepseek_cloud' else 'ollama'
    if profile.get('provider') != expected_provider or (expected_provider == 'ollama' and profile.get('cloud_consent') is not False):
        raise ExperienceError('EXPERIENCE_MODEL_RESULT_REQUIRED')
    if profile['processing_mode'] == 'deepseek_cloud' and (
            profile.get('cloud_consent') is not True
            or profile.get('authorized_source_version') != task.source_version
            or profile.get('authorized_by') != task.created_by):
        raise ExperienceError('EXPERIENCE_MODEL_AUTHORIZATION_REQUIRED')
    summary = (task.fields or {}).get('_agent_summary') or {}
    if (type(summary) is not dict or summary.get('provider') != profile.get('provider') or summary.get('model') != profile.get('model')
            or summary.get('workflow') != 'document_two_stage' or not summary.get('analysis_version')):
        raise ExperienceError('EXPERIENCE_MODEL_RESULT_REQUIRED')
    return {key: value for key, value in profile.items()
            if key not in {PROFILE_KEY, 'authorized_by'}}, summary['analysis_version']


async def run_comparison(db, user_id, identity, *, revision, references, comparison='boundary'):
    # Server-selected evaluator, never a caller-supplied module or pass flag.
    if comparison not in {'boundary','fields'}:
        raise ExperienceError('EXPERIENCE_COMPARISON_INVALID')
    evaluator_version = VERSION if comparison == 'boundary' else 'experience-field-comparison-v1'
    user = await actor(db, user_id, admin=True)
    rule = await visible(db, user, identity)
    if type(revision) is not int or revision != rule.revision:
        raise ExperienceError('EXPERIENCE_STALE_VERSION')
    payload = normalize(rule.payload)
    allowed_actions = {'keep_component', 'separate_document'} if comparison == 'boundary' else {'read_for_field','retain_only'}
    if payload['action'] not in allowed_actions:
        raise ExperienceError('EXPERIENCE_COMPARISON_RULE_REQUIRED')
    if type(references) is not list or not 2 <= len(references) <= 12:
        raise ExperienceError('EXPERIENCE_REFERENCE_SET_REQUIRED')
    evaluator = load('experience_boundary_comparison' if comparison == 'boundary' else 'experience_field_comparison')
    labels = [evaluator.references(item) for item in references]
    if {item['expected_applicable'] for item in labels} != {True, False}:
        raise ExperienceError('EXPERIENCE_POSITIVE_AND_NEGATIVE_REQUIRED')
    await require_origin(db, rule)
    origin_task = await db.get(ArchiveTask, rule.source_task_id)
    origin_case = await db.get(Case, rule.case_id)
    if origin_task.status not in {TaskStatus.done, TaskStatus.awaiting_review}:
        raise ExperienceError('EXPERIENCE_REFERENCE_TASK_NOT_READY')
    # Validate every task, organization, frozen policy and reference before I/O.
    cases, bound, stamps = {rule.case_id}, [], {origin_task.id: _stamp(origin_task)}
    for label in labels:
        tasks = []
        for name in ('baseline', 'candidate'):
            task = await db.scalar(select(ArchiveTask).where(
                ArchiveTask.id == label[f'{name}_task_id']).execution_options(populate_existing=True))
            case = await db.get(Case, task.case_id) if task else None
            if not can_access_case(user, case):
                raise ExperienceError('EXPERIENCE_NOT_FOUND')
            if task.status not in {TaskStatus.done, TaskStatus.awaiting_review}:
                raise ExperienceError('EXPERIENCE_REFERENCE_TASK_NOT_READY')
            if task.revision != label[f'{name}_revision'] or not _current_manifest(task, case):
                raise ExperienceError('EXPERIENCE_STALE_SOURCE')
            tasks.append(task)
        baseline, candidate = tasks
        if (baseline.case_id != candidate.case_id or candidate.case_id in cases
                or baseline.source_manifest != candidate.source_manifest):
            raise ExperienceError('EXPERIENCE_INDEPENDENT_CASES_REQUIRED')
        cases.add(candidate.case_id)
        if _profile(baseline) != _profile(candidate):
            raise ExperienceError('EXPERIENCE_COMPARISON_PROFILE_MISMATCH')
        snapshots = [snapshot_for_task(task, user.org_id) for task in tasks]
        before, after = snapshots
        matches = [r for r in after['rules'] if r['id'] == rule.id and r['payload_digest'] == rule.payload_digest]
        if (len(matches) != 1 or matches[0]['payload'] != payload or before['conflicts'] or after['conflicts']
                or before['rules'] != [r for r in after['rules'] if r['id'] != rule.id]
                or any(r['id'] == rule.id for r in before['rules'])):
            raise ExperienceError('EXPERIENCE_COMPARISON_POLICY_MISMATCH')
        projections = [evaluator.project(task.fields or {}, task.source_manifest, snapshot['sha256'])
                       for task, snapshot in zip(tasks, snapshots)]
        outcome = evaluator.compare(label, *projections, candidate.source_manifest)
        bound.append((label, tasks, case, projections, outcome))
        stamps.update((task.id, _stamp(task)) for task in tasks)
    known = {item['sha256'] for item in await _source_set(db, origin_task, origin_case)}
    samples = []
    for label, tasks, case, projections, outcome in bound:
        sources = await _source_set(db, tasks[1], case)
        hashes = {item['sha256'] for item in sources}
        if hashes & known:
            raise ExperienceError('EXPERIENCE_OVERLAPPING_MATERIALS')
        known.update(hashes)
        samples.append({'case_id': case.id, 'expected_applicable': label['expected_applicable'],
            'baseline_task_id': tasks[0].id, 'candidate_task_id': tasks[1].id,
            'task_revisions': [task.revision for task in tasks],
            'source_sha256': digest(sources), 'annotation_sha256': digest(label),
            'trace_sha256': [p['trace_sha256'] for p in projections], 'comparison': outcome})
    # Source hashing yields to the event loop. Reject concurrent edits rather
    # than installing a receipt against revisions that are no longer current.
    for task_id, expected in stamps.items():
        task = await db.scalar(select(ArchiveTask).where(ArchiveTask.id == task_id)
                               .execution_options(populate_existing=True))
        case = await db.scalar(select(Case).where(Case.id == task.case_id)
                               .execution_options(populate_existing=True)) if task else None
        if not task or not can_access_case(user, case) or _stamp(task) != expected or not _current_manifest(task, case):
            raise ExperienceError('EXPERIENCE_STALE_SOURCE')
    user = await actor(db, user_id, admin=True)
    fresh_rule = await visible(db, user, identity)
    if fresh_rule.revision != revision:
        raise ExperienceError('EXPERIENCE_STALE_VERSION')
    await require_origin(db, fresh_rule)
    report = {'kind': 'real_case_boundary_comparison' if comparison == 'boundary' else 'real_case_field_comparison', 'annotator_id': user.id,
        'publish_eligible': False, 'causal_effect_verified': False, 'field_accuracy_verified': False,
        'controlled_experiment_verified': False,
        'observation_basis': 'source_bound_original_model_trace_not_manual_projection',
        'source_bytes_checked': True, 'cloud_calls': 0, 'ocr_calls': 0,
        'samples': sorted(samples, key=lambda s: s['case_id'])}
    if comparison == 'boundary':
        report.update(all_candidate_boundaries_match=all(s['comparison']['candidate_matches_reference'] for s in samples),
            all_candidate_boundaries_resolved=all(s['comparison']['candidate_matches_reference']
                and s['comparison']['candidate_unresolved_reviews']==0 for s in samples),
            any_new_boundary_errors=any(s['comparison']['new_errors'] for s in samples))
    else:
        report.update(all_selected_field_checks_match=all(s['comparison']['candidate_checks_match'] for s in samples),
            any_new_field_check_failures=any(s['comparison']['new_errors'] for s in samples),
            native_output_verified=False,semantic_completeness_verified=False)
    receipt_id = digest([evaluator_version, rule.id, rule.revision, rule.payload_digest, report])[:32]
    existing = await db.get(ExperienceEvaluation, receipt_id)
    if existing:
        return existing
    receipt = ExperienceEvaluation(id=receipt_id, org_id=user.org_id, experience_id=rule.id,
        payload_digest=rule.payload_digest, evaluator_version=evaluator_version, result=report)
    db.add(receipt)
    db.add(ExperienceEvent(org_id=user.org_id, experience_id=rule.id, actor_id=user.id,
                          action='boundaries_compared' if comparison=='boundary' else 'fields_compared', revision=rule.revision))
    await db.flush()
    return receipt
