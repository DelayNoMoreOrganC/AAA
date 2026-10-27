"""Fictional title evidence. No customer data or cloud requests."""
from collections import Counter
from copy import deepcopy

import pytest

from document_title_review import title_evidence, review_visual_titles
from visual_archive_agent import _catalog_seq
from tests.test_visual_document_workflow import pdf, mock_client, classified, extracted, run, coverage, offline_only


NOTICE = "委托代理通知书\n虚构星河律师事务所：\n根据法律服务合作协议，现委托贵所代理虚构事项，请贵所办理代理手续。\n律师费按约定结算。"

@pytest.mark.parametrize('procedure',['简易','普通','小额诉讼'])
def test_acceptance_notice_current_trial_sentence_without_repeating_acceptance(procedure):
    text=f'虚构区人民法院\n受理案件通知书\n(2026)虚0101民初103号\n虚构公司：\n你单位起诉至本院。本院依法适用{procedure}程序对本案进行审理，现将有关事项通知如下。'
    evidence=title_evidence(text,case_type='civil')
    assert evidence['verified'] is True
    assert evidence['document_role']=='case_acceptance_notice'
    assert evidence['doc_type']=='acceptance_notice'  # User-approved placement; still not a pleading.
    assert evidence['procedure_stage']=='trial'

@pytest.mark.parametrize('body',[
    '本院拟适用简易程序对本案进行审理。',
    '如本院依法适用简易程序对本案进行审理，请另行通知。',
    '另案文字：“本院依法适用简易程序对本案进行审理。”',
    '本院未适用简易程序对本案进行审理。',
])
def test_acceptance_notice_current_trial_alternative_rejects_nonassertions(body):
    text='虚构区人民法院\n受理案件通知书\n(2026)虚0101民初103号\n'+body
    assert title_evidence(text,case_type='civil')['verified'] is False

def test_acceptance_notice_current_trial_alternative_needs_header_and_number():
    body='本院依法适用简易程序对本案进行审理。'
    assert title_evidence('受理案件通知书\n(2026)虚0101民初103号\n'+body)['verified'] is False
    assert title_evidence('虚构区人民法院\n受理案件通知书\n'+body)['verified'] is False


@pytest.mark.parametrize("title",["委托代理通知书","委 托 代 理 通 知 书","委托代理\n通知书"])
def test_notice_has_independent_type_with_strong_heading_and_engagement_context(title):
    result=title_evidence(NOTICE.replace("委托代理通知书",title))
    assert result["doc_type"] == "agency_notice"
    assert result["title"] == "委托代理通知书"
    assert _catalog_seq("civil",result["doc_type"]) == 3
    assert _catalog_seq("admin",result["doc_type"]) == 3
    assert _catalog_seq("arbitration",result["doc_type"]) == 3
    assert _catalog_seq("nonlit",result["doc_type"]) == 2


@pytest.mark.parametrize("text,kind",[
    ("借款合同\n借款人与贷款人引用《委托代理通知书》，不构成委托贵所代理的材料。","evidence"),
    ("授权委托书\n委托律师事务所代理诉讼，附《委托代理通知书》。","poa"),
    ("民事起诉状\n事实理由：依据《委托代理通知书》委托贵所办理，律师费如下。","complaint"),
    ("证据目录\n委托代理通知书\n虚构律师事务所\n请贵所代理案件，律师费另行结算。","evidence"),
    ("证据一\n委托代理通知书\n虚构律师事务所\n请贵所代理案件。","evidence"),
    ("委托代理合同\n虚构律师事务所与虚构委托人签订合同。","contract"),
    ("委托代理通知书\n本页只有引用目录，没有独立委托对象和事项。","unknown"),
])
def test_competing_headings_and_unverified_notice_do_not_become_contract(text,kind):
    assert title_evidence(text)["doc_type"] == kind


@pytest.mark.parametrize("text",[
    "事实与理由：原告根据委托代理通知书，委托贵所办理。",
    "关于《委托代理通知书》的说明\n请贵所核对律师费。",
    "《委托代理通知书》\n委托贵所代理，律师费按约定。",
])
def test_body_reference_is_not_a_standalone_title(text):
    assert title_evidence(text) is None


