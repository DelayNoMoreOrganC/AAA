from __future__ import annotations

import logging
import os
import asyncio
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy

from sqlalchemy import select

from ..config import ORGS_DIR, get_settings
from ..core.config_adapter import build_v4_config
from ..core.v4_bridge import archive_pipeline
from ..database import AsyncSessionLocal
from ..case_access import case_access_filter
from ..models import ArchiveTask, Case, CaseFile, Org, TaskStatus, User
from ..services.analysis_snapshot import (
    SYSTEM_TEMPLATE_NAMES,
    docx_dir,
    load_analysis,
    load_snapshot_data,
    preview_dir,
    save_snapshot,
    stabilize_templates,
    task_work_dir,
    update_snapshot_fields,
)
from ..services.task_manager import task_manager
from ..services.browser_pdf_service import BrowserPdfError, render_system_form_pdfs
from ..services.word_service import run_word
from ..services.readiness import check_readiness
from .task_sources import build_source_manifest, source_version, fields_digest
from .task_workflow import analyze_with_parent, analysis_issues, unresolved_issues, mark_snapshot_metrics_reused, analysis_reuse_compatible
from .document_classification import verify_classification, ClassificationError
from .safe_errors import ErrorCode, SafeTaskError, error_code, public_error, log_failure, readiness_error
from .execution_profile import task_config, profile_overrides
from .party_binding_state import reconcile_party_bindings, party_binding_issues, sync_party_binding_issues

logger = logging.getLogger("v6.archive")


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _safe_base_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name)).strip(' .')[:100]
    if not name or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1, 10)], *[f'LPT{i}' for i in range(1, 10)]}:
        name = '归档_' + name
    return name


def _build_sources(files):
    import document_segmenter as ds
    return [ds.DocumentSource(path=f.abs_path, doc_type=f.doc_type) for f in files]


def _build_catalog_status(analysis, stage=None, source_manifest=None):
    from .archive_rules import catalog_material_status
    return catalog_material_status(analysis, stage, source_manifest)


def _persist_fields(analysis) -> dict:
    fields = dict(analysis.fields or {})
    warnings = getattr(analysis, "outcome_warnings", None) or []
    if warnings:
        fields["_outcome_warnings"] = list(warnings)
    return fields


def refresh_form_drafts(analysis, manual_fields, source_manifest, issues=None, *, task=None, target_revision=None):
    """One shared value set for the browser, editable Word and final PDF."""
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    from form_drafts import derive_form_drafts, _STAGE_CONFLICT_FIELDS
    analysis.fields = reconcile_party_bindings(analysis.fields, manual_fields, source_manifest)
    from .source_forms import original_form_refs, quality_component_refs
    original_forms=original_form_refs(analysis.doc_spans,source_manifest,analysis.case_type)
    if original_forms:analysis.fields['_original_forms']=original_forms
    else:analysis.fields.pop('_original_forms',None)
    components=quality_component_refs(analysis.doc_spans,source_manifest,analysis.case_type)
    if components:analysis.fields['_original_form_components']={'质量监督卡':components}
    else:analysis.fields.pop('_original_form_components',None)
    original_intake=original_forms.get('立案审批表')
    if original_intake:analysis.fields['_source_intake_approval']=original_intake
    else:analysis.fields.pop('_source_intake_approval',None)
    from .field_decisions import fact_conflict_resolved
    candidates = list((analysis.fields or {}).get("_field_conflicts") or []) + [
        entry["detail"] for entry in issues or [] if entry.get("kind") == "field_conflict"
        and isinstance(entry.get("detail"), dict)]
    stage_resolved = [entry for entry in candidates if fact_conflict_resolved(task, entry,
        fields=analysis.fields, manual=manual_fields or {}, revision=target_revision)]
    blocked = {entry["detail"].get("field") for entry in issues or []
        if entry.get("kind") == "field_conflict" and isinstance(entry.get("detail"), dict)
        and entry["detail"] not in stage_resolved}
    stage_blocked = blocked & _STAGE_CONFLICT_FIELDS
    # Acknowledgement is UI history only; raw candidates remain untouched.
    acknowledged = stage_resolved
    analysis.fields = derive_form_drafts(analysis.fields, analysis.doc_spans,
        source_manifest=source_manifest, manual_fields=manual_fields, blocked_fields=blocked,
        acknowledged_conflicts=acknowledged, resolved_conflicts=stage_resolved, stage_blocked_fields=stage_blocked)
    from .outcome_state import refresh_missing_outcome
    refresh_missing_outcome(analysis, manual_fields, source_manifest, issues, resolved_conflicts=stage_resolved)
    return analysis.fields


async def _persist_task(task_id, **fields):
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(ArchiveTask).where(ArchiveTask.id == task_id))
        task = res.scalar_one_or_none()
        if task is not None:
            if "artifacts" in fields and fields["artifacts"] is None:
                from .artifact_history import retain_published_generation
                retain_published_generation(task)
            for k, v in fields.items():
                setattr(task, k, v)
            await db.commit()


