"""Checkpoint and incremental analysis helpers; no simulated model output."""
from __future__ import annotations

import copy
import hashlib
import json
import os

from .analysis_snapshot import load_analysis, task_work_dir
from .task_sources import changed_file_ids, snapshot_exists, source_version
from .source_recall_metrics import combine_source_recall_metrics


def issue(kind, message, *, detail=None, blocking=True):
    key = hashlib.sha256(json.dumps([kind, message, detail], ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:20]
    return {"id": key, "kind": kind, "message": message, "detail": detail, "blocking": blocking}


def enrich_classification_issues(issues, doc_spans, source_manifest):
    units = {str(unit.doc_id): unit for unit in doc_spans or []}
    sources = {os.path.normcase(os.path.abspath(row["path"])): row for row in source_manifest or [] if row.get("path")}
    result = copy.deepcopy(issues or [])
    for entry in result:
        if entry.get("kind") == "field_extraction_review":
            detail = entry.get("detail") or {}
            pages = {}
            for document in detail.get("documents") or []:
                path = document.get("source_path")
                source = sources.get(os.path.normcase(os.path.abspath(path))) if path else None
                if source:
                    document.update(file_id=source["file_id"], filename=source["filename"])
                    page = document.get("page")
                    if type(page) is int and page > 0:
                        pages[(source["file_id"], page)] = {"file_id":source["file_id"], "filename":source["filename"], "page":page}
            detail["pages"] = list(pages.values())
            continue
        if entry.get("kind") == "fact_review":
            detail = entry.get("detail") or {}
            grouped = {}
            for candidate in detail.get("candidates") or []:
                path = candidate.get("source_path")
                source = sources.get(os.path.normcase(os.path.abspath(path))) if path else None
                if source:
                    candidate.update(file_id=source["file_id"], filename=source["filename"])
                    page = candidate.get("page")
                    if type(page) is int and page > 0:
                        candidate.update(page_start=page, page_end=page)
                        key = (source["file_id"], page)
                        group = grouped.setdefault(key, {"file_id":source["file_id"], "filename":source["filename"],
                                                         "page":page, "fields":[], "candidate_count":0})
                        group["candidate_count"] += 1
                        if candidate.get("field") and candidate["field"] not in group["fields"]:
                            group["fields"].append(candidate["field"])
            detail["pages"] = list(grouped.values())
            continue
        if entry.get("kind") not in ("classification", "ocr"):
            continue
        detail = entry.get("detail")
        if not isinstance(detail, dict):
            continue
        unit = units.get(str(detail.get("doc_id")))
        if unit and entry.get("kind") == "classification":
            detail.update(source_path=unit.source_path, page=unit.start_page + 1,
                          page_start=unit.start_page + 1, page_end=unit.end_page + 1)
        if entry.get("kind") == "ocr" and type(detail.get("page")) is int and detail["page"] > 0:
            detail.setdefault("page_start", detail["page"])
            detail.setdefault("page_end", detail["page"])
        path = detail.get("source_path")
        source = sources.get(os.path.normcase(os.path.abspath(path))) if path else None
        if source:
            detail.update(file_id=source["file_id"], filename=source["filename"])
    return result


def _evidence_ocr_is_advisory(entry, analysis):
    """A minor OCR warning is not a user decision when no field depends on it."""
    fields = analysis.fields or {}
    if (entry.get('reason_codes') != ['low_confidence'] or type(entry.get('mean_confidence')) not in (int,float)
            or entry['mean_confidence'] < .95 or type(entry.get('page')) is not int):
        return False
    path, page = entry.get('source_path'), entry['page']
    unit = next((u for u in analysis.doc_spans or [] if u.source_path == path and u.start_page+1 <= page <= u.end_page+1), None)
    if unit is None or unit.doc_type != 'evidence' or (unit.confidence < .85 and unit.manual_catalog_seq is None):
        return False
    if not any(g.get('source_path') == path and any(e.get('status') == 'matched_range'
        and unit.doc_id in e.get('doc_ids',[]) for e in g.get('entries',[])) for g in fields.get('_evidence_bundles',[])):
        return False
    def uses(value):
        if isinstance(value,dict):
            return (value.get('source_path')==path and (value.get('page')==page or
                type(value.get('start_page')) is int and type(value.get('end_page')) is int
                and value['start_page']<=page<=value['end_page'])) or any(uses(v) for v in value.values())
        return isinstance(value,(list,tuple)) and any(uses(v) for v in value)
    # Any dependent fact, narrative source, conflict or failed extraction keeps
    # the warning actionable. No reliance on the model's confidence alone.
    return not any(uses(fields.get(k)) for k in ('_provenance','_form_draft_sources',
        '_field_conflicts','_fact_review','_case_timeline','_intake_complaint_source'))


def analysis_issues(analysis, source_manifest=None):
    result = []
    for entry in (analysis.fields or {}).get("_field_conflicts", []) or []:
        if isinstance(entry, dict):
            if entry.get('resolution_method') == 'case_timeline_summary':
                from case_timeline import resolved_conflict_supported
                if resolved_conflict_supported(entry, analysis.fields):
                    continue
            result.append(issue("field_conflict", f"材料中的「{entry.get('field', '字段')}」存在冲突，请核对后填写", detail=entry))
    units = {str(unit.doc_id): unit for unit in analysis.doc_spans or []}
    sources = {os.path.normcase(os.path.abspath(row["path"])): row
               for row in source_manifest or [] if row.get("path")}
    mapping_reviews = (analysis.fields or {}).get("_visual_classification_review") or []
    seen_units = set()
    for entry in getattr(analysis, "low_confidence_items", None) or []:
        if not isinstance(entry, dict):
            continue
        unit = units.get(str(entry.get("doc_id")))
        if unit is not None:
            if unit.doc_id in seen_units or getattr(unit, "manual_catalog_seq", None) is not None:
                continue
            seen_units.add(unit.doc_id)
        # Keep the existing decision identity: adding a clearer explanation
        # must not revive an already acknowledged low-confidence issue.
        problem = issue("classification", "部分材料分类把握不足，请核对原件与目录", detail=entry)
        detail = copy.deepcopy(entry)
        problem["detail"] = detail
        if unit is not None:
            path = os.path.normcase(os.path.abspath(unit.source_path)) if unit.source_path else ""
            source = sources.get(path)
            if (source and type(source.get("pages")) is int
                    and 0 <= unit.start_page <= unit.end_page < source["pages"]):
                detail["sources"] = [{"file_id": source["file_id"], "filename": source.get("filename", ""), "page": page}
                                     for page in range(unit.start_page + 1, unit.end_page + 2)]
            fallback = next((row for row in mapping_reviews if isinstance(row, dict)
                and row.get("reason_code") == "catalog_mapping_uncertain" and row.get("mapping_method") == "fallback"
                and str(row.get("doc_id")) == str(unit.doc_id)
                and row.get("doc_type") == unit.doc_type and row.get("catalog_seq") == unit.catalog_seq
                and isinstance(row.get("source_path"), str) and row["source_path"]
                and os.path.normcase(os.path.abspath(row["source_path"])) == path
                and type(row.get("page")) is int and unit.start_page + 1 <= row["page"] <= unit.end_page + 1), None)
            if fallback:
                import archive_catalog
                item = next((item for item in archive_catalog.get_catalog(analysis.case_type) if item.seq == unit.catalog_seq), None)
                destination = f"目录第 {unit.catalog_seq} 项" + (f"「{item.name}」" if item else "")
                problem["message"] = f"该文书在本业务目录无直接对应项，暂放{destination}，请核对归档位置"
                detail.update(reason_code="catalog_mapping_uncertain", mapping_method="fallback",
                              doc_type=unit.doc_type, catalog_seq=unit.catalog_seq)
        result.append(problem)
    for entry in (analysis.fields or {}).get("_classification_review") or []:
        result.append(issue("classification_stale", "原人工分类不再适用于当前材料，请重新核对文书分类", detail=entry))
    for entry in (analysis.fields or {}).get("_ocr_review", []) or []:
        if isinstance(entry, dict):
            problem = issue("ocr", "页面识别质量需要核对，请查看原件并记录处理说明", detail=entry)
            if _evidence_ocr_is_advisory(entry, analysis):
                problem["blocking"] = False
                problem["detail"] = dict(entry, triage="evidence_placement_verified_no_field_use",
                    explanation="证据归组已核实，此页未用于自动填表；保留原页和识别质量记录。")
            result.append(problem)
    for entry in getattr(analysis, "template_issues", None) or []:
        result.append(issue("template", str(entry)))
    for entry in getattr(analysis, "outcome_warnings", None) or []:
        result.append(issue("outcome", str(entry)))
    refused = (analysis.fields or {}).get("_fact_review") or []
    def recalled_now(entry):
        if (isinstance(entry, dict) and entry.get('resolution') == 'field_supported_by_cached_source'
                and entry.get('field') in ('应收业务费', '已收业务费', '尚欠业务费', '应退业务费')):
            from .evidence_links import supporting_refs
            fields = analysis.fields or {}; field = entry['field']
            refs = (fields.get('_provenance') or {}).get(field) or []
            refs = [refs] if isinstance(refs, dict) else refs
            # A prior refusal is obsolete only while its exact page, amount,
            # case identity and independent source anchors remain valid.
            return any(isinstance(ref, dict) and ref.get('binding') == 'case_fee_settlement'
                       and ref.get('method') in ('local_agent', 'visual_agent_local_evidence')
                       and bool(fields.get(field)) and ref.get('value') == fields.get(field)
                       and ref.get('source_path') == entry.get('source_path') and ref.get('page') == entry.get('page')
                       and supporting_refs(ref, fields, source_manifest or []) is not None for ref in refs)
        if (isinstance(entry,dict) and entry.get('resolution')=='field_supported_by_cached_source'
                and entry.get('field')=='收费标准'):
            from .evidence_links import supporting_refs
            fields=analysis.fields or {}
            refs=(fields.get('_provenance') or {}).get('收费标准') or []
            refs=[refs] if isinstance(refs,dict) else refs
            return any(isinstance(ref,dict) and ref.get('candidate_origin')=='local_cached_fee_notice'
                       and ref.get('method') in ('local_agent','visual_agent_local_evidence')
                       and ref.get('value')==fields.get('收费标准')
                       and ref.get('source_path')==entry.get('source_path') and ref.get('page')==entry.get('page')
                       and supporting_refs(ref,fields,source_manifest or []) is not None for ref in refs)
        if (isinstance(entry,dict) and entry.get('resolution')=='field_supported_by_cached_source'
                and entry.get('field') in ('对方当事人','地址','委托人电话')):
            from .evidence_links import supporting_refs
            fields=analysis.fields or {};field=entry['field']
            refs=(fields.get('_provenance') or {}).get(field) or []
            refs=[refs] if isinstance(refs,dict) else refs
            if any(isinstance(ref,dict) and ref.get('candidate_origin')=='local_cached_court_details'
                   and ref.get('value')==fields.get(field)
                   and ref.get('source_path')==entry.get('source_path') and ref.get('page')==entry.get('page')
                   and supporting_refs(ref,fields,source_manifest or []) is not None for ref in refs):return True
        if (isinstance(entry,dict) and entry.get('resolution')=='field_supported_by_cached_source'
                and entry.get('field') in ('委托人','承办律师','律师事务所')):
            from ..core.v4_bridge import load
            from .evidence_links import supporting_refs
            fields=analysis.fields or {};field=entry['field']
            refs=(fields.get('_provenance') or {}).get(field) or []
            refs=[refs] if isinstance(refs,dict) else refs
            scope={os.path.normcase(os.path.abspath(row['path'])):row['pages']
                   for row in source_manifest or [] if isinstance(row,dict) and isinstance(row.get('path'),str)
                   and row['path'] and type(row.get('pages')) is int and row['pages']>0}
            return any(isinstance(ref,dict) and ref.get('candidate_origin')=='local_cached_poa_roster'
                       and ref.get('source_path')==entry.get('source_path') and ref.get('page')==entry.get('page')
                       and type(ref.get('page')) is int and 1 <= ref['page'] <= scope.get(os.path.normcase(os.path.abspath(ref.get('source_path') or '')),0)
                       and load('source_engagement_evidence').poa_reference_supported(field,fields.get(field),ref,fields)
                       and supporting_refs(ref,fields,source_manifest or []) is not None for ref in refs)
        if (not isinstance(entry, dict) or entry.get("resolution") != "field_supported_by_cached_source"
                or entry.get("field") not in ("对方当事人", "审理法院", "地址", "委托人电话", "当事人")):
            return False
        from .evidence_links import supporting_refs
        fields = analysis.fields or {}
        field = entry["field"]
        binding = {"对方当事人": "same_page_opponent", "审理法院": "court_case_number",
                   "地址": "client_contact", "委托人电话": "client_contact", "当事人": "client_court_party"}[field]
        if any(isinstance(row, dict) and row.get("field") == field and row.get("resolved") is not True
               for row in fields.get("_field_conflicts") or []):
            return False
        refs = (fields.get("_provenance") or {}).get(field) or []
        refs = [refs] if isinstance(refs, dict) else refs
        return any(isinstance(ref, dict) and ref.get("candidate_origin") == "local_cached_candidate"
                   and ref.get("binding") == binding
                   and ref.get("value") == fields.get(field) and bool(fields.get(field))
                   and ref.get("source_path") == entry.get("source_path") and ref.get("page") == entry.get("page")
                   and supporting_refs(ref, fields, source_manifest or []) is not None for ref in refs)
    def linked_now(entry):
        if (not isinstance(entry, dict) or entry.get("resolution") != "accepted_after_linked_evidence"
                or entry.get("field") not in ("地址", "委托人电话")):
            return False
        from .evidence_links import supporting_refs
        fields = analysis.fields or {}
        field = entry["field"]
        current = fields.get(field)
        refs = (fields.get("_provenance") or {}).get(field) or []
        refs = [refs] if isinstance(refs, dict) else refs
        if not isinstance(current, str) or not current.strip() or not isinstance(refs, list):
            return False
        for ref in refs:
            if (isinstance(ref, dict) and ref.get("binding") == "client_contact"
                    and ref.get("value") == current and ref.get("source_path") == entry.get("source_path")
                    and ref.get("page") == entry.get("page")
                    and supporting_refs(ref, fields, source_manifest or [])):
                return True
        return False
    # Keep the original refusal in audit metadata, but do not tell the user a
    # value remains unaccepted after a current two-source check accepted it.
    refused = [entry for entry in refused if not linked_now(entry) and not recalled_now(entry)]
    if refused:
        # Rejected proposals never became facts. One advisory summary avoids
        # making the user approve every hallucination; empty-case, actual
        # conflicts and OCR problems retain their independent blocking checks.
        result.append(issue("fact_review", f"{len(refused)} 项候选事实依据不足，未采纳，已保留原值和材料；如需补录可展开原件核对",
                            detail={"candidate_count":len(refused), "candidates":refused}, blocking=False))
    reviews = []
    for entry in (analysis.fields or {}).get("_field_extraction_review") or []:
        if (isinstance(entry, dict) and entry.get("reason_code") in ("document_operation_limit", "selected_pages_only")
                and isinstance(entry.get("source_path"), str) and type(entry.get("page")) is int and entry["page"] > 0
                and type(entry.get("doc_id")) is int and entry["doc_id"] >= 0):
            reviews.append({key:entry[key] for key in ("source_path", "page", "doc_id", "reason_code")})
    if reviews:
        limited = {(entry["source_path"], entry["doc_id"]) for entry in reviews if entry["reason_code"] == "document_operation_limit"}
        selected = {(entry["source_path"], entry["doc_id"]) for entry in reviews if entry["reason_code"] == "selected_pages_only"} - limited
        parts = []
        if selected:
            parts.append(f"{len(selected)} 份文书仅核对了选定页面，未逐页穷尽")
        if limited:
            parts.append(f"{len(limited)} 份文书达到提取步数上限，字段提取未完成")
        result.append(issue("field_extraction_review", "；".join(parts) + "；原件已保留，可补充核对后保存草稿",
                            detail={"document_count":len(selected | limited), "selected_pages_document_count":len(selected),
                                    "operation_limit_document_count":len(limited), "documents":reviews}, blocking=False))
    if (analysis.fields or {}).get("_form_drafts"):
        from form_drafts import draft_review_message
        message, summary = draft_review_message(analysis.fields)
        if message:
            result.append(issue("form_draft", message, detail=summary, blocking=False))
    # Configured categories and generated titles are not evidence of a case.
    # Test the combined business fields after inheriting the parent's edits,
    # never the delta's fact count (evidence-only supplements legitimately add 0).
    from workstation_agent import FIELDS
    business_fields = (set(FIELDS) - {"案件或项目名称"}) | {"委托人名称", "委托人地址", "案情摘要", "办理结果", "委托人对服务质量意见"}
    current = analysis.fields or {}
    project = current.get("案件或项目名称")
    project_refs = (current.get("_provenance") or {}).get("案件或项目名称") or []
    project_refs = project_refs if isinstance(project_refs, list) else [project_refs]
    # This is now an extraction target too. An explicitly sourced or human
    # project name is a fact, while a system-generated title is still not one.
    project_fact = isinstance(project, str) and bool(project.strip()) and any(
        isinstance(ref, dict) and ref.get("value") == project and (
            ref.get("method") == "human" or (
                ref.get("method") in ("local_agent", "visual_agent_local_evidence")
                and isinstance(ref.get("source_path"), str) and bool(ref["source_path"])
                and type(ref.get("page")) is int and ref["page"] > 0
                and isinstance(ref.get("quote"), str) and project in ref["quote"]))
        for ref in project_refs)
    if not project_fact and not any(isinstance(value, str) and value.strip() for key, value in current.items() if key in business_fields):
        result.append(issue("empty_fields", "未提取到可用案件字段，请检查材料后填写系统表"))
    return enrich_classification_issues(result, analysis.doc_spans, source_manifest)


def unresolved_issues(issues, fields, *, task=None):
    from .field_decisions import fact_conflict_resolved
    decisions = (fields or {}).get("_issue_decisions") or {}
    decisions = decisions if isinstance(decisions, dict) else {}
    result = []
    for item in issues or []:
        if not item.get("blocking"):
            continue
        if item.get("kind") == "field_conflict":
            if not fact_conflict_resolved(task, item.get("detail"), fields=fields):
                result.append(item)
            continue
        decision = decisions.get(item.get("id"))
        if not (isinstance(decision, dict) and decision.get("action") == "acknowledged"
                and isinstance(decision.get("reason"), str) and decision["reason"].strip()):
            result.append(item)
    return result


def merge_manual_fields(analysis, manual_fields, *, evidence_version=None):
    conflicts = []
    for key, value in (manual_fields or {}).items():
        predicted = analysis.fields.get(key)
        if not key.startswith("_") and predicted not in (None, "", value):
            detail = {"field": key, "saved": value, "new": predicted}
            if evidence_version:
                detail["evidence_version"] = evidence_version
            conflicts.append(issue("field_conflict", f"补件提取的「{key}」与已核对值不同，已保留你的值", detail=detail))
        analysis.fields[key] = copy.deepcopy(value)
        if not key.startswith("_"):
            provenance = dict(analysis.fields.get("_provenance") or {})
            history = provenance.get(key) or []
            history = list(history) if isinstance(history, list) else [history]
            if not history or not isinstance(history[-1], dict) or history[-1].get("method") != "human" or history[-1].get("value") != value:
                history.append({"method": "human", "value": value, "inherited": True})
            provenance[key] = history
            analysis.fields["_provenance"] = provenance
    return conflicts


def mark_snapshot_metrics_reused(analysis):
    """No analysis/model call occurred while restoring this checkpoint."""
    analysis.fields["_analysis_metrics"] = {"scope": "this_analysis_call", "analysis_status": "snapshot_reused"}
    if isinstance(analysis.fields.get("_agent_summary"), dict):
        analysis.fields["_agent_summary"] = dict(analysis.fields["_agent_summary"])
        analysis.fields["_agent_summary"].pop("this_run_metrics", None)
    recall = combine_source_recall_metrics(None,
        previous=analysis.fields.get("_source_fact_recall"), reused=True)
    if recall is not None:
        analysis.fields["_source_fact_recall"] = recall


def analysis_reuse_compatible(analysis, config):
    """A same-model snapshot from another algorithm is not a current analysis."""
    mode = (config.get("extraction") or {}).get("mode")
    if mode in ("workstation_agent", "visual_agent"):
        from case_outcome import STRICT_EVIDENCE_VERSION
        if (analysis.fields or {}).get("_field_normalization_version") != STRICT_EVIDENCE_VERSION:
            return False
    summary = (analysis.fields or {}).get("_agent_summary") or {}
    if not isinstance(summary, dict):
        return False
    visual = config.get("extraction", {}).get("mode") == "visual_agent"
    if visual != (summary.get("visual") is True):
        return False
    if visual:
        from visual_archive_agent import VISUAL_ANALYSIS_VERSION
        if summary.get("analysis_version") != VISUAL_ANALYSIS_VERSION:
            return False
    vision = config.get("vision") or {}
    return not visual or (summary.get("model") == vision.get("model")
                          and summary.get("workflow") == vision.get("workflow"))


def analyze_with_parent(ap, task, parent, files, config, org_id, log):
    """Reuse only immutable prior documents; analyze genuine new sources with AI.

    Changed/removed prior sources require a full reanalysis because old extracted
    facts cannot safely be attributed to individual files. Pure additions reuse
    prior segmentation and analyze additions only, surfacing conflicting values.
    """
    import document_segmenter as ds
    from .recognition_checkpoint import analysis_config, RecognitionCheckpointError
    if "_recognition_checkpoint" in config:
        raise RecognitionCheckpointError()
    sources = [ds.DocumentSource(path=f.abs_path, doc_type=f.doc_type) for f in files]
    manual = dict((parent.manual_fields if parent else task.manual_fields) or {})
    previous = None
    parent_snapshot = None
    if parent and snapshot_exists(parent, org_id):
        previous, parent_snapshot = load_analysis(task_work_dir(org_id, parent.case_id, parent.id))
        from .document_classification import verify_classification
        verify_classification(parent, previous)
        if not parent.source_manifest and not manual and analysis_reuse_compatible(previous, config):
            # Legacy tasks did not distinguish human edits. Preserve the entire
            # compatible draft rather than silently losing edits. Incompatible
            # machine-derived history stays in the parent; it must not become
            # an invented human override of newly validated extraction.
            manual = dict(previous.fields or {})
    # Old compatibility snapshots can include machine diagnostics among their
    # presumed human edits. They cannot override this invocation's measurements.
    manual = {key: value for key, value in manual.items()
              if key not in ("_analysis_metrics", "_agent_summary", "_field_normalization_version", "_source_fact_recall", "_field_decision_receipt")}
    previous_recall = copy.deepcopy(previous.fields.get("_source_fact_recall")) if previous else None
    current = task.source_manifest or []
    old = parent.source_manifest if parent else []
    old_ids = {row["file_id"] for row in old or []}
    new_ids = changed_file_ids(old, current)
    current_ids = {row["file_id"] for row in current}
    additions_only = previous is not None and bool(old) and previous.case_type == config["workflow_case_type"] and not (old_ids - current_ids) and not (old_ids & new_ids)
    if parent:
        from .execution_profile import frozen_mode
        previous_profile = getattr(parent, "execution_profile", None) or {}
        current_profile = getattr(task, "execution_profile", None) or {}
        if (frozen_mode(parent) != frozen_mode(task)
                or previous_profile and current_profile and (
                    previous_profile.get("model") != current_profile.get("model")
                    or previous_profile.get("workflow") != current_profile.get("workflow"))):
            additions_only = False
        if previous is not None and not analysis_reuse_compatible(previous, config):
            additions_only = False
    case_type = config.pop("workflow_case_type")
    stage = config.pop("workflow_stage", "")
    if additions_only and hasattr(parent, "source_version"):
        # Production tasks always carry this field. Recompute the old material
        # identity using the requested stage: a mismatch includes a stage-only
        # change, while an absent/invalid stored value cannot authorize reuse.
        # Attribute-less lightweight historical test doubles remain compatible.
        if not parent.source_version or parent.source_version != source_version(old, case_type, stage):
            additions_only = False
    if additions_only and new_ids and case_type == "consultation":
        # Consultation volumes depend on global document dates. Appending fresh
        # doc_ids can place an earlier supplementary record after later records.
        # Reanalyze all sources until incremental ordering can preserve the same
        # global-date validation and fallback as the specialty analyzer.
        additions_only = False
        log("咨询代书补件需要重新核对全卷业务日期顺序；保留已人工核对字段")
    # A later evidence-only supplement does not resolve an earlier conflict.
    # Reuse its exact decision ID only while all prior sources/algorithm remain
    # compatible. Changed/removed sources get fresh conflicts from reanalysis.
    conflicts = list({entry["id"]: copy.deepcopy(entry)
        for entry in (getattr(parent, "issues", None) or [])
        if isinstance(entry, dict) and entry.get("kind") == "field_conflict"
        and isinstance(entry.get("id"), str) and entry["id"]
        and isinstance(entry.get("detail"), dict)}.values()) if additions_only else []
    evidence_version = source_version(current, case_type, stage)
    if not additions_only:
        # Replacing/removing evidence or changing the analysis semantics starts
        # a new review. Preserve human facts, but an old acknowledgement cannot
        # approve a newly derived conflict merely because its values match.
        manual.pop("_issue_decisions", None)
    if additions_only and not new_ids:
        analysis = previous
        mark_snapshot_metrics_reused(analysis)
        log("复用未变化材料的分析快照；保留人工核对内容")
    elif additions_only:
        delta_sources = [source for source, file in zip(sources, files) if file.id in new_ids]
        log(f"补件增量分析：复用 {len(old_ids)} 份材料，仅分析 {len(delta_sources)} 份新增材料")
        from .supplement_identity_context import build_supplement_identity_context
        local_context = build_supplement_identity_context(
            task, parent, previous, parent_snapshot, org_id=org_id, case_type=case_type, stage=stage)
        context_args = {"local_recall_context": local_context} if local_context is not None else {}
        run_config = analysis_config(task, parent, org_id, config, case_type=case_type, stage=stage,
            sources=delta_sources, manual_fields=manual, parent_snapshot=parent_snapshot,
            local_recall_context=local_context, analysis_kind="delta")
        delta = ap.analyze_archive(case_type, sources=delta_sources, config=run_config, log=log, **context_args)
        date_previous = copy.deepcopy(previous.fields)
        analysis = previous
        previous_summary = dict(analysis.fields.get("_agent_summary") or {})
        analysis.fields.pop("_analysis_metrics", None)
        analysis.fields.pop("_source_fact_recall", None)
        if isinstance(analysis.fields.get("_agent_summary"), dict):
            analysis.fields["_agent_summary"] = dict(analysis.fields["_agent_summary"])
            analysis.fields["_agent_summary"].pop("this_run_metrics", None)
        analysis.generated_templates = {}
        analysis.source_paths = [source.path for source in sources]
        unit_ids = {}
        for unit in delta.doc_spans:
            new_doc_id = max((u.doc_id for u in analysis.doc_spans), default=-1) + 1
            unit_ids[unit.doc_id] = new_doc_id
            unit.doc_id = new_doc_id
            analysis.doc_spans.append(unit)
        for item in delta.low_confidence_items or []:
            if isinstance(item, dict) and item.get("doc_id") in unit_ids:
                item["doc_id"] = unit_ids[item["doc_id"]]
        for key, value in delta.fields.items():
            previous_value = analysis.fields.get(key)
            if key in ("_analysis_metrics", "_source_fact_recall"):
                # Timings describe this invocation only, never the reused input.
                analysis.fields[key] = value
                continue
            if key in ("_field_extraction_review", "_visual_classification_review", "_targeted_fact_review") and isinstance(value, list):
                entries = copy.deepcopy(value)
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("doc_id") in unit_ids:
                        entry["doc_id"] = unit_ids[entry["doc_id"]]
                analysis.fields[key] = list(previous_value or []) + entries
                continue
            if key in ("_agent_events", "_field_conflicts", "_ocr_review", "_fact_review") and isinstance(value, list):
                analysis.fields[key] = list(previous_value or []) + value
                continue
            if key == "_provenance" and isinstance(value, dict):
                combined = dict(previous_value or {})
                for field, evidence in value.items():
                    if field not in combined:
                        combined[field] = evidence
                    elif isinstance(combined[field], list) and isinstance(evidence, list):
                        combined[field] = combined[field] + evidence
                analysis.fields[key] = combined
                continue
            if key == "_agent_summary" and isinstance(value, dict):
                reused = previous_summary.get("total_pages_checked", previous_summary.get("pages_checked", 0))
                current_run = value.get("total_pages_checked", value.get("pages_checked", 0))
                if not isinstance(reused, int) or isinstance(reused, bool):
                    reused = 0
                if not isinstance(current_run, int) or isinstance(current_run, bool):
                    current_run = 0
                summary = dict(value)
                summary.update(pages_checked=reused + current_run, total_pages_checked=reused + current_run,
                               this_run_pages=current_run, reused_pages=reused,
                               local=previous_summary.get("local") is True and value.get("local") is True,
                               tools=list(dict.fromkeys(list(previous_summary.get("tools") or []) + list(value.get("tools") or []))))
                for count_key in ("accepted_fact_count", "rejected_fact_count", "source_pages_checked"):
                    if count_key in value:
                        summary["this_run_" + count_key] = value[count_key]
                        old_count = previous_summary.get(count_key)
                        summary[count_key] = old_count + value[count_key] if type(old_count) is int and type(value[count_key]) is int else None
                if "empty_fact_pages" in value:
                    summary["empty_fact_pages"] = list(previous_summary.get("empty_fact_pages") or []) + list(value["empty_fact_pages"])
                analysis.fields[key] = summary
                continue
            if not value:
                continue
            if previous_value in (None, "", [], {}):
                analysis.fields[key] = value
            elif previous_value != value and not key.startswith("_"):
                conflicts.append(issue("field_conflict", f"补件中的「{key}」与原草稿不同，请核对", detail={"field": key, "saved": previous_value, "new": value, "evidence_version": evidence_version}))
        analysis.low_confidence_items = list(analysis.low_confidence_items or []) + list(delta.low_confidence_items or [])
        analysis.outcome_warnings = list(dict.fromkeys(list(analysis.outcome_warnings or []) + list(delta.outcome_warnings or [])))
        analysis.template_issues = []
        import archive_catalog as ac
        catalog = ac.get_catalog(case_type)
        virtual = {item.templates[0]: "pending-render" for item in catalog if item.source == "system" and item.templates}
        analysis.found_seqs = ap.compute_found_seqs(catalog, analysis.doc_spans, virtual)
        analysis.missing_items = ap.compute_missing_items(case_type, catalog, analysis.found_seqs)
        from intake_date_supplement import refresh as refresh_intake_date
        if not delta.low_confidence_items:
            refresh_intake_date(analysis.fields, date_previous, delta.fields, local_context, manual, current, conflicts)
    else:
        run_config = analysis_config(task, parent, org_id, config, case_type=case_type, stage=stage,
            sources=sources, manual_fields=manual, parent_snapshot=parent_snapshot,
            local_recall_context=None, analysis_kind="full")
        analysis = ap.analyze_archive(case_type, sources=sources, config=run_config, log=log)
    if not (additions_only and not new_ids):
        recall = combine_source_recall_metrics(analysis.fields.get("_source_fact_recall"),
                                              previous=previous_recall)
        if recall is not None:
            analysis.fields["_source_fact_recall"] = recall
    conflicts += merge_manual_fields(analysis, manual, evidence_version=evidence_version)
    from .outcome_state import refresh_missing_outcome
    refresh_missing_outcome(analysis, manual, current, conflicts)
    from .document_classification import DECISIONS, apply_decisions
    if manual.get(DECISIONS):
        apply_decisions(analysis, current, manual[DECISIONS], stage)
    return analysis, manual, conflicts
