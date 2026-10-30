"""Bounded policy-only repair during an explicitly requested analysis job.

Never invoked by field saves, preview, download, assembly or GET. Reuse source
excerpts and classification; no OCR, page inspection or provider fallback.
"""
from copy import deepcopy


OPERATION = 'repair_forms_and_draft'


def public_repair_plan(parent, saved):
    """Bind the user's next explicit action to these exact fields and rules."""
    import form_synthesis as synthesis
    from .task_sources import fields_digest
    analysis, manual, _ = saved
    targets = synthesis.policy_repair_targets(analysis.fields, manual, parent.source_manifest, analysis.doc_spans)
    token = synthesis.digest({'task':parent.id,'revision':parent.revision,'source':parent.source_version,
        'fields':fields_digest(parent.fields,parent.order_mode),
        'rules':{key:synthesis._cell_contract(key,analysis.case_type) for key in targets}})
    return {'available':True,'token':token,'fields':targets}


def load_repair_parent(parent, org_id, *, case_type, stage='', config=None):
    """Read-only eligibility check. Never widen a form repair into recognition.

    The caller has reconciled the committed field snapshot under the case lock.
    Per-cell attempt receipts prevent an unchanged failed/partial repair from
    receiving a new budget. A changed rule still needs an explicit new action.
    """
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    import form_synthesis as synthesis
    from .analysis_snapshot import load_analysis, task_work_dir
    from .task_sources import snapshot_exists, source_version, fields_digest
    from .task_workflow import analysis_reuse_compatible, unresolved_issues
    from .document_classification import verify_classification
    from .execution_profile import frozen_mode
    from .experience_binding import bind_config
    if (parent is None or not parent.source_manifest or
            ((parent.fields or {}).get('_request_budget_stop') or {}).get('status') == 'incomplete' or
            frozen_mode(parent) not in ('deepseek_cloud', 'ollama_local') or
            not snapshot_exists(parent, org_id)):
        return None
    if source_version(parent.source_manifest, case_type, stage) != parent.source_version:
        return None
    analysis, snapshot = load_analysis(task_work_dir(org_id, parent.case_id, parent.id))
    if (analysis.case_type != case_type or
            (snapshot.get('workflow') or {}).get('source_version') != parent.source_version or
            fields_digest(analysis.fields, parent.order_mode) != fields_digest(parent.fields, parent.order_mode)):
        return None
    verify_classification(parent, analysis)
    if config is None:
        profile = parent.execution_profile or {}
        config = bind_config(parent, org_id, {'extraction': {'mode':'visual_agent'},
            'vision': {key:profile.get(key) for key in ('provider','model','workflow')}})
    if not analysis_reuse_compatible(analysis, config):
        return None
    manual = deepcopy(parent.manual_fields or {})
    targets = synthesis.policy_repair_targets(analysis.fields, manual, parent.source_manifest, analysis.doc_spans)
    conflicts = list(analysis.fields.get('_field_conflicts') or [])
    issues = deepcopy(parent.issues or [])
    conflicts += [{**row['detail'], 'resolved':False} for row in unresolved_issues(issues,analysis.fields,task=parent)
                  if row.get('kind') == 'field_conflict' and isinstance(row.get('detail'),dict)]
    if not targets or any(row.get('field') in synthesis.INPUTS and not row.get('resolved') for row in conflicts):
        return None
    return analysis, manual, issues


def _client(config):
    vision, privacy = config.get('vision') or {}, config.get('privacy') or {}
    if vision.get('provider') == 'deepseek':
        from deepseek_vision_client import DeepSeekVisionClient
        return DeepSeekVisionClient(vision.get('api_key'))
    if vision.get('provider') == 'ollama':
        from ollama_vision_client import OllamaVisionClient
        return OllamaVisionClient(privacy.get('request_guard'), model=vision.get('model'))
    raise ValueError('FORM_REPAIR_PROVIDER_INVALID')