async def _fail_task(task_id, tracker, exc, fallback):
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    from glm_vision_client import GlmVisionError
    from deepseek_vision_client import DeepSeekVisionError
    from recognition_journal import RecognitionJournalError
    from .recognition_checkpoint import RecognitionCheckpointError
    from .original_template_service import OriginalTemplateError
    from original_catalog import OriginalCatalogError
    from .safe_errors import original_template_hint, original_template_target
    field_hint = original_template_hint(exc)
    recovery_target = original_template_target(exc)
    if isinstance(exc, OriginalTemplateError):
        exc = SafeTaskError(ErrorCode.ORIGINAL_TEMPLATE_OVERFLOW if exc.code in ("overflow", "page_count", "frame")
                            else ErrorCode.ORIGINAL_TEMPLATE_FAILED)
    if isinstance(exc, OriginalCatalogError):
        exc = SafeTaskError(ErrorCode.CATALOG_TEMPLATE_MISMATCH)
    if isinstance(exc, DeepSeekVisionError):
        from .safe_errors import deepseek_error_code
        exc = SafeTaskError(deepseek_error_code(exc))
    if isinstance(exc, GlmVisionError):
        exc = SafeTaskError(ErrorCode.GLM_ANALYSIS_FAILED)
    if type(exc) is RecognitionJournalError:
        from .safe_errors import recognition_progress_error_code
        exc = SafeTaskError(recognition_progress_error_code(exc))
    if type(exc) is RecognitionCheckpointError:
        exc = SafeTaskError(ErrorCode.RECOGNITION_PROGRESS_CONFIG)
    if type(exc) is BrowserPdfError:
        # BrowserPdfError currently carries only a message, not structured
        # diagnostic attributes. Map by type without parsing or copying it.
        exc = SafeTaskError(ErrorCode.BROWSER_RENDER_FAILED)
    code = log_failure(logger, exc, task_id, fallback)
    message = public_error(exc, fallback) + field_hint
    try:
        editable_overflow = code == ErrorCode.ORIGINAL_TEMPLATE_OVERFLOW
        await _persist_task(task_id, status=TaskStatus.awaiting_review if editable_overflow else TaskStatus.failed,
                            phase="needs_input" if editable_overflow else "failed",
                            output_pdf="", artifacts=None, error=message,
                            recovery_target=recovery_target if editable_overflow else None,
                            finished_at=None if editable_overflow else _now())
    except Exception:
        # A storage failure here must not escape as an unhandled async exception
        # containing the original material or SQL parameter values.
        log_failure(logger, ErrorCode.TASK_FAILURE_PERSIST_FAILED, task_id)
        tracker.fail(ErrorCode.TASK_FAILURE_PERSIST_FAILED)
        return
    tracker.fail(exc if type(exc) is SafeTaskError else code)


async def _load_case_context(case_id, org_id, user_id):
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, user_id)
        if not actor or not actor.is_active or actor.org_id != org_id:
            return None
        res = await db.execute(select(Case).where(Case.id == case_id, case_access_filter(actor)))
        case = res.scalar_one_or_none()
        if not case:
            return None
        fres = await db.execute(select(CaseFile).where(CaseFile.case_id == case_id).order_by(CaseFile.created_at))
        files = fres.scalars().all()
        # Rendering/editing is local. Only run_archive may obtain a cloud
        # configuration after validating its frozen, version-bound authority.
        config = await build_v4_config(db, user_id, overrides={"processing_mode": "local"})
        return case, files, config


async def _load_org_name(org_id: str) -> str:
    async with AsyncSessionLocal() as db:
        value = await db.scalar(select(Org.name).where(Org.id == org_id))
        return value or ""


def _work_dir_for(task, org_id: str) -> str:
    return task_work_dir(org_id, task.case_id, task.id)


async def _task_record(task_id):
    async with AsyncSessionLocal() as db:
        return await db.get(ArchiveTask, task_id)


def _frozen_files(task, files):
    if not task.source_manifest:
        return files
    return [SimpleNamespace(id=row["file_id"], filename=row["filename"], abs_path=row["path"],
                            doc_type=row["doc_type"]) for row in task.source_manifest]


