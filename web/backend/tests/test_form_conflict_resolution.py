"""Exact current decisions restore synthetic stage drafts; history stays intact."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services import archive_service
from app.services.analysis_snapshot import save_snapshot, load_snapshot_data
from app.services.task_workflow import issue
from app.services.task_sources import source_version
from app.services.field_decisions import prepare_accept_current, fact_conflict_resolved, FieldDecisionError
from app.services.original_template_service import _values
from app.core.v4_bridge import init_v4_path
from tests.test_task_workflow import fixture_analysis

init_v4_path()


CLIENT = "虚构星岚科技有限公司"
WORK = "2026年10月10日，虚构律师戊完成采购合同模板审查，向聘方发送修订意见。"
STATUS = "截至2026年10月20日，该顾问协议仍在履行，尚未终止；本说明不是终止协议。"


def fixture(tmp_path, conflict_field="委托人", wrong_client=False):
    path = str(tmp_path / "fictional-source.pdf")
    values = {"案件类别": "法律顾问", "委托人": CLIENT, "阶段工作情况": WORK, "顾问协议状态": STATUS}
    values["_provenance"] = {key: [{"method": "visual_agent_local_evidence", "value": value,
        "quote": value, "source_path": path, "page": 1, "subject": CLIENT}]
        for key, value in values.items() if key != "案件类别"}
    detail = {"field": conflict_field, "values": [values[conflict_field], "另一虚构候选"], "evidence_version": "synthetic-current"}
    values["_field_conflicts"] = [deepcopy(detail)]
    if wrong_client: values["委托人"] = "虚构另一个公司"
    analysis = fixture_analysis(path, values)
    analysis.case_type = "counsel"
    conflict = issue("field_conflict", "虚构来源冲突", detail=detail)
    manifest = [{"path": path, "pages": 1, "file_id": "synthetic"}]
    return analysis, manifest, conflict


def acknowledge(fields, item):
    fields.setdefault("_issue_decisions", {})[item["id"]] = {"action": "acknowledged", "reason": "已核对本次虚构来源"}


@pytest.mark.parametrize("field", ["委托人", "阶段工作情况", "顾问协议状态"])
def test_legacy_ack_is_history_not_an_explicit_choice_of_conflicting_facts(tmp_path, field):
    analysis, manifest, conflict = fixture(tmp_path, field)
    history = deepcopy(analysis.fields["_field_conflicts"])
    archive_service.refresh_form_drafts(analysis, {}, manifest, [conflict])
    assert not analysis.fields.get("结案小结")
    acknowledge(analysis.fields, conflict)
    fields = archive_service.refresh_form_drafts(analysis, {}, manifest, [conflict])
    assert not fields.get('结案小结')
    assert fields["_field_conflicts"] == history
    assert fields["_issue_decisions"][conflict["id"]]["action"] == "acknowledged"
    assert not _values("结案报告表", fields, "配置律所不得替代来源", {}).get('结案小结')
    assert not fields.get("结案日期") and not fields.get("已收业务费")
    assert archive_service.refresh_form_drafts(analysis, {}, manifest, [conflict]) == fields


def saved_task(tmp_path,analysis,manifest,conflict):
    manifest[0].update(sha256='a'*64,doc_type='default')
    version=source_version(manifest,analysis.case_type,'')
    work=tmp_path/'work'
    save_snapshot(str(work),analysis,base_name='synthetic',metadata={
        'source_version':version,'source_manifest':manifest,'revision':1,'case_stage':''})
    task=SimpleNamespace(id=101,case_id='synthetic',source_version=version,
        fields=analysis.fields,manual_fields={},source_manifest=manifest,issues=[conflict],revision=1,
        output_pdf='historical.pdf',artifacts={'valid':True},confirmation={'confirmed':True})
    return task,work


@pytest.mark.asyncio
@pytest.mark.parametrize('field',['委托人','阶段工作情况','顾问协议状态'])
async def test_source_bound_explicit_choice_restores_draft_and_keeps_original_conflict(tmp_path,monkeypatch,field):
    analysis,manifest,conflict=fixture(tmp_path,field)
    task,work=saved_task(tmp_path,analysis,manifest,conflict)
    history=deepcopy(task.fields['_field_conflicts'][0])
    monkeypatch.setattr(archive_service,'_work_dir_for',lambda *_:str(work))
    body={'field':field,'current_value':task.fields[field],'source_version':task.source_version,
          'expected_revision':task.revision,'request_id':'fictional-current-choice'}
    receipt,replay=prepare_accept_current(task,body,actor_id='tester',org_id='synthetic-org')
    assert not replay
    fields=await archive_service.update_task_fields(task,'synthetic-org',{field:task.fields[field]},
        actor_id='tester',accept_current=receipt)
    assert WORK in fields['结案小结'] and STATUS in fields['结案小结']
    current=fields['_field_conflicts'][0]
    assert all(current[key]==value for key,value in history.items())
    assert fact_conflict_resolved(task,current)
    assert prepare_accept_current(task,body,actor_id='tester',org_id='synthetic-org')[1] is True
    with pytest.raises(FieldDecisionError):
        prepare_accept_current(task,dict(body,request_id='new-request',current_value='changed'),actor_id='tester',org_id='synthetic-org')
    changed=await archive_service.update_task_fields(task,'synthetic-org',{'委托人':'不同虚构公司'},actor_id='tester')
    assert not changed.get('结案小结')
    assert changed[field]==('不同虚构公司' if field=='委托人' else body['current_value'])


@pytest.mark.asyncio
async def test_real_snapshot_field_update_acknowledges_identity_and_refreshes_stage(tmp_path, monkeypatch):
    analysis, manifest, conflict = fixture(tmp_path, wrong_client=True)
    before_history = deepcopy(analysis.fields["_field_conflicts"])
    task,work=saved_task(tmp_path,analysis,manifest,conflict)
    monkeypatch.setattr(archive_service, "_work_dir_for", lambda *_: str(work))
    fields = await archive_service.update_task_fields(task, "synthetic-org", {"委托人": CLIENT}, actor_id="tester")
    assert WORK in fields.get("结案小结", "") and STATUS in fields["结案小结"]
    assert all(fields['_field_conflicts'][0][key]==value for key,value in before_history[0].items())
    assert fact_conflict_resolved(task,fields['_field_conflicts'][0])
    assert fields == load_snapshot_data(str(work))["fields"] == task.fields
    assert task.manual_fields["委托人"] == CLIENT
    assert task.revision == 2 and task.confirmation is None and task.artifacts is None


@pytest.mark.parametrize("variant", ["new_version", "other_detail", "missing_current_issue", "empty_reason", "resolved_flag_only"])
def test_old_ack_or_human_value_cannot_hide_current_conflict(tmp_path, variant):
    analysis, manifest, conflict = fixture(tmp_path)
    acknowledge(analysis.fields, conflict)
    current = deepcopy(conflict)
    if variant == "new_version": current["detail"]["evidence_version"] = "synthetic-new-source"
    elif variant == "other_detail": current["detail"]["values"][1] = "不同虚构候选"
    elif variant == "empty_reason": analysis.fields["_issue_decisions"][conflict["id"]]["reason"] = " "
    elif variant == "resolved_flag_only":
        analysis.fields["_issue_decisions"] = {}
        current["detail"]["resolved"] = True
    if variant in ("new_version", "other_detail", "resolved_flag_only"):
        current = issue("field_conflict", current["message"], detail=current["detail"])
        analysis.fields["_field_conflicts"].append(deepcopy(current["detail"]))
    active = [] if variant == "missing_current_issue" else [conflict, current]
    result = archive_service.refresh_form_drafts(analysis, {"委托人": CLIENT}, manifest, active)
    assert not result.get("结案小结")
    assert result["委托人"] == CLIENT
    assert result["_field_conflicts"] == analysis.fields["_field_conflicts"]


def test_ack_does_not_allow_different_subject_or_override_manual_result_blank(tmp_path):
    analysis, manifest, conflict = fixture(tmp_path)
    acknowledge(analysis.fields, conflict)
    result = archive_service.refresh_form_drafts(analysis, {"委托人": "虚构另一主体"}, manifest, [conflict])
    assert not result.get("结案小结")
    result = archive_service.refresh_form_drafts(analysis, {"委托人": CLIENT, "结案小结": ""}, manifest, [conflict])
    assert result["结案小结"] == "" and result["_form_drafts"]["fields"]["结案小结"]["status"] == "human_modified"


def test_new_court_documents_reach_original_docx_without_service_or_native_render(tmp_path):
    from zipfile import ZipFile
    from lxml import etree
    from document_title_review import review_visual_titles
    from app.services.original_template_service import fill_original_docx
    path = str(tmp_path / "fictional.pdf")
    texts = ["虚构区人民法院\n财产保全情况告知书\n本院未发现可供保全的财产。",
             "虚构区人民法院\n执行结案通知书\n本案尚未足额受偿，现终结本次执行程序。"]
    pages = SimpleNamespace(pages={"p1": (path, 0), "p2": (path, 1)}, read=lambda key: texts[int(key[1:])-1])
    rows, audit = review_visual_titles([{"page_id":key, "document_start":True, "doc_type":"unknown",
        "confidence":.9, "document_role":"unknown", "procedure_stage":"unknown", "title":""}
        for key in pages.pages], pages)
    analysis = fixture_analysis(path, {"_visual_classification_review": audit})
    analysis.doc_spans = [SimpleNamespace(doc_id=i, doc_type=row["doc_type"], title=row["title"],
        source_path=path, start_page=i, end_page=i, confidence=row["confidence"]) for i,row in enumerate(rows)]
    fields = archive_service.refresh_form_drafts(analysis, {}, [{"path":path,"pages":2}])
    destination = tmp_path / "synthetic-delivery-form.docx"
    fill_original_docx("送达材料清单", fields, "虚构律所", destination)
    with ZipFile(destination) as package:
        tree = etree.fromstring(package.read("word/document.xml"))
    text = "".join(tree.xpath('//w:t/text()', namespaces={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}))
    assert "财产保全情况告知书" in text and "执行结案通知书" in text
    assert fields["_form_draft_sources"]["法院文件清单"][1]["page"] == 2
    assert not fields.get("结案小结") and not fields.get("结案日期")