def repair_policy_cells(analysis, task, config, org_id, manual, issues, *, stage='', log=lambda _:None):
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    import form_synthesis as synthesis
    from form_cell_contracts import CASE_ALIASES
    from .task_workflow import unresolved_issues
    from .recognition_checkpoint import build_checkpoint
    from document_segmenter import DocumentSource
    from deepseek_vision_client import DeepSeekVisionError
    from ollama_vision_client import OllamaVisionError
    from recognition_journal import RecognitionJournalError
    fields = analysis.fields
    if (fields.get('_request_budget_stop') or {}).get('status') == 'incomplete':
        # A rule change must not turn an exhausted analysis into a fresh child
        # budget. Preserve the partial result until the remaining processing
        # is explicitly resolved; ordinary form repair is not that operation.
        return None
    if (fields.get('_analysis_metrics') or {}).get('analysis_status') != 'snapshot_reused':
        return None  # A fresh or failed writer must not get a second budget.
    vision = config.get('vision') or {}
    if (config.get('extraction', {}).get('mode') != 'visual_agent'
            or vision.get('workflow') != 'document_two_stage'
            or vision.get('provider') not in ('deepseek', 'ollama')):
        return None
    bundle = fields.get(synthesis.KEY) or {}
    canonical = lambda value: CASE_ALIASES.get(value, value)
    if canonical(bundle.get('case_type')) != canonical(analysis.case_type): return None
    configured = fields.get('案件类别')
    if configured and canonical(configured) != canonical(analysis.case_type): return None
    targets = synthesis.policy_repair_targets(fields, manual, task.source_manifest, analysis.doc_spans)
    if not targets: return None
    attempted_scope = synthesis.policy_repair_scope(bundle)
    attempted_rules = {key:synthesis._cell_contract(key,analysis.case_type) for key in targets}
    conflicts = deepcopy(fields.get('_field_conflicts') or [])
    conflicts += [{**row['detail'], 'resolved':False} for row in unresolved_issues(issues,fields,task=task)
                  if row.get('kind') == 'field_conflict' and isinstance(row.get('detail'),dict)]
    blocked = {row.get('field') for row in conflicts if not row.get('resolved')}
    if blocked.intersection(synthesis.INPUTS):
        return {'status':'source_conflict', 'targets':targets, 'requests':0}
    expected = {synthesis._path(row['path']):row['sha256'] for row in task.source_manifest}
    if synthesis._source_hashes(analysis.doc_spans) != expected:
        raise ValueError('FORM_REPAIR_SOURCE_CHANGED')
    checkpoint = build_checkpoint(task, None, org_id, config, case_type=analysis.case_type,
        stage=stage, sources=[DocumentSource(path=row['path'],doc_type=row['doc_type']) for row in task.source_manifest],
        manual_fields=manual, parent_snapshot=None, analysis_kind='form_repair')
    if checkpoint is None: raise ValueError('FORM_REPAIR_CHECKPOINT_REQUIRED')
    guard = (config.get('privacy') or {}).get('request_guard')
    if guard is not None and not callable(guard): raise ValueError('FORM_REPAIR_GUARD_INVALID')
    if guard: guard()
    client = checkpoint.bind(_client(config))
    candidate = deepcopy(fields)
    provenance = candidate.setdefault('_provenance', {})
    log('填写规则已更新，正在复核受影响栏目')
    try:
        status = synthesis.generate(client,candidate,provenance,conflicts,analysis.doc_spans,{},set(),
            case_type=analysis.case_type,guard=guard,manual_fields=manual,source_manifest=task.source_manifest,
            target_fields=targets,use_saved_sources=True)
    except RecognitionJournalError as error:
        if error.code != 'REQUEST_BUDGET_EXHAUSTED': raise
        status={'status':'task_budget_exhausted','requests':client.metrics.get('model_requests',0),
                'fields':{key:'task_budget_exhausted' for key in targets}}
        candidate['_request_budget_stop']={'status':'incomplete','phase':'form_policy_repair',
            'fields':targets,'material_absence_proven':False,'budget':client.metrics.get('task_request_budget')}
        client.finish_segment('operation_limit')
    except (DeepSeekVisionError,OllamaVisionError):
        status = {'status':'provider_failed','requests':client.metrics.get('model_requests',0),
                  'fields':{key:'provider_failed' for key in targets}}
        client.finish_segment('operation_limit')
    else:
        if status['requests']: client.finish_segment('completed')
    rejected = [key for key in targets if status.get('fields',{}).get(key) not in ('generated','reused')]
    if status['requests']:
        attempts = deepcopy(fields.get('_form_policy_attempts') or [])
        receipt = {'scope':attempted_scope,'rules':attempted_rules,
                   'status':status['status'],'unaccepted_targets':rejected}
        if receipt not in attempts: attempts.append(receipt)
        candidate['_form_policy_attempts'] = attempts
    if synthesis.digest(candidate.get(synthesis.KEY)) != synthesis.digest(bundle):
        history = deepcopy(fields.get('_form_policy_history') or [])
        if not any(row.get('bundle_digest') == synthesis.digest(bundle) for row in history):
            history.append({'bundle_digest':synthesis.digest(bundle),'bundle':deepcopy(bundle),
                            'repair_targets':targets,'unaccepted_targets':rejected})
        candidate['_form_policy_history'] = history
    for key in rejected:
        # A rejected old automatic value remains in its prior bundle/history,
        # never in a cell pretending to have passed the updated rule.
        candidate[key] = ''
    candidate['_form_synthesis_status'] = {**status,
        'fields':{**(fields.get('_form_synthesis_status') or {}).get('fields',{}),**status.get('fields',{})}}
    repair_status = 'partially_repaired' if status['status']=='generated' and rejected else status['status']
    candidate['_form_policy_repair'] = {'scope':'this_analysis_call','status':repair_status,'targets':targets,
        'unaccepted_targets':rejected,
        'writer_steps':status['requests'],'new_page_reads':0,'new_ocr_calls':0,
        'metrics':deepcopy(client.metrics)}
    candidate['_analysis_metrics'] = {**candidate.get('_analysis_metrics',{}),
        'analysis_status':'snapshot_reused_policy_review', 'form_policy_repair':candidate['_form_policy_repair']}
    # The frozen analysis job owns this version. The usual save/snapshot path
    # commits it and invalidates final confirmation; historical tasks stay intact.
    analysis.fields = candidate
    return candidate['_form_policy_repair']
