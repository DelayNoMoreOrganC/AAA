from copy import deepcopy

import pytest

from app.services.form_fill_audit import build_form_fill_audit, render_form_fill_audit


def row(rows, template, field):
    return next(item for item in rows if item['template'] == template and item['field'] == field)


@pytest.mark.parametrize('category,has_court,archive_row', [
    ('民事', True, 13), ('行政', True, 13), ('刑事', True, 13),
    ('非诉', False, 12), ('法律顾问', False, 12),
])
def test_uses_actual_original_form_positions_for_each_business(category, has_court, archive_row):
    rows = build_form_fill_audit({'案件类别': category}, [])
    assert len({r['template'] for r in rows}) == 5
    cover = [r for r in rows if r['template'] == '档案卷宗']
    assert any(r['field'] == '审理法院' for r in cover) is has_court
    assert row(rows, '档案卷宗', '档案号')['position']['physical_row'] == archive_row
    assert row(rows, '立案审批表', '传真')['position'] == {'table': 1, 'physical_row': 3, 'physical_cell': 4}


def test_actual_alias_and_source_survive_without_exporting_quotes_or_private_paths(tmp_path):
    path = str(tmp_path / 'private-source.pdf')
    fields = {'案号': '（2026）虚民初1号', '_provenance': {'案号': [
        {'method': 'local_agent', 'value': '（2026）虚民初1号', 'quote': '秘密原文 案号：（2026）虚民初1号',
         'source_path': path, 'page': 1}]}}
    manifest = [{'file_id': 'private-id', 'path': path, 'pages': 1, 'filename': '虚构.pdf'}]
    before = deepcopy(fields)
    item = row(build_form_fill_audit(fields, manifest), '档案卷宗', '法院收案号')
    assert item['value'] == fields['案号'] and item['status'] == 'source_supported'
    assert item['sources'] == [{'filename': '虚构.pdf', 'page': 1}]
    assert path not in str(item) and '秘密原文' not in str(item) and 'private-id' not in str(item)
    assert fields == before
    item = row(build_form_fill_audit(fields, []), '档案卷宗', '法院收案号')
    assert item['status'] == 'unverified' and item['sources'] == []


def test_human_blank_is_not_reported_as_missing_and_does_not_restore_alias():
    fields = {'法院收案号': '', '案号': '旧案号', '_provenance': {'法院收案号': [{'method': 'human', 'value': ''}]}}
    item = row(build_form_fill_audit(fields, []), '档案卷宗', '法院收案号')
    assert not item['value'] and item['status'] == 'human_confirmed'
    assert '人工留空' in item['reason']


def test_reading_a_conflict_does_not_make_exported_field_confirmed():
    issue = {'id': 'conflict', 'kind': 'field_conflict', 'detail': {'field': '委托人', 'saved': '虚构甲', 'new': '虚构乙'}}
    fields = {'委托人': '虚构甲', '_provenance': {'委托人': [{'method': 'human', 'value': '虚构甲'}]},
              '_field_conflicts': [issue['detail']], '_issue_decisions': {'conflict': {'action': 'acknowledged', 'reason': '已阅'}}}
    item = row(build_form_fill_audit(fields, [], issues=[issue]), '立案审批表', '委托人')
    assert item['status'] == 'conflict' and '不代表' in item['reason']


def test_capacity_not_missing_and_measured_page_count_not_business_evidence():
    fields = {'_form_drafts': {'fields': {'案情简介': {'status': 'insufficient', 'reason_codes': ['draft_too_long_for_original_cell']}}}}
    rows = build_form_fill_audit(fields, [], derived_output={'volume_page_count': 55})
    assert '容量' in row(rows, '立案审批表', '案情简介')['reason']
    count = row(rows, '档案卷宗', '卷内页数')
    assert count['value'] == '55 页' and count['status'] == 'output_measurement' and count['sources'] == []
    assert '实际收款' in row(rows, '结案报告表', '已收业务费')['reason']


def test_delivery_names_match_original_renderer_without_claiming_service():
    fields = {'法院文件清单': '判决书（原材料第3—4页）\n执行通知书（原材料第5页）'}
    item = row(build_form_fill_audit(fields, []), '送达材料清单', '法院文件清单')
    assert item['value'] == '判决书\n执行通知书'
    assert item['saved_value'] == fields['法院文件清单']
    assert item['status'] == 'unverified'


def test_manual_opinions_and_html_are_escaped_and_do_not_claim_approval():
    fields = {'_preview_custom_values': {'立案审批表': {'p0-b0-r6-c0': '<script>虚构意见</script>'}}}
    rows = build_form_fill_audit(fields, [])
    opinion = row(rows, '立案审批表', '承办律师意见')
    assert opinion['value'] == '<script>虚构意见</script>' and '不证明' in opinion['reason']
    rendered = render_form_fill_audit(rows)
    assert '<script>' not in rendered and '&lt;script&gt;虚构意见&lt;/script&gt;' in rendered
    assert '字段' in rendered and '实际送达' in rendered
