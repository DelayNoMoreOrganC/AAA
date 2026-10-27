"""Independent pure synthetic probes for reuse and conflict version isolation."""
import copy
from types import SimpleNamespace

import pytest

from app.core.v4_bridge import init_v4_path
init_v4_path()
import archive_pipeline as ap
from case_outcome import STRICT_EVIDENCE_VERSION
from visual_archive_agent import VISUAL_ANALYSIS_VERSION
from app.services import task_workflow as workflow
from tests.test_task_workflow import fixture_analysis


def visual_fields(version=VISUAL_ANALYSIS_VERSION):
    return {"承办律师":"虚构乙", "_field_normalization_version":STRICT_EVIDENCE_VERSION,
        "_agent_summary":{"visual":True,"model":"deepseek-flash","workflow":"document_two_stage",
                          "analysis_version":version}}


def row(number, sha=None):
    return {"file_id":str(number),"path":f"fictional-{number}.pdf","filename":f"fictional-{number}.pdf",
            "sha256":sha or str(number),"pages":1,"doc_type":"default"}


def run(previous, old_rows, current, manual, issues, monkeypatch):
    profile={"processing_mode":"deepseek_cloud","model":"deepseek-flash","workflow":"document_two_stage"}
    parent=SimpleNamespace(id=1,case_id="fictional",source_manifest=old_rows,
                           manual_fields=manual,issues=issues,execution_profile=profile)
    task=SimpleNamespace(source_manifest=current,execution_profile=profile)
    files=[SimpleNamespace(id=x["file_id"],abs_path=x["path"],doc_type=x["doc_type"]) for x in current]
    calls=[]
    def analyze(case_type, *, sources, **kwargs):
        calls.append([x.path for x in sources])
        return fixture_analysis(sources[0].path,visual_fields())
    monkeypatch.setattr(workflow,"snapshot_exists",lambda *_:True)
    monkeypatch.setattr(workflow,"load_analysis",lambda *_:(copy.deepcopy(previous),{}))
    engine=SimpleNamespace(analyze_archive=analyze,compute_found_seqs=ap.compute_found_seqs,
                           compute_missing_items=ap.compute_missing_items)
    result, _, conflicts=workflow.analyze_with_parent(engine,task,parent,files,
        {"workflow_case_type":"civil","extraction":{"mode":"visual_agent"},
         "vision":{"model":"deepseek-flash","workflow":"document_two_stage"}},"fictional-org",lambda _:None)
    return result, conflicts, calls


@pytest.mark.parametrize("version",[None,"visual-analysis-v1",VISUAL_ANALYSIS_VERSION])
def test_visual_classifier_version_controls_actual_analysis_scope(monkeypatch, version):
    previous=fixture_analysis(row(1)["path"],visual_fields(version))
    _,_,calls=run(previous,[row(1)],[row(1),row(2)],{},[],monkeypatch)
    assert calls == ([[row(2)["path"]]] if version==VISUAL_ANALYSIS_VERSION else [[row(1)["path"],row(2)["path"]]])


@pytest.mark.parametrize("changed",["replaced","removed","algorithm"])
def test_reanalysis_does_not_reuse_ack_for_equal_values_from_new_evidence(monkeypatch, changed):
    previous=fixture_analysis(row(1)["path"],visual_fields())
    manual={"承办律师":"虚构甲"}
    old_conflicts=workflow.merge_manual_fields(previous,manual)
    assert len(old_conflicts)==1
    old_id=old_conflicts[0]["id"]
    manual["_issue_decisions"]={old_id:{"action":"acknowledged","reason":"仅核对过旧材料的这一冲突"}}
    previous.fields["_issue_decisions"]=copy.deepcopy(manual["_issue_decisions"])
    old_rows=[row(1),row(2)] if changed=="removed" else [row(1)]
    current=[row(1,"new-bytes")] if changed=="replaced" else [row(1)]
    if changed=="algorithm":
        previous.fields["_agent_summary"]["analysis_version"]="visual-analysis-v1"
    result,conflicts,calls=run(previous,old_rows,current,manual,old_conflicts,monkeypatch)
    assert calls == [[x["path"] for x in current]]  # It really reanalyzed, not additions reuse.
    assert result.fields["承办律师"]=="虚构甲"  # Explicit human value stays.
    assert len(conflicts)==1  # A fix may bind the new ID to its evidence generation.
    assert conflicts[0]["detail"]["field"]=="承办律师"
    unresolved=workflow.unresolved_issues(conflicts,result.fields)
    assert len(unresolved)==1, {"change":changed,"fresh_conflict_count":len(conflicts),
        "old_ack_survived":old_id in result.fields.get("_issue_decisions",{}),
        "unresolved_count":len(unresolved)}