class FakePages:
    def __init__(self,texts):
        self.pages={f"p{i+1}":("fictional.pdf",i) for i in range(len(texts))}
        self.texts=dict(zip(self.pages,texts));self.reads=[]
    def read(self,key): self.reads.append(key);return self.texts[key]


def row(key,start=False,kind="unknown",title=""):
    return {"page_id":key,"document_start":start,"doc_type":kind,"confidence":.9,
            "document_role":"unknown" if kind=="unknown" else "standard",
            "procedure_stage":"unknown","title":title}


def test_review_corrects_type_and_preserves_continuations_and_fact_boundary():
    pages=FakePages([NOTICE,"律师费支付方式继续约定。","请贵所及时办理，特此通知。",
                     "授权委托书\n委托人为虚构主体。"])
    rows=[row("p1",True,title="委托代理通知书"),row("p2"),row("p3"),row("p4",True,"poa")]
    original=deepcopy(rows)
    actual,audit=review_visual_titles(rows,pages)
    assert rows==original
    assert [r["doc_type"] for r in actual]==["agency_notice"]*3+["poa"]
    assert [r["document_start"] for r in actual]==[True,False,False,True]
    assert audit[0]["page"]==1 and audit[0]["source_path"]=="fictional.pdf"
    assert audit[0]["contract_presence_confirmed"] is False
    assert audit[0]["visual_doc_type"]=="unknown"
    assert not any("律师费" in str(entry) for entry in audit)


@pytest.mark.parametrize("tail,expected",[("授权委托书\n虚构授权内容。","poa"),
    ("民事起诉状\n诉讼请求：虚构款项。","complaint"),
    ("借款合同\n借款人向虚构银行贷款。","evidence")])
def test_notice_run_cannot_swallow_an_independent_new_heading(tail,expected):
    pages=FakePages([NOTICE,"律师费结算续页。",tail,"下一页延续相同文书。"])
    actual,_=review_visual_titles([row("p1",True),row("p2"),row("p3"),row("p4")],pages)
    assert [(r["doc_type"],r["document_start"]) for r in actual]==[
        ("agency_notice",True),("agency_notice",False),(expected,True),(expected,False)]
    assert Counter(r["page_id"] for r in actual)==Counter(pages.pages.keys())


def test_model_notice_claim_without_local_title_is_not_promoted_to_contract():
    pages=FakePages(["仅有普通事实说明，没有文书标题。"])
    actual,audit=review_visual_titles([row("p1",True,"agency_notice")],pages)
    assert actual[0]["doc_type"]=="unknown" and actual[0]["confidence"]==.5
    assert audit[0]["reason_code"]=="agency_notice_title_unverified"


def test_notice_number_is_not_evidence_of_an_engagement_contract_number():
    from fact_evidence import validate_fact
    page = NOTICE + "\n编号：2026-001"
    assert title_evidence(page)["doc_type"] == "agency_notice"
    assert not validate_fact("合同号", "2026-001", "编号：2026-001", page)


@pytest.mark.parametrize("heading", ["执行申请书", "申请执行书", "强制执行申请书", "申请强制执行书", "执行裁定书", "执 行 裁 定 书", "执行\n裁定书"])
def test_standalone_execution_headings_override_unknown_without_outcome_inference(heading):
    text = "虚构市人民法院\n" + heading + "\n本页为虚构材料，不表明款项已履行。"
    evidence = title_evidence(text)
    assert evidence["doc_type"] == "execution"
    pages = FakePages([text, "本份执行材料的续页。"])
    actual, audit = review_visual_titles([row("p1", True), row("p2")], pages)
    assert [item["doc_type"] for item in actual] == ["execution", "execution"]
    assert [item["document_start"] for item in actual] == [True, False]
    assert all(item["procedure_stage"] == "enforcement" for item in actual)
    assert _catalog_seq("civil", "execution") == 15
    assert _catalog_seq("admin", "execution") == 15
    assert audit[0]["reason_code"] == "execution_title_verified"