async def run_archive(task_id, case_id, org_id, user_id, order_mode="catalog"):
    tracker = task_manager.get_tracker(task_id)
    try:
        ap = archive_pipeline()
        ctx = await _load_case_context(case_id, org_id, user_id)
        if not ctx:
            raise SafeTaskError(ErrorCode.CASE_UNAVAILABLE)
        case, files, config = ctx
        if not files:
            raise SafeTaskError(ErrorCode.NO_SOURCES)
        task = await _task_record(task_id)
        automatic_delivery = task.requested_operation in ("analyze_and_draft", "draft")
        current = await asyncio.to_thread(build_source_manifest, files)
        current_version = source_version(current, case.case_type, getattr(case, "stage", ""))
        async with AsyncSessionLocal() as db:
            config = await task_config(db, task, actual_source_version=current_version)
        files = _frozen_files(task, files)
        manifest = await asyncio.to_thread(build_source_manifest, files)
        if task.source_version and source_version(manifest, case.case_type, getattr(case, "stage", "")) != task.source_version:
            raise SafeTaskError(ErrorCode.SOURCE_CHANGED)
        case_type = case.case_type
        base_name = _safe_base_name(os.path.splitext(files[0].filename)[0])
        order_mode = order_mode or "catalog"
        config.setdefault("archive", {})["order_mode"] = order_mode
        config["archive"]["stage"] = getattr(case, "stage", "")
        work = task_work_dir(org_id, case_id, task_id)
        parent = await _task_record(task.parent_task_id) if task.parent_task_id else None
        analysis_mode = (task.execution_profile or {}).get("processing_mode", "local")
        reused_checkpoint = False
        if os.path.isfile(os.path.join(work, "analysis_snapshot.json")):
            analysis, snapshot = load_analysis(work)
            verify_classification(task, analysis)
            if snapshot.get("workflow", {}).get("source_version") != task.source_version:
                raise SafeTaskError(ErrorCode.SNAPSHOT_STALE)
            reused_checkpoint = analysis_reuse_compatible(analysis, config)
            if reused_checkpoint:
                # Reusing bytes locally does not change their original provider.
                analysis_mode = snapshot.get("processing_mode") or "unknown"
                mark_snapshot_metrics_reused(analysis)
                manual = dict(task.manual_fields or {})
                conflicts = list(task.issues or [])
                tracker.log("从已保存分析检查点恢复，无需重复识别材料")
            else:
                # Preserve this task's human edits, but no old algorithm spans.
                parent = None
        if not reused_checkpoint:
            async with AsyncSessionLocal() as db:
                readiness = await check_readiness(db, task.created_by, overrides=profile_overrides(task))
            if not readiness["ready"]:
                raise readiness_error(readiness)
            await _persist_task(task_id, status=TaskStatus.running, phase="analyzing", stage="正在识别与分析材料", order_mode=order_mode)
            tracker.update(5.0, "正在识别与分析材料")
            config["workflow_case_type"] = case_type
            config["workflow_stage"] = getattr(case, "stage", "")
            analysis, manual, conflicts = await run_word(analyze_with_parent, ap, task, parent, files, config, org_id, tracker.log)
        refresh_form_drafts(analysis, manual, manifest, conflicts, task=task)
        conflicts = [entry for entry in conflicts if entry.get("kind") not in ("form_draft", "party_binding")]
        preview_only = get_settings().preview_only
        tracker.update(55.0, "正在生成浏览器预览" if preview_only else "正在生成系统表")

        os.makedirs(work, exist_ok=True)
        if not preview_only:
            stabilize_templates(analysis, work, log=tracker.log)
        save_snapshot(work, analysis, base_name=base_name, order_mode=order_mode,
                      processing_mode=analysis_mode,
                      metadata={"source_version": task.source_version, "source_manifest": manifest,
                                "revision": task.revision, "manual_fields": manual, "case_stage": getattr(case, "stage", "")})
        persist_fields = _persist_fields(analysis)
        dx = "" if preview_only else docx_dir(work)
        issues = {entry["id"]: entry for entry in conflicts + analysis_issues(analysis, task.source_manifest)
                  + party_binding_issues(analysis.fields, task.source_manifest)}
        issues = list(issues.values())
        from .archive_rules import get_rule_readiness
        rules = get_rule_readiness(case_type, stage=getattr(case, "stage", None))
        needs_input = bool(analysis.missing_items or unresolved_issues(issues, persist_fields, task=task))

        await _persist_task(
            task_id,
            status=TaskStatus.running if automatic_delivery else TaskStatus.awaiting_review,
            phase="rendering" if automatic_delivery else "needs_input" if needs_input else "ready_to_finalize",
            checkpoint="analyzed", requested_operation="draft" if automatic_delivery else "analyze", manual_fields=manual,
            issues=issues, rule_readiness=rules,
            progress=60.0,
            stage="整理完成，正在生成整卷档案草稿" if automatic_delivery else "请处理材料异常并核对草稿" if needs_input else "草稿已准备好，请最终确认出卷",
            fields=persist_fields,
            catalog_status=_build_catalog_status(analysis, stage=getattr(case, "stage", None), source_manifest=task.source_manifest),
            output_docx_dir=dx,
            error="",
            finished_at=None,
        )
        if automatic_delivery:
            await run_assemble(task_id, case_id, org_id, user_id, order_mode, draft=True)
        else:
            tracker.update(60.0, "待核对浏览器预览与字段" if preview_only else "待核对表格与字段")
            tracker.finish()
    except Exception as exc:
        await _fail_task(task_id, tracker, exc, ErrorCode.ANALYSIS_FAILED)


