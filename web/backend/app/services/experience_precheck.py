"""Human-labelled source-bound routing precheck, NOT a release/accuracy receipt.

No model, OCR, material text or client fact is read. File bytes are hashed to
prevent stale or renamed copies from masquerading as independent holdouts.
The full real-case evaluator must still test recognition and output behaviour.
"""
from pathlib import Path
import hashlib

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from ..models import ArchiveTask, Case, CaseFile, ExperienceEvaluation, ExperienceEvent, TaskStatus
from ..case_access import can_access_case
from .experience_rules import ExperienceError, digest, match, normalize
from .experience_store import actor, visible, require_origin
from .experience_sources import _current_manifest
from ..core.v4_bridge import load

VERSION = 'experience-routing-precheck-v1'


def annotation(raw):
    contract = load('agent_experience')
    keys = {'task_id','task_revision','file_id','start_page','end_page','document_kind',
            'signals','expected_applicable','expected_action','expected_target_fields','reference_reviewed'}
    if (not isinstance(raw,dict) or set(raw)!=keys
            or type(raw['task_id']) is not int or raw['task_id']<1
            or type(raw['task_revision']) is not int or raw['task_revision']<1
            or type(raw['file_id']) is not str or not 1<=len(raw['file_id'])<=128
            or type(raw['start_page']) is not int or type(raw['end_page']) is not int
            or not 1<=raw['start_page']<=raw['end_page']
            or type(raw['document_kind']) is not str or raw['document_kind'] not in contract.KINDS
            or type(raw['expected_applicable']) is not bool or raw['reference_reviewed'] is not True
            or type(raw['expected_action']) is not str
            or raw['expected_action'] not in contract.ACTIONS|{'none'}):
        raise ExperienceError('EXPERIENCE_REFERENCE_INVALID')
    signals=raw['signals']; fields=raw['expected_target_fields']
    if (not isinstance(signals,dict) or set(signals)-contract.SIGNALS
            or any(type(value) is not bool for value in signals.values())
            or not isinstance(fields,list) or any(type(f) is not str or f not in contract.FIELDS for f in fields)
            or len(fields)!=len(set(fields))
            or (raw['expected_action']=='read_for_field')!=bool(fields)
            or raw['expected_applicable']!=(raw['expected_action']!='none')):
        raise ExperienceError('EXPERIENCE_REFERENCE_INVALID')
    return {**raw,'signals':dict(sorted(signals.items())), 'expected_target_fields':sorted(fields)}


def _hash_source(path):
    """Fresh bounded-memory hash, no metadata-only cache or OCR/parse step."""
    try:
        before=path.stat()
        if not path.is_file():raise OSError('not a file')
        hashed=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):hashed.update(block)
        after=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
            raise OSError('changed during read')
        return hashed.hexdigest()
    except OSError:
        raise ExperienceError('EXPERIENCE_MATERIAL_UNAVAILABLE') from None


async def _source_set(db, task, case):
    from ..config import ORGS_DIR
    if not _current_manifest(task,case) or len(task.source_manifest)>128:
        raise ExperienceError('EXPERIENCE_STALE_SOURCE')
    root=Path(ORGS_DIR).resolve()
    seen=set(); sources=[]
    for item in task.source_manifest:
        if item['file_id'] in seen:raise ExperienceError('EXPERIENCE_STALE_SOURCE')
        seen.add(item['file_id'])
        file=await db.scalar(select(CaseFile).where(CaseFile.id==item['file_id'],CaseFile.case_id==case.id))
        if not file or type(item.get('path')) is not str:
            raise ExperienceError('EXPERIENCE_MATERIAL_UNAVAILABLE')
        try:
            path=Path(file.abs_path).resolve()
            if not path.is_relative_to(root) or Path(item['path']).resolve()!=path:
                raise ValueError('scope mismatch')
        except (OSError,ValueError,RuntimeError):
            raise ExperienceError('EXPERIENCE_MATERIAL_UNAVAILABLE') from None
        if await run_in_threadpool(_hash_source,path)!=item['sha256']:
            raise ExperienceError('EXPERIENCE_STALE_SOURCE')
        sources.append({key:item[key] for key in ('file_id','sha256','pages')})
    return sources