@pytest.mark.parametrize("text", [
    "民事判决书\n不按期履行的，权利人可申请执行。",
    "民事判决书\n执行申请书\n正文引用拟提交材料。",
    "起诉状\n诉讼请求中引用执行裁定书。",
    "借款合同\n执行裁定书\n这是业务合同内的材料引用。",
    "证据目录\n执行申请书\n证明事项。",
    "证据一\n执行裁定书\n附件名称。",
    "申请执行前应当准备以下材料\n执行申请书\n身份证明。",
    "关于《执行裁定书》的说明\n仅陈述其他程序。",
    "《执行申请书》\n仅是一个材料引用。",
    "判决正文指出可以申请执行，不代表已经提出执行申请。",
])
def test_execution_references_and_body_words_do_not_promote_unknown(text):
    evidence = title_evidence(text)
    assert evidence is None or evidence["doc_type"] != "execution"
    actual, _ = review_visual_titles([row("p1", True)], FakePages([text]))
    assert actual[0]["doc_type"] != "execution"


def test_execution_continuation_cannot_swallow_a_new_complaint():
    pages = FakePages(["执行申请书\n申请执行人：虚构申请主体。", "执行申请附件说明。", "民事起诉状\n虚构诉讼请求。"])
    actual, _ = review_visual_titles([row("p1", True), row("p2"), row("p3")], pages)
    assert [(item["doc_type"], item["document_start"]) for item in actual] == [
        ("execution", True), ("execution", False), ("complaint", True)]
    assert Counter(item["page_id"] for item in actual) == Counter(pages.pages.keys())


def test_execution_heading_without_case_or_court_context_remains_unverified():
    actual, audit = review_visual_titles([row("p1", True)], FakePages(["执行申请书\n仅有标题的目录占位项。"]))
    assert actual[0]["doc_type"] == "unknown"
    assert actual[0]["confidence"] == .5
    assert audit[0]["reason_code"] == "execution_context_unverified"


@pytest.mark.parametrize("heading,number,body", [
    ("财产保全情况告知书", "(2026)虚0101执保101号", "本院已依法冻结被申请人的银行存款。"),
    ("财产保全\n情况告知书", "(2026)虚0101民初102号", "本院根据申请，已对涉案财产采取保全措施。"),
    ("保全情况告知书", "", "保全结果：查封被申请人名下财产。"),
    ("财产保全告知书", "", "本案已解除此前采取的财产保全。"),
    ("财产保全情况告知书", "", "本院未发现可供保全的财产。"),
    ("财产保全情况告知书", "(2026)虚0101执保101号", "本院尚未对被申请人的财产采取保全措施。"),
    ("财产保全情况告知书", "", "本院未能采取财产保全措施。"),
])
def test_preservation_notices_need_actual_preservation_context(heading, number, body):
    evidence = title_evidence(f"虚构区人民法院\n{heading}\n{number}\n{body}")
    assert evidence["verified"] and evidence["doc_type"] == "preservation"
    assert evidence["procedure_stage"] == "trial"
    assert _catalog_seq("civil", evidence["doc_type"]) == 8
    assert _catalog_seq("admin", evidence["doc_type"]) == 8


@pytest.mark.parametrize("number,body", [
    ("(2026)虚0101执保101号", "请查看通知内容。"),
    ("", "申请人请求本院查封被申请人的财产。"),
    ("", "本院拟查封被申请人的财产。"),
    ("", "若本院查封被申请人的财产，请另行通知。"),
    ("", "另案材料摘录。本院已冻结被申请人的存款。"),
    ("(2026)虚0101执101号", "本院已冻结被申请人的存款。"),
    ("", "本案不属于保全事项。本院已查封财产。"),
])
def test_unproved_or_conflicting_preservation_notice_remains_reviewable_even_if_model_called_it_preservation(number, body):
    pages = FakePages([f"虚构区人民法院\n财产保全情况告知书\n{number}\n{body}"])
    actual, audit = review_visual_titles([row("p1", True, "preservation")], pages)
    assert actual[0]["doc_type"] == "unknown" and actual[0]["confidence"] == .5
    assert audit[0]["independent_title_verified"] is False