async def run_assemble(task_id, case_id, org_id, user_id, order_mode=None, skipped=None, *, draft=False):
    tracker = task_manager.get_tracker(task_id)
    try:
        ap = archive_pipeline()
        ctx = await _load_case_context(case_id, org_id, user_id)
        if not ctx:
            raise SafeTaskError(ErrorCode.CASE_UNAVAILABLE)
        case, files, config = ctx
        task = await _task_record(task_id)
        if not task.source_version or not task.source_manifest:
            raise SafeTaskError(ErrorCode.SOURCE_VERSION_MISSING)
        required_missing = [item for item in task.catalog_status or [] if not item.get("found")
                            and item.get("legal_requirement_verified") is True and item.get("requirement") == "required"]
        from .archive_rules import unresolved_material_requirements
        required_missing += unresolved_material_requirements(task.catalog_status)
        if required_missing and not draft:
            rules = dict(task.rule_readiness or {})
            rules.update(formal_ready=False, unresolved_required_items=required_missing)
            previous = task.artifacts or {}
            keep_draft = (previous.get("delivery_kind") == "draft" and previous.get("valid")
                          and previous.get("revision") == task.revision and previous.get("source_version") == task.source_version)
            output = {} if keep_draft else {"output_pdf":"", "artifacts":None, "finished_at":None}
            await _persist_task(task_id, status=TaskStatus.awaiting_review, phase="draft_ready" if keep_draft else "needs_input", confirmation=None,
                                stage="草稿已保留，已核验必需材料仍待补充", rule_readiness=rules, **output)
            tracker.update(60.0, "草稿已保留，已核验必需材料仍待补充")
            tracker.finish()
            return
        current = await asyncio.to_thread(build_source_manifest, files)
        if task.source_version and source_version(current, case.case_type, getattr(case, "stage", "")) != task.source_version:
            raise SafeTaskError(ErrorCode.SOURCE_CHANGED)
        confirmation = task.confirmation or {}
        if not draft and (confirmation.get("revision") != task.revision or confirmation.get("source_version") != task.source_version):
            raise SafeTaskError(ErrorCode.CONFIRMATION_REQUIRED)
        work = task_work_dir(org_id, case_id, task_id)
        analysis, snap = load_analysis(work)
        verify_classification(task, analysis)
        order_mode = order_mode or confirmation.get("order_mode") or task.order_mode or snap.get("order_mode") or "catalog"
        if draft and (snap.get("workflow", {}).get("source_version") != task.source_version
                      or fields_digest(analysis.fields, order_mode) != fields_digest(task.fields, order_mode)):
            raise SafeTaskError(ErrorCode.SNAPSHOT_CONFIRMATION_MISMATCH)
        if not draft and confirmation.get("fields_digest") != fields_digest(analysis.fields, order_mode):
            raise SafeTaskError(ErrorCode.SNAPSHOT_CONFIRMATION_MISMATCH)
        projected = reconcile_party_bindings(analysis.fields, task.manual_fields or {}, task.source_manifest)
        if projected != analysis.fields:
            # Old saved tasks may predate the save-time identity guard. Do not
            # render a silently different field set under their old approval.
            analysis.fields = projected
            refresh_form_drafts(analysis, task.manual_fields or {}, task.source_manifest, task.issues, task=task)
            task.fields = analysis.fields
            task.issues = sync_party_binding_issues(task.issues, analysis.fields, task.source_manifest)
            from .outcome_state import sync_missing_outcome_issue
            task.issues = sync_missing_outcome_issue(task.issues, analysis)
            update_snapshot_fields(work, analysis.fields, generated_templates={},
                                   workflow_metadata=_next_revision_metadata(task))
            invalidate_output(task)
            await _persist_task(task_id, fields=task.fields, issues=task.issues, revision=task.revision,
                                output_pdf="", artifacts=None, confirmation=None, error="", recovery_target=None,
                                status=task.status, phase="needs_input", checkpoint=task.checkpoint,
                                progress=task.progress, stage="委托人关联已更新，请核对留空的对方信息后重新生成", finished_at=None)
            tracker.update(60.0, "委托人关联已更新，请核对留空的对方信息后重新生成")
            tracker.finish()
            return
        base_name = _safe_base_name(snap.get("base_name") or "archive")
        config.setdefault("archive", {})["order_mode"] = order_mode
        config["archive"]["stage"] = getattr(case, "stage", "")
        config.setdefault("output", {})["original_templates"] = True
        from original_catalog import row_mapping, OriginalCatalogError
        try:
            present_slots = {unit.catalog_seq for unit in analysis.doc_spans}
            original_slots = set(row_mapping(analysis.case_type, has_execution=15 in present_slots)) | {0}
            if present_slots - original_slots:
                raise OriginalCatalogError()
        except OriginalCatalogError:
            raise SafeTaskError(ErrorCode.CATALOG_TEMPLATE_MISMATCH) from None
        # Draft generation does not invent acknowledgement or skip present pages.
        # Missing slots are recorded in the single supplement list and quality report.
        skip = [item["seq"] for item in analysis.missing_items] if draft else skipped if skipped is not None else confirmation.get("skipped", [])
        if not draft and unresolved_issues(task.issues, analysis.fields, task=task):
            raise SafeTaskError(ErrorCode.UNRESOLVED_ISSUES)
        from .output_derivation import new_render_directory, finalize_cover_count, RENDERER_VERSION
        from .artifact_history import last_published_generation
        previous_generation = last_published_generation(task) or {}
        result_dir = new_render_directory(work, task.revision, previous_generation)
        await _persist_task(task_id, status=TaskStatus.running, phase="rendering", stage="正在生成归档表格", output_pdf="", artifacts=None)
        tracker.update(65.0, "正在生成归档表格")
        organization_name = await _load_org_name(org_id)
        from .system_docx_service import generate_system_docx
        from .source_forms import original_form_refs, export_original_form, quality_component_refs
        original_forms=original_form_refs(analysis.doc_spans,task.source_manifest,analysis.case_type)
        quality_refs=quality_component_refs(analysis.doc_spans,task.source_manifest,analysis.case_type)
        render_options={'exclude_templates':tuple(original_forms)} if original_forms else {}
        if quality_refs and '质量监督卡' not in original_forms:
            from source_form_policy import missing_quality_components
            render_options['quality_component']=missing_quality_components(quality_refs)[0]
        docx_paths = await asyncio.to_thread(generate_system_docx, analysis.fields, organization_name, result_dir, tracker.log, **render_options)
        if set(docx_paths) != set(SYSTEM_TEMPLATE_NAMES)-set(render_options.get('exclude_templates',())):
            raise SafeTaskError(ErrorCode.SYSTEM_FORMS_INCOMPLETE)
        # Every production volume uses the verified native original-form PDFs.
        # Editable Word files remain separate deliverables, never an unchecked
        # alternate conversion branch when preview_only settings differ.
        preview_only = True
        config["output"]["preview_only"] = True
        config["output"]["pagination_mode"] = "draft" if draft else "body"
        analysis.generated_templates = await asyncio.to_thread(render_system_form_pdfs, analysis.fields, organization_name, result_dir, tracker.log, **render_options)
        save_snapshot(work, analysis, base_name=base_name, order_mode=order_mode, skipped=skip,
                      metadata={"revision": task.revision, "docx_templates": docx_paths})
        await _persist_task(task_id, checkpoint="rendered", phase="assembling", stage="正在合并归档 PDF")
        tracker.update(75.0, "正在合并归档 PDF")
        output_pdf = os.path.join(result_dir, base_name + ("_档案草稿.pdf" if draft else "_完整归档.pdf"))
        assemble_call = lambda: ap.assemble_archive(analysis, output_pdf=output_pdf, config=config, skipped=skip, log=tracker.log)
        result = await asyncio.to_thread(assemble_call) if preview_only else await run_word(assemble_call)
        if not result.success:
            raise SafeTaskError(ErrorCode.ASSEMBLY_VALIDATION_FAILED)
        if (getattr(result,"pagination",None) or {}).get("mode") != ("draft" if draft else "body"):
            raise SafeTaskError(ErrorCode.ASSEMBLY_VALIDATION_FAILED)
        tracker.update(82.0, "正在回填整卷页数并复核分页")
        finalize = lambda: finalize_cover_count(analysis, organization_name, docx_paths, result, assemble_call,
                                                preview_only=preview_only, log=tracker.log)
        from .original_template_service import OriginalTemplateError
        try:
            result, derived_output = await asyncio.to_thread(finalize) if preview_only else await run_word(finalize)
        except (SafeTaskError, BrowserPdfError, OriginalTemplateError):
            raise
        except Exception:
            raise SafeTaskError(ErrorCode.COVER_PAGE_COUNT_FAILED) from None
        from .original_template_service import template_metadata
        from original_catalog import source_metadata
        derived_output['original_forms']=original_forms
        derived_output['original_form_components']={'质量监督卡':quality_refs} if quality_refs else {}
        derived_output['generated_quality_component']=render_options.get('quality_component')
        derived_output['intake_form']='source_original_preserved' if '立案审批表' in original_forms else 'supplementary_draft'
        derived_output["template_evidence"] = {
            "forms": {name: template_metadata(name, analysis.fields) for name in docx_paths},
            "catalog": source_metadata(analysis.case_type, has_execution=15 in (analysis.found_seqs or set())),
            "format_verification": "original_frames_and_page_counts_verified",
        }
        if render_options.get('quality_component'):
            evidence=derived_output['template_evidence']['forms']['质量监督卡']
            evidence.update(expected_pages=1,generated_component=render_options['quality_component'])
        save_snapshot(work, analysis, base_name=base_name, order_mode=order_mode, skipped=skip,
                      metadata={"revision":task.revision, "docx_templates":docx_paths, "derived_output":derived_output})
        # Recheck inputs after the long-running operation before publishing any result.
        latest = await _load_case_context(case_id, org_id, user_id)
        latest_manifest = await asyncio.to_thread(build_source_manifest, latest[1])
        if task.source_version and source_version(latest_manifest, case.case_type, getattr(case, "stage", "")) != task.source_version:
            raise SafeTaskError(ErrorCode.SOURCE_CHANGED)
        await _persist_task(task_id, phase="verifying", stage="正在校验并打包归档成果")
        tracker.update(90.0, "正在校验并打包归档成果")
        from .quality_report import write_quality_report
        await asyncio.to_thread(write_quality_report, result_dir, analysis, files, result.output_pdf,
                                snap.get("processing_mode", "unknown"), skip, verification=result, stage=getattr(case, "stage", None), derived_output=derived_output,
                                draft=draft, review_issues=unresolved_issues(task.issues, analysis.fields, task=task))
        from .archive_rules import get_rule_readiness
        rules = get_rule_readiness(case.case_type, stage=getattr(case, "stage", None))
        if draft:
            rules = dict(rules, formal_ready=False, unresolved_required_items=required_missing)
        required = {"archive_pdf": output_pdf, "quality_json": os.path.join(result_dir, "归档质检清单.json"),
                    "quality_html": os.path.join(result_dir, "归档质检清单.html")}
        required.update({"docx:" + name: path for name, path in docx_paths.items()})
        for name in original_forms:
            required['source_pdf:'+name]=await asyncio.to_thread(export_original_form,name,analysis.doc_spans,result_dir,task.source_manifest,analysis.case_type)
        if render_options.get('quality_component'):
            required['source_component_pdf:质量监督卡']=await asyncio.to_thread(export_original_form,'质量监督卡',analysis.doc_spans,result_dir,task.source_manifest,analysis.case_type)

        archive_zip = os.path.join(result_dir, "归档包.zip")
        def package():
            temp = archive_zip + ".tmp"
            with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as bundle:
                for path in required.values():
                    bundle.write(path, os.path.basename(path))
            os.replace(temp, archive_zip)
        await asyncio.to_thread(package)
        required["package_zip"] = archive_zip
        from .artifact_manifest import verify_artifact_manifest
        manifest = await asyncio.to_thread(verify_artifact_manifest, result_dir, required,
                                          expected_source_pages=sum(item["pages"] for item in current),
                                          source_pages_included=result.original_pages_included,
                                          require_pagination=True, pagination=result.pagination)
        if not manifest.get("valid"):
            raise SafeTaskError(ErrorCode.ARTIFACT_VALIDATION_FAILED)
        manifest["revision"] = task.revision
        manifest["source_version"] = task.source_version
        manifest["result_dir"] = result_dir
        manifest["renderer_version"] = RENDERER_VERSION
        manifest["derived_output"] = derived_output
        manifest["delivery_kind"] = "draft" if draft else "reviewed"
        manifest["pagination"] = result.pagination
        if previous_generation:
            manifest["previous_generation"] = {key:previous_generation.get(key) for key in
                ("result_dir", "revision", "source_version", "delivery_kind", "renderer_version", "artifacts")}
        from .analysis_snapshot import _atomic_write
        _atomic_write(os.path.join(result_dir, "artifact_manifest.json"), manifest)
        from .output_export import export_archive
        saved_to = await asyncio.to_thread(export_archive, result_dir, org_id, case_id, task_id)
        fields = _persist_fields(analysis)
        fields["_saved_to"] = saved_to
        title = "档案草稿已生成，请按补充清单完善材料" if draft else "完整体验归档已完成（适用规范待核验）" if not rules.get("formal_ready") else "归档成果已完成"
        await _persist_task(task_id, status=TaskStatus.awaiting_review if draft else TaskStatus.done,
                            phase="draft_ready" if draft else "completed", checkpoint="completed",
                            progress=100.0, stage=title, fields=fields,
                            catalog_status=_build_catalog_status(analysis, stage=getattr(case, "stage", None), source_manifest=task.source_manifest), output_pdf=result.output_pdf,
                            output_docx_dir=os.path.dirname(next(iter(docx_paths.values()))), artifacts=manifest,
                            rule_readiness=rules, error="", order_mode=order_mode, finished_at=_now())
        tracker.update(100.0, title)
        tracker.finish()
    except Exception as exc:
        await _fail_task(task_id, tracker, exc, ErrorCode.ASSEMBLY_FAILED)


