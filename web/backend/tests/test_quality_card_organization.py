"""Fictional case facts only; native DOCX, stub PDF conversion, real ASGI edits."""
from copy import deepcopy
from zipfile import ZipFile

import pytest
from lxml import etree as ET
from sqlalchemy import select

from app.models import ArchiveTask, CaseFile, TaskStatus
from app.services import original_template_service as original
from app.services.analysis_snapshot import save_snapshot, load_analysis, task_work_dir
from app.services.preview_fields import build_preview, sanitize_preview_updates
from app.services.browser_pdf_service import render_form_html
from app.services.task_sources import build_source_manifest, source_version
from tests.test_file_import_api import upload_context, upload
from tests.test_task_workflow import fixture_analysis, wire_storage


def firm_cell(path):
    with ZipFile(path) as package:
        root = ET.fromstring(package.read('word/document.xml'))
    table = root.find('.//' + original._tag('body') + '/' + original._tag('tbl'))
    return table.findall(original._tag('tr'))[0].findall(original._tag('tc'))[1]


@pytest.mark.parametrize('fields,expected,status', [
    ({'律师事务所':'虚构来源律所'}, '虚构来源律所', 'unverified'),
    ({'律师事务所':'虚构人工律所','_provenance':{'律师事务所':[{'method':'human','value':'虚构人工律所'}]}}, '虚构人工律所','human_confirmed'),
    ({}, '', 'missing'),
    ({'律师事务所':'','_provenance':{'律师事务所':[{'method':'human','value':''}]}}, '', 'human_confirmed'),
])
def test_case_firm_not_account_setting_controls_native_docx_pdf_and_preview(tmp_path, monkeypatch, fields, expected, status):
    before=deepcopy(fields)
    preview=build_preview('质量监督卡',fields)
    entry=next(x for x in preview['fields'] if x['key']=='律师事务所')
    assert entry['value']==expected and entry['assurance']['status']==status
    assert sanitize_preview_updates('质量监督卡',{'律师事务所':expected})=={'律师事务所':expected}
    docx=original.fill_original_docx('质量监督卡',fields,'虚构账号配置绝不入卷',tmp_path/'quality.docx')
    cell=firm_cell(docx)
    assert original._compact(''.join(cell.xpath('.//w:t/text()',namespaces=original.NS)))==expected
    assert cell.xpath('.//w:permStart',namespaces=original.NS), 'The case firm is a reviewable field.'
    seen={}
    def convert(path, output, **kwargs):
        seen.update(kwargs)
        assert original._compact(''.join(firm_cell(path).xpath('.//w:t/text()',namespaces=original.NS)))==expected
        return str(output)
    monkeypatch.setattr(original,'convert_docx_to_pdf',convert)
    original.render_original_pdf('质量监督卡',fields,'虚构账号配置绝不入卷',tmp_path/'quality.pdf')
    assert seen['field_texts']['律师事务所']==[expected]
    assert '虚构账号配置绝不入卷' not in str(seen)
    html=render_form_html('质量监督卡',fields,'虚构账号配置绝不入卷')
    assert '虚构账号配置绝不入卷' not in html
    if expected:assert expected in html
    assert fields==before


def test_source_label_requires_current_case_anchor_and_remains_pending_review(tmp_path):
    path=str(tmp_path/'fictional.pdf');value='虚构源律师事务所'
    fields={'律师事务所':value,'_provenance':{'律师事务所':[{'method':'visual_agent_local_evidence',
        'value':value,'quote':'受托方：'+value,'source_path':path,'page':1}]}}
    row=next(x for x in build_preview('质量监督卡',fields,source_manifest=[{'file_id':'fictional-file',
        'path':path,'pages':1}])['fields'] if x['key']=='律师事务所')
    assert row['assurance']['status']=='source_supported'
    assert row['assurance']['label']=='有原文依据，待核对'
    assert row['assurance']['anchors']==[{'file_id':'fictional-file','page':1}]


def test_firm_overflow_reports_editable_field_without_private_text(tmp_path):
    with pytest.raises(original.OriginalTemplateError) as exc:
        original.fill_original_docx('质量监督卡',{'律师事务所':'虚构'+('甲'*101)},'',tmp_path/'too-long.docx')
    assert exc.value.fields==['律师事务所'] and exc.value.code=='overflow'
    assert '甲' not in str(exc.value)


@pytest.mark.asyncio
async def test_quality_preview_uses_case_value_and_real_save_retains_manual_clear(upload_context,monkeypatch):
    ctx=upload_context;wire_storage(ctx,monkeypatch)
    await upload(ctx)
    async with ctx.sessions() as db:
        files=list((await db.scalars(select(CaseFile))).all())
        manifest=build_source_manifest(files)
        task=ArchiveTask(case_id='case-a',created_by='test-user',status=TaskStatus.awaiting_review,
            revision=1,fields={'律师事务所':'虚构卷宗律所'},source_manifest=manifest,
            source_version=source_version(manifest,'civil'))
        db.add(task);await db.commit();task_id=task.id
    work=task_work_dir('org-a','case-a',task_id)
    analysis=fixture_analysis(files[0].abs_path,{'律师事务所':'虚构卷宗律所'})
    save_snapshot(work,analysis,base_name='synthetic-quality-card',
                  metadata={'revision':1,'source_version':source_version(manifest,'civil')})
    url=f'/api/tasks/{task_id}/preview-fields/质量监督卡'
    response=await ctx.client.get(url)
    assert response.status_code==200
    assert response.json()['organization_name']=='虚构卷宗律所'
    assert next(x for x in response.json()['fields'] if x['key']=='律师事务所')['value']=='虚构卷宗律所'
    assert (await ctx.client.get(url,headers={'X-Test-Org':'org-b'})).status_code==404
    for value in ('虚构人工核对律所',''):
        revision=(await ctx.client.get(url)).json()['revision']
        result=await ctx.client.put(url,json={'expected_revision':revision,'values':{'律师事务所':value}})
        assert result.status_code==200,result.text
        current=(await ctx.client.get(url)).json()
        field=next(x for x in current['fields'] if x['key']=='律师事务所')
        assert field['value']==current['organization_name']==value
        assert field['assurance']['status']=='human_confirmed'
        async with ctx.sessions() as db:
            saved=await db.get(ArchiveTask,task_id)
            assert saved.manual_fields['律师事务所']==value
            assert not saved.confirmation
        snapshot,_=load_analysis(work)
        assert snapshot.fields['律师事务所']==value