@pytest.mark.parametrize("heading,number,body", [
    ("结案通知书", "(2026)虚0101执101号", "本案现予结案。"),
    ("结案\n通知书", "(2026)虚0101执恢102号", "本案现已结案。"),
    ("执行结案通知书", "", "本案已经执行完毕，现通知双方。"),
    ("执行案件结案通知书", "", "本院决定终结本次执行程序。"),
    ("结案通知书", "", "本案尚未足额受偿，现终结本次执行程序。"),
    ("结案通知书", "(2026)虚0101执101号", "本案尚未执行完毕，现终结本次执行程序。"),
    ("结案通知书", "(2026)虚0101执101号", "本案未能全部执行完毕。"),
])
def test_closure_notice_enters_execution_only_with_primary_number_or_current_execution_closure(heading, number, body):
    evidence = title_evidence(f"虚构区人民法院\n{heading}\n{number}\n{body}")
    assert evidence["verified"] and evidence["doc_type"] == "execution"
    assert evidence["procedure_stage"] == "enforcement"
    assert _catalog_seq("civil", evidence["doc_type"]) == 15
    assert _catalog_seq("admin", evidence["doc_type"]) == 15
    assert "已履行" not in str(evidence) and "受偿" not in str(evidence)


@pytest.mark.parametrize("number,body", [
    ("", "本案诉讼现已审结，特此通知。"),
    ("(2026)虚0101民初101号", "本案现已执行完毕。"),
    ("(2026)虚0101执保101号", "本案现予结案。"),
    ("", "若本案执行完毕，另行通知。"),
    ("", "申请人请求本院终结本次执行程序。"),
    ("", "本案尚未执行完毕。"),
    ("", "本案未能全部执行完毕。"),
    ("(2026)虚0101执101号", "另案执行结案材料供参考。"),
    ("(2026)虚0101执101号", "本案不属于执行案件。"),
    ("", "本案拟结束执行程序。"),
    ("", "本院已执行完毕；本案尚未执行完毕。"),
])
def test_generic_closure_notice_does_not_confirm_execution_from_claims_references_or_conflicts(number, body):
    pages = FakePages([f"虚构区人民法院\n结案通知书\n{number}\n{body}"])
    actual, audit = review_visual_titles([row("p1", True, "execution")], pages)
    assert actual[0]["doc_type"] == "unknown" and actual[0]["confidence"] == .5
    assert audit[0]["independent_title_verified"] is False


def test_new_notice_types_preserve_continuations_and_do_not_claim_an_unrelated_acceptance_or_lawyer_letter():
    pages = FakePages([
        "虚构区人民法院\n财产保全情况告知书\n(2026)虚0101执保101号\n本院已冻结被申请人的存款。",
        "同份保全告知的附表续页。",
        "虚构区人民法院\n结案通知书\n(2026)虚0101执102号\n本案现予结案。",
        "虚构区人民法院\n结案通知书\n(2026)虚0101执102号\n续页，第2页。",
        "虚构区人民法院\n受理案件通知书\n(2026)虚0101民初103号\n本院已受理本案。",
        "律师函\n虚构律师事务所发函，要求依法履约。",
    ])
    original = [row("p1", True), row("p2"), row("p3"), row("p4"), row("p5", True), row("p6", True)]
    actual, audit = review_visual_titles(original, pages)
    assert [(item["doc_type"], item["document_start"]) for item in actual] == [
        ("preservation", True), ("preservation", False), ("execution", True), ("execution", False),
        ("unknown", True), ("unknown", True)]
    assert Counter(item["page_id"] for item in actual) == Counter(pages.pages.keys())
    assert all(token not in str(audit) for token in ("执保101号", "执102号", "依法履约", "冻结被申请人"))


@pytest.mark.parametrize("title", ["财产保全情况告知书", "结案通知书"])
def test_new_notice_title_references_inside_other_material_never_change_its_type(title):
    for prefix, expected in [("证据目录", "evidence"), ("借款合同", "evidence"), ("民事起诉状", "complaint")]:
        text = f"{prefix}\n{title}\n原告请求本院冻结财产，并参考另案执行结束的材料。"
        assert title_evidence(text)["doc_type"] == expected
    assert title_evidence(f"关于《{title}》的说明\n仅引用文书名称。") is None