async def update_task_fields(task, org_id: str, field_updates: dict, actor_id: str = "", *, accept_current=None) -> dict:
    work = _work_dir_for(task, org_id)
    from .field_snapshot_state import reconcile_field_snapshot, field_save_baseline, field_save_marker, SAVE_MARKER
    reconcile_field_snapshot(task, work)
    data = load_snapshot_data(work)
    analysis, _ = load_analysis(work)
    verify_classification(task, analysis)
    # The task row is the last committed version. A prior snapshot write may
    # have survived a failed DB commit and must never become a successful no-op.
    merged = dict(task.fields or {})
    changes = {key: value for key, value in (field_updates or {}).items() if merged.get(key) != value}
    if accept_current is not None:
        from .field_decisions import validate_decision_snapshot
        validate_decision_snapshot(task, data)
        field = accept_current["field"]
        changes[field] = field_updates[field]
    # An explicit clear can equal an empty canonical value while the displayed
    # form was populated from a legacy alias. Record that first human decision.
    for key, value in (field_updates or {}).items():
        if not key.startswith("_") and value == "" and key not in (task.manual_fields or {}):
            changes[key] = value
    if not changes:
        return merged
    original_fields = deepcopy(merged)
    baseline_analysis = deepcopy(analysis)
    baseline_analysis.fields = deepcopy(merged)
    before_projection = deepcopy(refresh_form_drafts(baseline_analysis,
        deepcopy(task.manual_fields or {}), task.source_manifest, task.issues,
        task=task, target_revision=task.revision))
    save_baseline = field_save_baseline(task)
    issue_decisions = dict(merged.get("_issue_decisions") or {})
    issue_decisions.update(field_updates.get("_issue_decisions") or {})
    for item in task.issues or []:
        detail = item.get("detail") or {}
        if item.get("kind") == "field_conflict" and isinstance(detail, dict) and detail.get("field") in changes:
            issue_decisions[item["id"]] = {"action": "acknowledged", "reason": "已人工修改并核对字段：" + detail["field"]}
    if issue_decisions:
        field_updates = dict(field_updates, _issue_decisions=issue_decisions)
    manual = dict(task.manual_fields or {})
    manual.update(changes)
    task.manual_fields = manual
    merged.update(field_updates or {})
    if "结案小结" in field_updates:
        v = field_updates["结案小结"]
        merged["审（办）结果"] = v
        merged["审办结果"] = v
    provenance = dict(merged.get("_provenance") or {})
    for key, value in changes.items():
        if key.startswith("_"):
            continue
        previous = provenance.get(key) or []
        previous = list(previous) if isinstance(previous, list) else [previous]
        human = {"method": "human", "value": value, "edited_at": _now().isoformat(), "actor_id": actor_id}
        if key in ('阶段工作情况','顾问协议状态') and isinstance(merged.get('委托人'),str) and merged['委托人'].strip():
            # Bind this explicit human entry to this task's current subject;
            # a later client change must not reassign the old stage record.
            human['subject']=merged['委托人']
        if accept_current is not None and key == accept_current["field"]:
            human.update(deepcopy(accept_current))
        provenance[key] = previous + [human]
    if provenance:
        merged["_provenance"] = provenance
    if accept_current is not None:
        from .field_decisions import RECEIPT
        merged[RECEIPT] = deepcopy(accept_current)
    _resolve_edited_identity_conflicts(task, merged, changes, data, actor_id=actor_id, decision=accept_current)
    analysis.fields = merged
    merged = refresh_form_drafts(analysis, manual, task.source_manifest, task.issues, task=task, target_revision=task.revision + 1)
    from .form_draft_stability import preserve_unaffected_drafts
    merged = preserve_unaffected_drafts(original_fields, before_projection, merged)
    analysis.fields = merged
    task.issues = [entry for entry in task.issues or [] if entry.get("kind") != "form_draft"] + [
        entry for entry in analysis_issues(analysis, task.source_manifest) if entry.get("kind") == "form_draft"]
    task.issues = sync_party_binding_issues(task.issues, merged, task.source_manifest)
    from .outcome_state import sync_missing_outcome_issue
    task.issues = sync_missing_outcome_issue(task.issues, analysis)
    update_snapshot_fields(work, merged, generated_templates={},
                           workflow_metadata=dict(_next_revision_metadata(task),
                               **{SAVE_MARKER: field_save_marker(task, merged, save_baseline)}))
    task.fields = merged
    invalidate_output(task)
    return merged


