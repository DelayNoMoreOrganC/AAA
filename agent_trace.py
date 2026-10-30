"""Task-private, source-scoped agent traces; never a shared experience store.

Local f1p1/d1 identifiers have meaning only inside one run. Preserve that scope
across supplements and keep archive document-ID remapping separate from the
immutable trace. Legacy unscoped records remain historical, not invented facts.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

TRACE_RUNS = '_agent_trace_runs'
TRACE_CURRENT = '_agent_trace_current'
TRACE_KEYS = ('_visual_boundary_review','_document_reading_plan','_document_field_batches','_case_evidence_search','_page_observations','_experience_policy','_page_text_views','_request_budget_stop','_machine_field_candidates')
SCHEMA = 'agent-source-trace-v1'
RESERVED_KEYS = frozenset((*TRACE_KEYS,TRACE_RUNS,TRACE_CURRENT,'_agent_events','_evidence_bundles','_page_reading_cache','_form_policy_repair','_form_policy_history','_form_policy_attempts'))


class AgentTraceError(ValueError):
    pass


def digest(value):
    try:
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    except (ValueError,TypeError):
        raise AgentTraceError('AGENT_TRACE_INVALID') from None
    return hashlib.sha256(raw).hexdigest()


def source_identity(path, page_count):
    source=Path(path).absolute()
    before=source.stat()
    h=hashlib.sha256()
    with source.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise AgentTraceError('SOURCE_CHANGED_DURING_IDENTITY')
    return {'source_path':str(source),'sha256':h.hexdigest(),'size':after.st_size,
            'page_count':page_count,'mtime_ns':after.st_mtime_ns}


def build_trace(pages, documents, units, metadata):
    page_map={key:{'source_path':str(Path(path).absolute()),'page':number+1} for key,(path,number) in pages.pages.items()}
    identities=copy.deepcopy(getattr(pages,'source_identities',{}))
    if set(identities)!={item['source_path'] for item in page_map.values()}:
        raise AgentTraceError('AGENT_TRACE_SOURCE_IDENTITY_MISSING')
    for path,identity in identities.items():
        current=Path(path).stat()
        if (current.st_size,current.st_mtime_ns)!=(identity['size'],identity['mtime_ns']):
            raise AgentTraceError('SOURCE_CHANGED_DURING_ANALYSIS')
    if len(documents)!=len(units):raise AgentTraceError('AGENT_TRACE_DOCUMENT_SCOPE')
    doc_map={};global_ids={};covered=[]
    for document,unit in zip(documents,units):
        key=document['id'];keys=document['keys']
        expected=[{'source_path':str(Path(unit.source_path).absolute()),'page':n+1} for n in range(unit.start_page,unit.end_page+1)]
        if key in doc_map or not keys or any(k not in page_map for k in keys) or [page_map[k] for k in keys]!=expected:
            raise AgentTraceError('AGENT_TRACE_DOCUMENT_SCOPE')
        doc_map[key]={'page_ids':list(keys),'local_doc_id':unit.doc_id}
        global_ids[key]=unit.doc_id;covered.extend(keys)
    if len(covered)!=len(page_map) or set(covered)!=set(page_map):
        raise AgentTraceError('AGENT_TRACE_PAGE_COVERAGE')
    body={'schema':SCHEMA,'scope':{'sources':identities,'pages':page_map,'documents':doc_map},
          'payload':{key:copy.deepcopy(metadata[key]) for key in (*TRACE_KEYS,'_agent_events') if key in metadata}}
    return {'run_id':digest(body),'body':body,'archive_document_ids_at_merge':global_ids,
            'mapping_sha256':digest(global_ids)}


def _checked_runs(value):
    if value is None:return []
    if not isinstance(value,list):raise AgentTraceError('AGENT_TRACE_INVALID')
    runs=[];ids=set()
    for item in value:
        if (not isinstance(item,dict) or not isinstance(item.get('body'),dict)
                or item['body'].get('schema') not in (SCHEMA,'legacy-unscoped')
                or item.get('run_id')!=digest(item['body']) or item['run_id'] in ids
                or not isinstance(item.get('archive_document_ids_at_merge'),dict)
                or item.get('mapping_sha256')!=digest(item['archive_document_ids_at_merge'])):
            raise AgentTraceError('AGENT_TRACE_HASH_OR_DUPLICATE')
        mapping=item['archive_document_ids_at_merge']
        expected=set(((item['body'].get('scope') or {}).get('documents') or {}).keys())
        if set(mapping)!=expected or any(type(v) is not int or v<0 for v in mapping.values()) or len(set(mapping.values()))!=len(mapping):
            raise AgentTraceError('AGENT_TRACE_DOCUMENT_REMAP')
        ids.add(item['run_id']);runs.append(copy.deepcopy(item))
    return runs


def validate_trace_fields(fields):
    """Old snapshots remain readable; scoped records must retain valid binding."""
    runs=_checked_runs(fields.get(TRACE_RUNS))
    current=fields.get(TRACE_CURRENT)
    if current is None:
        if runs:raise AgentTraceError('AGENT_TRACE_CURRENT_SCOPE_MISSING')
        return
    run=next((r for r in runs if r['run_id']==current),None)
    if run is None:raise AgentTraceError('AGENT_TRACE_CURRENT_SCOPE_MISSING')
    payload=run['body'].get('payload') or {}
    for key in TRACE_KEYS:
        if (key in fields)!=(key in payload) or key in payload and fields[key]!=payload[key]:
            raise AgentTraceError('AGENT_TRACE_CURRENT_VIEW_MISMATCH')


def merge_diagnostics(target_fields, incoming_fields, unit_ids):
    """Preserve historical scopes and expose this run's flat compatibility view.

    Compute and validate first, then mutate only diagnostic keys. Facts, manual
    edits, original document spans and prior snapshot files are never changed.
    """
    runs=_checked_runs(target_fields.get(TRACE_RUNS))
    incoming=_checked_runs(incoming_fields.get(TRACE_RUNS))
    legacy={key:copy.deepcopy(target_fields[key]) for key in TRACE_KEYS if key in target_fields}
    if not runs and legacy:
        body={'schema':'legacy-unscoped','payload':legacy,'source_binding_verified':False}
        runs.append({'run_id':digest(body),'body':body,'archive_document_ids_at_merge':{},'mapping_sha256':digest({})})
    by_id={run['run_id']:run for run in runs}
    current_id=target_fields.get(TRACE_CURRENT)
    if current_id is not None and current_id not in by_id:
        raise AgentTraceError('AGENT_TRACE_CURRENT_SCOPE_MISSING')
    if current_id is None and runs:current_id=runs[-1]['run_id']
    for run in incoming:
        local_map=(run['body'].get('scope') or {}).get('documents') or {}
        if run['body'].get('schema')!=SCHEMA:
            raise AgentTraceError('AGENT_TRACE_INCOMING_SCHEMA')
        mapping={}
        for key,doc in local_map.items():
            local=doc.get('local_doc_id')
            mapped=unit_ids.get(local)
            if type(local) is not int or type(mapped) is not int or mapped<0:
                raise AgentTraceError('AGENT_TRACE_DOCUMENT_REMAP')
            mapping[key]=mapped
        run['archive_document_ids_at_merge']=mapping
        run['mapping_sha256']=digest(mapping)
        if run['run_id'] in by_id:
            if by_id[run['run_id']]!=run:
                raise AgentTraceError('AGENT_TRACE_MAPPING_CONFLICT')
        else:
            runs.append(run);by_id[run['run_id']]=run
        current_id=run['run_id']
    # Existing versions before source-scoped traces may supply flat diagnostics.
    # Keep these explicitly unscoped; never reinterpret their f1p1 as an old page.
    if not incoming:
        payload={key:copy.deepcopy(incoming_fields[key]) for key in TRACE_KEYS if key in incoming_fields}
        if payload:
            body={'schema':'legacy-unscoped','payload':payload,'source_binding_verified':False}
            run={'run_id':digest(body),'body':body,'archive_document_ids_at_merge':{},'mapping_sha256':digest({})}
            if run['run_id'] not in by_id:runs.append(run)
            current_id=run['run_id']
    updates={key:copy.deepcopy(incoming_fields[key]) for key in TRACE_KEYS if key in incoming_fields}
    if runs:updates[TRACE_RUNS]=runs
    if current_id is not None:updates[TRACE_CURRENT]=current_id
    if incoming or any(key in incoming_fields for key in TRACE_KEYS):
        for key in TRACE_KEYS:target_fields.pop(key,None)
    target_fields.update(updates)