def test_visual_workflow_maps_negative_preservation_and_execution_closure_without_inventing_success_facts(tmp_path, monkeypatch):
    source = pdf(tmp_path, 4, texts=[
        "虚构区人民法院\n财产保全情况告知书\n(2026)虚0101执保101号\n本院未发现可供保全的财产。",
        "本份告知书附表续页。",
        "虚构区人民法院\n结案通知书\n(2026)虚0101执102号\n本案尚未足额受偿，现终结本次执行程序。",
        "本份执行结案通知续页。",
    ])
    mock_client(monkeypatch, lambda ctx, *_: extracted(ctx) if ctx["phase"] == "fields"
                else classified(ctx, kind="unknown", role="unknown", stage="unknown"))
    units, fields, metadata, _ = run([source], title_review_budget=24)
    assert [(unit.doc_type, unit.catalog_seq, unit.start_page, unit.end_page) for unit in units] == [
        ("preservation", 8, 0, 1), ("execution", 15, 2, 3)]
    assert fields == {}
    assert coverage(units) == Counter((source.path, i) for i in range(4))
    assert {item["reason_code"] for item in metadata["_visual_classification_review"]} == {
        "preservation_notice_verified", "execution_closure_notice_verified"}


def test_full_visual_unknown_execution_maps_to_execution_slot_without_new_facts(tmp_path, monkeypatch):
    source = pdf(tmp_path, 2, texts=["执行裁定书\n虚构法院作出程序裁定。", "同份裁定书续页。"])
    def respond(ctx, *_):
        return extracted(ctx) if ctx["phase"] == "fields" else classified(ctx, kind="unknown", role="unknown", stage="unknown")
    mock_client(monkeypatch, respond)
    units, fields, metadata, _ = run([source], title_review_budget=24)
    assert [(unit.doc_type, unit.catalog_seq, unit.start_page, unit.end_page) for unit in units] == [("execution", 15, 0, 1)]
    assert fields == {}
    assert coverage(units) == Counter((source.path, i) for i in range(2))
    assert metadata["_visual_classification_review"][0]["reason_code"] == "execution_title_verified"


def test_full_visual_workflow_places_notice_in_contract_slot_without_contract_fact(tmp_path,monkeypatch):
    source=pdf(tmp_path,4,texts=[NOTICE,"律师费结算续页，仍属于同一虚构通知。",
        "请贵所及时办理，特此通知。","授权委托书\n委托虚构律师代理。"])
    def respond(ctx,*_):
        if ctx["phase"]=="fields":return extracted(ctx)
        action=classified(ctx,kind="unknown",role="unknown",stage="unknown")
        action["pages"][0]["title"]="委托代理通知书"
        action["pages"][3].update(doc_type="poa",document_start=True,document_role="standard",procedure_stage="engagement")
        return action
    mock_client(monkeypatch,respond)
    units,fields,metadata,_=run([source], title_review_budget=24)
    assert [(u.doc_type,u.catalog_seq,u.start_page,u.end_page) for u in units]==[
        ("agency_notice",3,0,2),("poa",4,3,3)]
    assert fields == {}  # Mapping never creates a contract number/signature fact.
    assert coverage(units)==Counter((source.path,i) for i in range(4))
    evidence=metadata["_visual_classification_review"][0]
    assert evidence["contract_presence_confirmed"] is False
    assert evidence["method"]=="local_title_context_review"


def test_notice_mapping_is_used_by_found_and_actual_merger_not_old_unknown_slot(tmp_path):
    import fitz
    import archive_catalog as ac
    import archive_pipeline as ap
    from pdf_doc_locator import DocumentUnit
    source=pdf(tmp_path,1,texts=[NOTICE])
    unit=DocumentUnit(0,"agency_notice",0,0,"委托代理通知书",3,source.path,confidence=.9)
    catalog=ac.get_catalog("civil")
    found=ap.compute_found_seqs(catalog,[unit],{})
    assert 3 in found and 7 not in found
    analysis=ap.ArchiveAnalysis("civil",source.path,{}, {},[unit],found,[],source_paths=[source.path])
    output=str(tmp_path/"synthetic-result.pdf")
    result=ap.assemble_archive(analysis,output_pdf=output,config={"archive":{"order_mode":"catalog"},"output":{"preview_only":True}},skipped=[],log=lambda _:None)
    assert result.success and result.original_pages_included==1
    with fitz.open(output) as merged:
        titles=[entry[1] for entry in merged.get_toc()]
        assert any("委托代理合同" in title for title in titles)