def _resolve_edited_identity_conflicts(task, fields, changes, snapshot, *, actor_id="", decision=None):
    """An actual field edit/explicit choice resolves that field, not acknowledgement.

    Retain the original conflict and attach the source scope/value of the human
    decision. Later additions can verify that scope without retaining OCR text.
    """
    import copy
    import hashlib

    from .field_decisions import conflict_digest
    edits = {key: value for key, value in changes.items()
             if not key.startswith("_") and isinstance(value, str)}
    manifest = getattr(task, "source_manifest", None)
    meta = snapshot.get("workflow") or {}
    case_type, stage = snapshot.get("case_type"), meta.get("case_stage", "")
    version = getattr(task, "source_version", None)
    if (not edits or not isinstance(manifest, list) or not manifest
            or not version or meta.get("source_version") != version
            or meta.get("source_manifest") != manifest
            or source_version(manifest, case_type, stage) != version):
        return
    scope = [{key: row.get(key) for key in ("file_id", "sha256", "doc_type", "pages")}
             for row in manifest]
    decisions = {key: {"method": "human_field_edit",
        "task_id": getattr(task, "id", None),
        "revision": (getattr(task, "revision", None) or 1) + 1,
        "source_version": version, "value_digest": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "source_scope": scope, "case_id": getattr(task, "case_id", None),
        "case_type": case_type, "case_stage": stage} for key, value in edits.items()}
    for proof in decisions.values():
        proof["actor_id"] = actor_id
        if decision is not None:
            proof.update({key: copy.deepcopy(decision[key]) for key in
                ("request_id", "payload_digest", "org_id", "operation", "base_revision", "applied_revision", "issue_ids", "conflicts")})
    def resolved_proof(entry):
        return dict(copy.deepcopy(decisions[entry["field"]]), conflict_digest=conflict_digest(entry))
    conflicts = fields.get("_field_conflicts")
    if isinstance(conflicts, list):
        conflicts = copy.deepcopy(conflicts)
        for entry in conflicts:
            if isinstance(entry, dict) and entry.get("field") in decisions:
                entry.update(resolved=True, resolution=resolved_proof(entry))
        fields["_field_conflicts"] = conflicts
    issues = copy.deepcopy(getattr(task, "issues", None) or [])
    for entry in issues:
        if isinstance(entry, dict) and entry.get("kind") == "field_conflict":
            detail = entry.get("detail")
            if isinstance(detail, dict) and detail.get("field") in decisions:
                detail.update(resolved=True, resolution=resolved_proof(detail))
    task.issues = issues


