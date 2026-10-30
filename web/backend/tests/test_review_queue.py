"""Fictional review anchors; grouping never acknowledges business issues."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.services.review_queue import build_review_queue


def task(issues=(), catalog=(), fields=None):
    return SimpleNamespace(issues=list(issues), catalog_status=list(catalog), fields=fields or {},
        source_manifest=[{"file_id": "a", "filename": "虚构材料.pdf", "path": "fictional-a.pdf", "pages": 6},
                         {"file_id": "b", "filename": "虚构补件.pdf", "path": "fictional-b.pdf", "pages": 3}])


def issue(id, kind="field_conflict", **detail):
    return {"id": id, "kind": kind, "message": "虚构待核原因 " + id, "detail": detail, "blocking": True}


def test_same_field_groups_preserve_all_decisions_reasons_and_current_sources():
    value = task([issue("one", field="委托人", file_id="a", page=1), issue("two", field="委托人", file_id="b", page=2)],
        fields={"_issue_decisions": {"one": {"action": "acknowledged", "reason": "已核第一项"}}})
    before = deepcopy(value.__dict__)
    queue = build_review_queue(value)
    assert len(queue) == 1 and queue[0]["issue_ids"] == ["one", "two"]
    assert len(queue[0]["reasons"]) == 2 and len(queue[0]["sources"]) == 2
    assert queue[0]["field_targets"][0] == {"template_name": "立案审批表", "field": "委托人"}
    assert value.__dict__ == before  # Presentation does not acknowledge the second issue.


def test_distinct_case_number_fields_do_not_merge_because_they_share_a_form_slot():
    queue = build_review_queue(task([issue("one", field="案号"), issue("two", field="法院收案号")]))
    assert len(queue) == 2 and queue[0]["field"] != queue[1]["field"]
    assert any(target["field"] == "法院收案号" for target in queue[0]["field_targets"])


def test_exact_source_spans_group_ocr_and_classification_but_overlaps_stay_separate():
    queue = build_review_queue(task([
        issue("ocr", "ocr", file_id="a", page=2),
        issue("classification", "classification", file_id="a", page=2, page_start=2, page_end=2),
        issue("longer", "classification", file_id="a", page=2, page_start=2, page_end=3),
        issue("other", "ocr", file_id="b", page=2),
    ]))
    assert len(queue) == 3
    assert queue[0]["issue_ids"] == ["ocr", "classification"]
    assert len(queue[0]["sources"]) == 1


def test_quality_pages_inside_one_document_share_classification_review_without_acknowledgement():
    value=task([issue('class','classification',file_id='a',page=2,page_start=2,page_end=4),
                issue('blur','ocr',file_id='a',page=3),issue('crossing','ocr',file_id='a',page=4,page_end=5)])
    before=deepcopy(value.__dict__);queue=build_review_queue(value)
    assert len(queue)==2 and queue[0]['issue_ids']==['class','blur']
    assert len(queue[0]['reasons'])==2 and value.__dict__==before


@pytest.mark.parametrize("reference", [
    {"file_id": "other-case", "source_path": "fictional-a.pdf", "page": 1},
    {"file_id": "a", "source_path": "fictional-b.pdf", "page": 1},
    {"file_id": "a", "page": 0}, {"file_id": "a", "page": 7}, {"file_id": "a", "page": True},
    {"source_path": "private-other-case.pdf", "page": 1},
])
def test_queue_rejects_stale_out_of_range_or_cross_case_anchors(reference):
    queue = build_review_queue(task([issue("one", "ocr", **reference)]))
    assert queue[0]["sources"] == []
    assert "source_path" not in json.dumps(queue) and "private-other" not in json.dumps(queue)


def test_missing_material_never_coalesces_with_related_source_issue_or_gains_verified_necessity():
    queue = build_review_queue(task([issue("one", field="合同号")], catalog=[
        {"seq": 3, "name": "委托代理合同", "found": False, "requirement": "required", "legal_requirement_verified": False},
        {"seq": 4, "name": "授权材料", "found": False, "requirement": "required", "legal_requirement_verified": True},
        {"seq": 7, "name": "证据", "found": True},
    ]))
    assert [row["kind"] for row in queue] == ["missing", "issue", "missing"]
    assert queue[0]["blocking"] and not queue[2]["blocking"]
    assert queue[2]["catalog_seqs"] == [3] and queue[2]["issue_ids"] == []


def test_nonblocking_rejections_remain_advisory_in_original_issues_and_queue_keys_are_stable():
    value = task([issue("one", field="委托人"), dict(issue("advice", "fact_review"), blocking=False)])
    queue = build_review_queue(value)
    assert len(queue) == 1 and len(value.issues) == 2
    value.issues[0]["message"] = "说明更新但仍是同一字段"
    assert build_review_queue(value)[0]["key"] == queue[0]["key"]


def test_unique_field_source_and_quality_share_a_visit_but_not_a_resolution():
    # Metadata protocol only, not a fictional recognition benchmark.
    quality=issue('quality','ocr',file_id='a',page=2)
    conflict=issue('field',field='案号',source={'file_id':'a','page':2})
    value=task([quality,conflict]);before=deepcopy(value.__dict__)
    first=build_review_queue(value)
    assert len(first)==1 and first[0]['issue_ids']==['quality','field']
    assert first[0]['field']=='案号' and first[0]['field_targets']
    assert value.__dict__==before
    conflict['detail']['fact_resolved']=True
    after=build_review_queue(value)
    assert after[0]['key']==first[0]['key'] and len(after[0]['reasons'])==2
    assert quality['blocking'] and not value.fields.get('_issue_decisions')


def test_shared_page_cannot_select_between_two_field_conflicts():
    quality=issue('quality','ocr',file_id='a',page=2)
    value=task([quality,issue('one',field='案号',source={'file_id':'a','page':2}),
                issue('two',field='法院收案号',source={'file_id':'a','page':2})])
    assert len(build_review_queue(value))==3


def test_field_link_does_not_break_existing_classification_quality_group():
    value=task([issue('quality','ocr',file_id='a',page=2),
                issue('one',field='案号',source={'file_id':'a','page':2}),
                issue('class','classification',file_id='a',page=2,page_start=2,page_end=3)])
    grouped=build_review_queue(value)
    assert len(grouped)==2
    assert next(g for g in grouped if 'quality' in g['issue_ids'])['issue_ids']==['quality','class']


def test_stale_reference_hash_cannot_link_quality_to_a_field():
    value=task([issue('quality','ocr',file_id='a',page=2),
                issue('one',field='案号',source={'file_id':'a','page':2,'source_sha256':'0'*64})])
    value.source_manifest[0]['sha256']='1'*64
    grouped=build_review_queue(value)
    assert len(grouped)==2 and next(g for g in grouped if g['field'])['sources']==[]