def test_fictional_per_type_evaluation_is_not_real_model_accuracy():
    from scripts.evaluate_document_title_review import evaluate
    report = evaluate()
    assert report["not_actual_model_accuracy"] is True
    assert report["model_calls"] == report["ocr_calls"] == 0
    assert report["passed"] == report["total"], report["failed_cases"]
    assert len(report["by_category"]) >= 10


def test_default_budget_limits_new_reads_and_reuses_cached_pages():
    pages = FakePages(["借款合同\n虚构业务条款。"] * 6)
    pages.read_pages = {"p1", "p2", "p3"}
    original = [row(key, True, "evidence") for key in pages.pages]
    actual, _ = review_visual_titles(original, pages, max_new_reads=2)
    assert len(pages.reads) == 5
    assert pages.title_review_metrics["new_page_reads"] == 2
    assert pages.title_review_metrics["cached_page_reads"] == 3
    assert pages.title_review_metrics["pages_not_independently_reviewed"] == 1
    assert actual[-1] == original[-1]


def test_zero_budget_does_not_read_or_claim_independent_verification():
    pages = FakePages(["虚构法院\n传票\n到庭时间另列。"])
    pages.read_pages = {"p1"}
    original = [row("p1", True, "evidence", "传票")]
    actual, audit = review_visual_titles(original, pages, max_new_reads=0)
    assert actual == original and not audit and not pages.reads
    assert pages.title_review_metrics["pages_reviewed"] == 0
    assert pages.title_review_metrics["pages_not_independently_reviewed"] == 1


@pytest.mark.parametrize("budget", [-1,129,True,1.5,"2",None])
def test_invalid_budgets_are_rejected_without_reads(budget):
    pages = FakePages(["虚构文字"])
    with pytest.raises(ValueError):
        review_visual_titles([row("p1", True)], pages, max_new_reads=budget)
    assert not pages.reads


def test_unknown_start_has_priority_over_normal_material_and_no_blanket_downgrade():
    pages = FakePages(["虚构法院\n民事判决书\n原告：虚构甲。", "申请执行书\n申请执行人：虚构甲。", "普通证据材料。"])
    original = [row("p1", True, "judgment"), row("p2", True), row("p3", True, "evidence")]
    actual, _ = review_visual_titles(original, pages, max_new_reads=1)
    assert pages.reads == ["p2"]
    assert actual[0] == original[0] and actual[2] == original[2]
    assert actual[1]["doc_type"] == "execution"


def test_continuation_heading_splits_hidden_document_but_preserves_repeated_heading():
    pages = FakePages(["借款合同\n虚构业务条款。", "普通条款续页。", "授权委托书\n委托虚构代理人。", "授权委托书\n委托虚构代理人，续页内容。"])
    actual, _ = review_visual_titles([row("p1",True,"evidence"),row("p2",False,"evidence"),row("p3",False,"evidence"),row("p4",False,"evidence")], pages)
    assert [(item["doc_type"],item["document_start"]) for item in actual] == [
        ("evidence",True),("evidence",False),("poa",True),("poa",False)]
    assert Counter(item["page_id"] for item in actual) == Counter(pages.pages.keys())


def test_same_title_different_primary_case_number_creates_new_document_boundary():
    pages = FakePages(["虚构区人民法院\n民事判决书\n(2026)虚0101民初1号\n原告：虚构甲。",
                       "虚构区人民法院\n民事判决书\n(2026)虚0101民初2号\n原告：虚构乙。"])
    actual, audit = review_visual_titles([row("p1",True,"judgment"),row("p2",False,"judgment")],pages)
    assert [item["document_start"] for item in actual] == [True,True]
    assert "民初1号" not in str(audit) and "民初2号" not in str(audit)


def test_failed_local_read_neither_leaks_body_nor_marks_page_verified():
    class FailedPages(FakePages):
        def read(self,key): raise RuntimeError("PRIVATE_SOURCE_BODY")
    pages = FailedPages(["unused"])
    actual, audit = review_visual_titles([row("p1",True)],pages)
    assert actual[0]["doc_type"] == "unknown"
    assert pages.title_review_metrics["read_failures"] == 1
    assert pages.title_review_metrics["pages_reviewed"] == 0
    assert "PRIVATE_SOURCE_BODY" not in str(audit)


