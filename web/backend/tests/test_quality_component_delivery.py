"""Real assembly/Word/ZIP and API; fictional material, stubbed model and PDF forms."""
import copy
import json
from pathlib import Path
from zipfile import ZipFile

import fitz
import pytest
from tests.test_automatic_draft import draft_context,create_review,make_draft
from tests.test_file_import_api import upload_context
from app.services import archive_service


@pytest.mark.asyncio
@pytest.mark.parametrize('kinds',[(),('quality_card',),('client_notice',),('quality_card','client_notice')])
async def test_quality_component_complete_delivery(draft_context,monkeypatch,kinds):
    ctx=draft_context
    if kinds:
        original=ctx.analysis.doc_spans[0]
        if len(kinds)==1:
            original.doc_type=kinds[0];original.catalog_seq=16
        else:
            original.doc_type=kinds[0];original.catalog_seq=16;original.end_page=0
            other=copy.deepcopy(original);other.doc_id+=1;other.doc_type=kinds[1];other.start_page=other.end_page=1
            ctx.analysis.doc_spans.append(other)
    archive_service.refresh_form_drafts(ctx.analysis,{},ctx.manifest,ctx.issues)
    renderer=archive_service.render_system_form_pdfs
    def render(*args,exclude_templates=(),quality_component=None):
        result={k:v for k,v in renderer(*args).items() if k not in exclude_templates}
        if quality_component:
            path=Path(result['质量监督卡'])
            with fitz.open() as document:
                document.new_page().insert_text((72,72),'GENERATED_'+quality_component)
                document.save(path)
        return result
    monkeypatch.setattr(archive_service,'render_system_form_pdfs',render)
    await create_review(ctx)
    task=await make_draft(ctx)
    keys={item['key'] for item in task.artifacts['artifacts']}
    assert task.artifacts['valid']
    assert ('source_pdf:质量监督卡' in keys)==(len(kinds)==2)
    assert ('source_component_pdf:质量监督卡' in keys)==(len(kinds)==1)
    assert ('docx:质量监督卡' in keys)==(len(kinds)!=2)
    assert len(keys)==(10 if len(kinds)==1 else 9)
    with fitz.open(task.output_pdf) as document:
        text=''.join(p.get_text() for p in document)
        assert text.count('UNIQUE_SYNTHETIC_SOURCE_A')==1
        assert text.count('UNIQUE_SYNTHETIC_SOURCE_B')==1
    response=await ctx.client.get(f'/api/tasks/{ctx.task_id}')
    assert response.status_code==200 and response.json()['has_archive'] and response.json()['has_docx']
    response=await ctx.client.get(f'/api/tasks/{ctx.task_id}/preview-fields/质量监督卡')
    assert response.status_code==(409 if 'quality_card' in kinds else 200)
    response=await ctx.client.get(f'/api/tasks/{ctx.task_id}/docx/质量监督卡')
    assert response.status_code==(409 if len(kinds)==2 else 200)
    report=json.loads(Path(task.artifacts['result_dir'],'归档质检清单.json').read_text(encoding='utf8'))
    audited=any(row['template']=='质量监督卡' for row in report['form_fill_audit'])
    assert audited==('quality_card' not in kinds)
    if len(kinds)==1:
        assert report['derived_output']['template_evidence']['forms']['质量监督卡']['expected_pages']==1
        target=next(item for item in task.artifacts['artifacts'] if item['key']=='docx:质量监督卡')
        with ZipFile(target['path']) as package:
            xml=package.read('word/document.xml').decode()
            assert ('<w:tbl>' in xml)==('quality_card' not in kinds)