async def run_precheck(db,user_id,identity,*,revision,references):
    user=await actor(db,user_id,admin=True)
    rule=await visible(db,user,identity)
    if type(revision) is not int or revision!=rule.revision:
        raise ExperienceError('EXPERIENCE_STALE_VERSION')
    if rule.state not in {'draft','validated','approved'}:
        raise ExperienceError('EXPERIENCE_TRANSITION_INVALID')
    if not isinstance(references,list) or not 2<=len(references)<=12:
        raise ExperienceError('EXPERIENCE_REFERENCE_SET_REQUIRED')
    labels=[annotation(raw) for raw in references]
    payload=normalize(rule.payload)
    needed=set(payload['required_signals'])|set(payload['excluded_signals'])
    if any(not needed<=set(label['signals']) for label in labels):
        raise ExperienceError('EXPERIENCE_REFERENCE_OBSERVATIONS_REQUIRED')
    if {label['expected_applicable'] for label in labels}!={True,False}:
        raise ExperienceError('EXPERIENCE_POSITIVE_AND_NEGATIVE_REQUIRED')
    # Validate all IDs and labels before reading any private source file.
    await require_origin(db,rule)
    origin_task=await db.get(ArchiveTask,rule.source_task_id)
    origin_case=await db.get(Case,rule.case_id)
    if origin_task.status not in {TaskStatus.awaiting_review,TaskStatus.done}:
        raise ExperienceError('EXPERIENCE_REFERENCE_TASK_NOT_READY')
    cases={rule.case_id}; bound=[]
    for label in labels:
        task=await db.get(ArchiveTask,label['task_id'])
        case=await db.get(Case,task.case_id) if task else None
        if not can_access_case(user,case):raise ExperienceError('EXPERIENCE_NOT_FOUND')
        if task.status not in {TaskStatus.awaiting_review,TaskStatus.done}:
            raise ExperienceError('EXPERIENCE_REFERENCE_TASK_NOT_READY')
        if case.id in cases:raise ExperienceError('EXPERIENCE_INDEPENDENT_CASES_REQUIRED')
        if task.revision!=label['task_revision'] or not _current_manifest(task,case):
            raise ExperienceError('EXPERIENCE_STALE_SOURCE')
        source=next((r for r in task.source_manifest if r['file_id']==label['file_id']),None)
        if not source or label['end_page']>source['pages']:
            raise ExperienceError('EXPERIENCE_REFERENCE_INVALID')
        cases.add(case.id);bound.append((label,task,case))
    origin_sources=await _source_set(db,origin_task,origin_case)
    known_hashes={s['sha256'] for s in origin_sources}
    samples=[]
    for label,task,case in bound:
        sources=await _source_set(db,task,case)
        hashes={s['sha256'] for s in sources}
        # Case identifiers/file names can change on re-import. Identical source
        # bytes still cannot be both training and held-out evaluation evidence.
        if known_hashes & hashes:raise ExperienceError('EXPERIENCE_OVERLAPPING_MATERIALS')
        known_hashes.update(hashes)
        applicable=match(payload,{'case_type':case.case_type,'document_kind':label['document_kind'],'signals':label['signals']})
        observed_action=payload['action'] if applicable else 'none'
        observed_fields=payload['target_fields'] if applicable else []
        checks={'applicability':applicable==label['expected_applicable'],
                'action':observed_action==label['expected_action'],
                'target_fields':observed_fields==label['expected_target_fields']}
        samples.append({'case_id':case.id,'task_id':task.id,'task_revision':task.revision,
                        'source_version':task.source_version,'source_sha256':digest(sorted(hashes)),
                        'annotation':label,'annotation_sha256':digest(label),
                        'observed_applicable':applicable,'observed_action':observed_action,
                        'observed_target_fields':observed_fields,'checks':checks})
    samples.sort(key=lambda s:s['case_id'])
    report={'kind':'real_case_routing_precheck','annotator_id':user.id,
            'routing_checks_passed':all(all(s['checks'].values()) for s in samples),
            'publish_eligible':False,'recognition_accuracy_verified':False,
            'observation_basis':'human_reviewed_labels_not_model_predictions',
            'source_bytes_checked':True,'cloud_calls':0,'ocr_calls':0,'samples':samples}
    receipt_id=digest([VERSION,rule.id,rule.payload_digest,rule.revision,report])[:32]
    existing=await db.get(ExperienceEvaluation,receipt_id)
    if existing:return existing
    receipt=ExperienceEvaluation(id=receipt_id,org_id=user.org_id,experience_id=rule.id,
        payload_digest=rule.payload_digest,evaluator_version=VERSION,result=report)
    db.add(receipt)
    db.add(ExperienceEvent(org_id=user.org_id,experience_id=rule.id,actor_id=user.id,
                          action='routing_prechecked',revision=rule.revision))
    await db.flush()
    return receipt