def test_failed_local_read_keeps_a_specific_model_title_type_conflict_reviewable():
    class FailedPages(FakePages):
        def read(self, key): raise RuntimeError("PRIVATE_SOURCE_BODY")
    actual, audit = review_visual_titles([row("p1", True, "contract", "借款合同")], FailedPages(["unused"]))
    assert actual[0]["doc_type"] == "contract" and actual[0]["confidence"] == .5
    assert audit[0]["reason_code"] == "title_conflict_not_independently_reviewed"
    assert audit[0]["independent_title_verified"] is False
    assert "PRIVATE_SOURCE_BODY" not in str(audit)


def test_identical_heading_without_boundary_evidence_remains_reviewable():
    pages = FakePages(["授权委托书\n委托虚构甲代理。", "授权委托书\n委托虚构乙代理。"])
    actual, audit = review_visual_titles([row("p1", True, "poa"), row("p2", False, "poa")], pages)
    assert [item["document_start"] for item in actual] == [True, False]
    assert actual[1]["confidence"] == .5
    assert audit[-1]["reason_code"] == "repeated_heading_boundary_requires_review"
    assert Counter(item["page_id"] for item in actual) == Counter(pages.pages.keys())


def test_same_case_number_does_not_prove_two_same_title_rulings_are_one_document():
    text = "虚构区人民法院\n民事裁定书\n(2026)虚0101民初1号\n裁定如下：准许撤诉。"
    actual, audit = review_visual_titles([row("p1", True, "ruling"), row("p2", False, "ruling")], FakePages([text, text]))
    assert actual[1]["confidence"] == .5
    assert audit[-1]["reason_code"] == "repeated_heading_boundary_requires_review"


def test_default_budget_is_finite_even_with_many_unknown_starts():
    pages = FakePages(["普通虚构材料。"] * 30)
    original = [row(key, True) for key in pages.pages]
    actual, audit = review_visual_titles(original, pages)
    assert len(pages.reads) == 24
    assert pages.title_review_metrics["new_page_reads"] == 24
    assert pages.title_review_metrics["pages_not_independently_reviewed"] == 6
    assert actual == original and not audit


@pytest.mark.parametrize("budget", [-1, 129, True, "24"])
def test_workflow_rejects_invalid_title_budget_before_model_client_creation(monkeypatch, budget):
    import visual_archive_agent as agent
    from tests.test_visual_document_workflow import CONFIG
    config = deepcopy(CONFIG); config["vision"]["title_review_budget"] = budget
    monkeypatch.setattr(agent, "DeepSeekVisionClient", lambda *_: pytest.fail("must not create client"))
    with pytest.raises(agent.GlmVisionError, match="标题复核预算"):
        agent.analyze_visual_sources([], "civil", config, log=lambda _: None)


def test_default_workflow_reviews_authorized_titles_without_extra_model_request(tmp_path,monkeypatch):
    import visual_archive_agent as agent
    from tests.test_visual_document_workflow import CONFIG
    source = pdf(tmp_path,texts=["虚构区人民法院\n传票\n受传唤人：虚构主体。到庭时间另列。"])
    other = pdf(tmp_path,name="unrelated.pdf",texts=["PRIVATE_OTHER_CASE"])
    read_keys = []
    original_read = agent.CasePages.read
    def read(self,key):
        assert key in self.pages and self.pages[key][0] == source.path
        assert self.pages[key][0] != other.path
        read_keys.append(key)
        return original_read(self,key)
    monkeypatch.setattr(agent.CasePages,"read",read)
    client = mock_client(monkeypatch,lambda ctx,*_:classified(ctx) if ctx["phase"]=="classification" else extracted(ctx))
    config=deepcopy(CONFIG);config["vision"].pop("title_review_budget")
    units,fields,metadata,_=agent.analyze_visual_sources([source],"civil",config,log=lambda _:None)
    assert len(client.messages)==2  # Original classification + extraction only.
    assert units[0].doc_type=="summons" and units[0].catalog_seq==12 and not fields
    assert set(read_keys)=={"f1p1"}
    metrics=metadata["_agent_summary"]["this_run_metrics"]["title_review"]
    assert metrics["configured_budget"]==24 and metrics["verified_title_pages"]==1
    assert metrics["new_page_reads"]==1 and metrics["corrected_pages"]==1
