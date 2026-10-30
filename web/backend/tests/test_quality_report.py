from types import SimpleNamespace

import fitz

from app.services.quality_report import write_quality_report


def _fixture(tmp_path):
    source = tmp_path / "fictional.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((50, 50), "Fictional source")
        document.save(source)
    unit = SimpleNamespace(source_path=str(source), start_page=0, end_page=0, title="虚构材料", doc_type="evidence", catalog_seq=7)
    analysis = SimpleNamespace(case_type="civil", fields={"委托人": "虚构甲"}, missing_items=[], outcome_warnings=[], doc_spans=[unit])
    files = [SimpleNamespace(filename="虚构材料.pdf", abs_path=str(source))]
    return analysis, files, source


def test_quality_report_does_not_invent_pass_without_merger_result(tmp_path):
    analysis, files, source = _fixture(tmp_path)
    report = write_quality_report(tmp_path, analysis, files, source, "local", [])
    assert report["source_page_conservation"] == "not_verified"
    assert "未核验" in (tmp_path / "归档质检清单.html").read_text(encoding="utf-8")


def test_quality_report_exports_source_to_output_locations_and_local_links(tmp_path):
    analysis,files,source=_fixture(tmp_path)
    result={'success':True,'original_pages_included':1,'pagination':{'mode':'draft','body_start':0},
        'source_page_locations':[{'source_path':str(source),'source_page':1,'archive_page':1,'body_page':None,'doc_id':1,'catalog_seq':7}]}
    report=write_quality_report(tmp_path,analysis,files,source,'local',[],verification=result,draft=True)
    assert report['source_page_locations_version']=='source-pages-v1'
    row=report['source_page_locations'][0]
    assert row['source_index']==1 and row['source_page']==row['archive_page']==1
    assert 'source_path' not in row and row['body_page'] is None
    html=(tmp_path/'归档质检清单.html').read_text(encoding='utf-8')
    assert '#page=1' in html and '源页去向' in html


def test_verified_merge_records_provenance_and_unverified_rules(tmp_path):
    analysis, files, source = _fixture(tmp_path)
    result = SimpleNamespace(success=True, original_pages_included=1)
    report = write_quality_report(tmp_path, analysis, files, source, "local", [], verification=result)
    assert report["source_page_conservation"] == "passed"
    assert report["document_provenance"][0]["source_pages"] == [1, 1]
    assert report["document_provenance"][0]["source_anchor_valid"]
    assert report["delivery_classification"] == "draft"
    assert report["rule_readiness"]["formal_ready"] is False
    assert len(report["confirmed_values_sha256"]) == 64


def test_success_with_wrong_page_count_and_invalid_anchor_is_not_pass(tmp_path):
    analysis, files, source = _fixture(tmp_path)
    analysis.doc_spans[0].end_page = 5
    report = write_quality_report(tmp_path, analysis, files, source, "local", [], verification={"success": True, "original_pages_included": 0})
    assert report["source_page_conservation"] == "not_verified"
    assert report["document_provenance"][0]["source_anchor_valid"] is False


def test_quality_and_catalog_report_same_missing_contract_even_with_occupied_slot(tmp_path):
    from app.services.archive_rules import catalog_material_status
    analysis, files, source = _fixture(tmp_path)
    files[0].id = "fictional-file"
    files[0].filename = "虚构通知<script>.pdf"
    analysis.doc_spans[0].doc_type = "agency_notice"
    analysis.doc_spans[0].catalog_seq = 3
    analysis.doc_spans[0].confidence = .95
    analysis.found_seqs = {3}
    report = write_quality_report(tmp_path, analysis, files, source, "local", [], draft=True)
    material = next(item for item in report["material_completeness"]["checks"] if item["id"] == "material:contract")
    assert material["status"] == "missing" and not material["material_found"]
    assert material["related_sources"][0]["page"] == 1
    catalog = catalog_material_status(analysis, source_manifest=[{"file_id":files[0].id,"filename":files[0].filename,"path":str(source),"pages":1}])
    assert next(item for item in catalog if item["seq"] == 3)["material_checks"][0] == material
    rendered = (tmp_path / "归档质检清单.html").read_text(encoding="utf-8")
    assert "委托代理通知书不能证明委托合同已提供或签署" in rendered
    assert "第 1—1 页" in rendered
    assert "<script>" not in rendered and "&lt;script&gt;" in rendered
    assert report["delivery_classification"] == "draft"
    assert not report["material_completeness"]["formal_ready"]


def test_manual_classification_audit_records_effective_destination_without_internal_ids(tmp_path):
    import hashlib
    import json
    from app.services.document_classification import indexed_units
    analysis, files, source = _fixture(tmp_path)
    files[0].id = "fictional-internal-file-id"
    manifest = [{"file_id":files[0].id,"path":str(source),"sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"pages":1}]
    key = next(iter(indexed_units(analysis, manifest)))
    unit = analysis.doc_spans[0]
    unit.manual_catalog_seq = 7
    analysis.fields["_document_classifications"] = {key:{
        "file_id":files[0].id,"sha256":manifest[0]["sha256"],"actor_id":"fictional-internal-user-id",
        "start_page":0,"end_page":0,"original_doc_type":"judgment","original_catalog_seq":14,
        "doc_type":"evidence","catalog_seq":7,"reason":"虚构核对 <script>marker</script>",
        "edited_at":"2026-10-23T01:00:00Z","revision":2}}
    report = write_quality_report(tmp_path, analysis, files, source, "local", [])
    audit = report["document_classification_audit"]
    assert len(audit) == 1 and audit[0]["applied_to_current_volume"] is True
    assert audit[0]["source_pages"] == [1,1] and audit[0]["original_catalog_seq"] == 14
    assert "file_id" not in audit[0] and "sha256" not in audit[0] and "actor_id" not in audit[0]
    rendered = (tmp_path / "归档质检清单.html").read_text(encoding="utf-8")
    assert "已应用" in rendered and "&lt;script&gt;marker&lt;/script&gt;" in rendered
    assert "<script>" not in rendered and "fictional-internal-user-id" not in rendered
    unit.manual_catalog_seq = None
    report = write_quality_report(tmp_path, analysis, files, source, "local", [])
    assert report["document_classification_audit"][0]["applied_to_current_volume"] is False