def _next_revision_metadata(task):
    """Write edited facts and their next revision in one atomic snapshot.

    The caller still commits the task row. A failed or interrupted commit is
    recovered from the authoritative row before reading or editing this snapshot.
    """
    metadata = {"revision": (getattr(task, "revision", None) or 1) + 1,
                "manual_fields": dict(getattr(task, "manual_fields", None) or {})}
    for key in ("source_version", "source_manifest"):
        if hasattr(task, key):
            metadata[key] = getattr(task, key)
    return metadata


def invalidate_output(task):
    """Never offer a previous PDF as the result of subsequently edited fields."""
    from .artifact_history import retain_published_generation
    retain_published_generation(task)
    task.output_pdf = ""
    task.artifacts = None
    task.confirmation = None
    task.error = ""
    task.recovery_target = None
    task.revision = (getattr(task, "revision", None) or 1) + 1
    task.phase = "needs_input" if unresolved_issues(getattr(task, "issues", None), getattr(task, "fields", None), task=task) else "ready_to_finalize"
    task.checkpoint = "analyzed"
    task.status = TaskStatus.awaiting_review
    task.progress = 60.0
    task.stage = "内容已保存，请重新生成归档"
    task.finished_at = None


async def regenerate_templates(
    task, org_id: str, user_id: str, field_overrides=None, outcome_type="auto"
):
    ap = archive_pipeline()
    ctx = await _load_case_context(task.case_id, org_id, user_id)
    if not ctx:
        raise RuntimeError("案件不存在")
    case, _files, config = ctx
    work = _work_dir_for(task, org_id)
    from .field_snapshot_state import reconcile_field_snapshot, field_save_baseline, field_save_marker, SAVE_MARKER
    reconcile_field_snapshot(task, work)
    save_baseline = field_save_baseline(task)
    if field_overrides:
        await update_task_fields(task, org_id, field_overrides, actor_id=user_id)
    analysis, snap = load_analysis(work)
    verify_classification(task, analysis)
    merged = dict(analysis.fields or {})
    merged.update(field_overrides or {})
    if outcome_type and outcome_type != "auto":
        from case_outcome import apply_outcome_type_override, unify_case_outcome_fields
        merged = apply_outcome_type_override(merged, outcome_type, "")
        merged = unify_case_outcome_fields(merged)
    analysis.fields = merged
    manual = dict(task.manual_fields or {})
    manual.update({key: value for key, value in (field_overrides or {}).items() if (task.fields or {}).get(key) != value})
    task.manual_fields = manual
    merged = refresh_form_drafts(analysis, manual, task.source_manifest, task.issues, task=task, target_revision=task.revision + 1)
    task.issues = sync_party_binding_issues(task.issues, merged, task.source_manifest)
    from .outcome_state import sync_missing_outcome_issue
    task.issues = sync_missing_outcome_issue(task.issues, analysis)
    save_metadata = dict(_next_revision_metadata(task),
                         **{SAVE_MARKER: field_save_marker(task, merged, save_baseline)})
    if get_settings().preview_only:
        analysis.generated_templates = {}
        save_snapshot(
            work,
            analysis,
            base_name=snap.get("base_name", "archive"),
            order_mode=snap.get("order_mode", "catalog"),
            metadata=save_metadata,
        )
        task.fields = _persist_fields(analysis)
        task.output_docx_dir = ""
        return {}
    import archive_catalog as ac
    catalog = ac.get_catalog(analysis.case_type)
    dx = docx_dir(work)
    os.makedirs(dx, exist_ok=True)
    generated = await run_word(
        ap.generate_system_templates,
        catalog,
        merged,
        log=lambda m: None,
        work_dir=dx,
    )
    analysis.generated_templates = generated
    save_snapshot(work, analysis, base_name=snap.get("base_name", "archive"), order_mode=snap.get("order_mode", "catalog"), metadata=save_metadata)
    task.fields = _persist_fields(analysis)
    task.output_docx_dir = dx
    return generated


