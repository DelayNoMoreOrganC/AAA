"""Fingerprint recognition and related workflow code; never inspect runtime data or secrets.

The server freezes this at startup. A scheduled, paid regression must match it
before importing either authorized source. Frontend-only changes do not trigger
another real-source run. A changed hash alone does not establish a semantic
recognition change or authorize a paid regression. Keep the list in sync when
adding related modules.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

RECOGNITION_FILES = (
    "archive_pipeline.py", "archive_catalog.py", "case_outcome.py", "page_classifier.py",
    "web/backend/app/services/classification_guidance.py",
    "web/backend/app/services/document_classification.py",
    "visual_document_workflow.py", "visual_archive_agent.py",
    "local_vision_catalog.py", "ollama_vision_client.py", "web/backend/app/services/local_vision.py",
    "web/backend/app/core/config_adapter.py", "deepseek_vision_client.py", "document_title_review.py", "fact_evidence.py",
    "recognition_journal.py", "model_request_budget.py",
    "complaint_brief.py", "narrative_sources.py", "business_intake.py", "form_field_policy.py", "form_cell_contracts.py", "form_synthesis.py", "case_fact_ledger.py",
    "pleading_parties.py", "pleading_sources.py", "engagement_intake.py",
    "fee_display.py",
    "fee_settlement_evidence.py",
    "intake_contract_date.py",
    "intake_date_supplement.py",
    "source_form_policy.py", "web/backend/app/services/source_forms.py",
    "web/backend/app/services/quality_form_components.py",
    "evidence_index.py",
    "evidence_group_state.py",
    "document_continuity.py",
    "classification_context.py",
    "visual_page_view.py",
    "visual_reading_views.py",
    "visual_ocr_orientation.py",
    "visual_fact_readback.py",
    "visual_fee_readback.py",
    "literal_quote_alignment.py",
    "visual_synthesis_sources.py",
    "supplement_synthesis.py",
    "page_reading_store.py",
    "fact_review_resolution.py",
    "visual_boundary_review.py",
    "document_reading_plan.py",
    "document_field_batch.py",
    "case_evidence_search.py",
    "agent_trace.py",
    "machine_field_candidates.py",
    "agent_experience.py", "experience_reading.py",
    "web/backend/app/services/experience_binding.py",
    "web/backend/app/services/experience_sources.py",
    "case_timeline.py", "source_contract_roster.py",
    "document_segmenter.py", "pdf_doc_locator.py", "local_ocr.py", "ocr_review.py",
    "workstation_agent.py", "stage_fact_evidence.py", "linked_fact_evidence.py",
    "linked_party_evidence.py", "party_binding_workflow.py",
    "source_fact_recall.py", "source_court_evidence.py", "local_recall_context.py",
    "trial_level_evidence.py", "source_contact_evidence.py",
    "source_party_evidence.py", "source_engagement_evidence.py", "court_roster_details.py", "source_fee_notice.py", "court_report_summary.py", "form_drafts.py",
    "web/backend/app/services/field_assurance.py",
    "web/backend/app/services/task_workflow.py",
    "web/backend/app/services/analysis_snapshot.py",
    "web/backend/app/services/archive_service.py",
    "web/backend/app/services/form_policy_repair.py",
    "web/backend/app/services/supplement_identity_context.py",
    "web/backend/app/services/outcome_state.py",
    "web/backend/app/services/party_binding_state.py",
    "web/backend/app/services/evidence_links.py",
    "web/backend/app/services/field_snapshot_state.py",
    "web/backend/app/services/field_decisions.py",
    "web/backend/app/services/execution_profile.py",
    "web/backend/app/services/recognition_checkpoint.py",
    "web/backend/app/routers/tasks.py",
)


def recognition_identity(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    digest = hashlib.sha256(b"gd-recognition-code-v1\0")
    normalization_version = None
    for relative in RECOGNITION_FILES:
        content = (root / relative).read_bytes()
        digest.update(relative.encode("utf-8") + b"\0" + hashlib.sha256(content).digest())
        if relative == "case_outcome.py":
            tree = ast.parse(content.decode("utf-8-sig"))
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "STRICT_EVIDENCE_VERSION" for t in node.targets):
                    normalization_version = ast.literal_eval(node.value)
    if not isinstance(normalization_version, str) or not normalization_version.startswith("strict-fields-v"):
        raise ValueError("RECOGNITION_VERSION_UNAVAILABLE")
    return {"recognition_signature": digest.hexdigest(), "normalization_version": normalization_version}