async def preview_template_pdf(task, org_id: str, template_name: str) -> str:
    if template_name not in SYSTEM_TEMPLATE_NAMES:
        raise ValueError(f"unknown template: {template_name}")
    work = _work_dir_for(task, org_id)
    _analysis, snap = load_analysis(work)
    verify_classification(task, _analysis)
    # Preview the current revision with the exact original-form renderer. Old
    # generated PDFs are historical artifacts, not evidence of current fields.
    from .output_derivation import visible_derivation
    import uuid
    prev = os.path.join(preview_dir(work), f"r{task.revision or 1}", uuid.uuid4().hex)
    os.makedirs(prev, exist_ok=True)
    pdf_path = os.path.join(prev, f"{template_name}.pdf")
    from .source_forms import original_form_refs, export_original_form, quality_component_refs
    if template_name in original_form_refs(_analysis.doc_spans,task.source_manifest,_analysis.case_type):
        return await asyncio.to_thread(export_original_form,template_name,_analysis.doc_spans,prev,task.source_manifest,_analysis.case_type)
    organization_name = await _load_org_name(org_id)
    from .original_template_service import render_original_pdf
    fields = reconcile_party_bindings(task.fields, task.manual_fields or {}, task.source_manifest)
    if fields != task.fields:
        _analysis.fields = fields
        fields = refresh_form_drafts(_analysis, task.manual_fields or {}, task.source_manifest, task.issues, task=task)
    quality_refs=quality_component_refs(_analysis.doc_spans,task.source_manifest,_analysis.case_type)
    if template_name=='质量监督卡' and quality_refs:
        from source_form_policy import missing_quality_components
        from .quality_form_components import render_quality_component_pdf
        return await asyncio.to_thread(render_quality_component_pdf,missing_quality_components(quality_refs)[0],fields,organization_name,pdf_path)
    return await asyncio.to_thread(render_original_pdf, template_name, fields, organization_name,
                                    pdf_path, derived_output=visible_derivation(task))


async def refill_templates(task, field_overrides, order_mode, outcome_type="auto", org_id="", user_id=""):
    """Compatibility entry point: saving never publishes without final approval."""
    if not org_id or not user_id:
        raise RuntimeError("请从已登录账号的归档任务保存表格")
    if not os.path.isfile(os.path.join(_work_dir_for(task, org_id), "analysis_snapshot.json")):
        raise RuntimeError("旧任务没有分析快照，请继续归档建立新修订")
    await regenerate_templates(task, org_id, user_id, field_overrides, outcome_type)
    invalidate_output(task)


async def save_template_docx(task, org_id: str, template_name: str, content: bytes) -> str:
    if template_name not in SYSTEM_TEMPLATE_NAMES:
        raise ValueError(f"unknown template: {template_name}")
    import tempfile
    from pathlib import Path
    from .file_import_service import _validate_docx
    work = _work_dir_for(task, org_id)
    analysis, snap = load_analysis(work)
    verify_classification(task, analysis)
    dx = docx_dir(work)
    os.makedirs(dx, exist_ok=True)
    path = os.path.join(dx, f"{template_name}.docx")
    fd, temporary = tempfile.mkstemp(dir=dx, suffix=".docx")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        _validate_docx(Path(temporary))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    templates = dict(snap.get("generated_templates") or {})
    templates[template_name] = path
    analysis.generated_templates = templates
    save_snapshot(work, analysis, base_name=snap.get("base_name", "archive"), order_mode=snap.get("order_mode", "catalog"))
    task.output_docx_dir = dx
    invalidate_output(task)
    return path


def get_template_docx_path(task, org_id: str, template_name: str) -> str:
    if template_name not in SYSTEM_TEMPLATE_NAMES:
        raise ValueError(f"unknown template: {template_name}")
    work = _work_dir_for(task, org_id)
    _analysis, snap = load_analysis(work)
    verify_classification(task, _analysis)
    path = (snap.get("workflow", {}).get("docx_templates") or {}).get(template_name) or (snap.get("generated_templates") or {}).get(template_name)
    if path and path.lower().endswith(".docx") and os.path.isfile(path):
        return path
    fallback = os.path.join(docx_dir(work), f"{template_name}.docx")
    if os.path.isfile(fallback):
        return fallback
    raise FileNotFoundError(template_name)
