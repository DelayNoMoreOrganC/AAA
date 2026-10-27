"""Real merge/Word/ZIP with fictional input; model and PDF form renderers stubbed."""
import json
from pathlib import Path
import fitz,pytest
from tests.test_automatic_draft import draft_context,create_review,make_draft
from tests.test_file_import_api import upload_context
from app.services import archive_service
from app.models import ArchiveTask

@pytest.mark.asyncio
@pytest.mark.parametrize('kind,name,seq',[('intake_approval','立案审批表',1),('closure_report','结案报告表',18),('service_list','送达材料清单',17)])
async def test_original_intake_complete_delivery_and_edit_guards(draft_context,monkeypatch,kind,name,seq):
    ctx=draft_context
    u=ctx.analysis.doc_spans[0];u.doc_type=kind;u.catalog_seq=seq
    # Production analysis/save projects the source-form metadata before it
    # commits the versioned task and snapshot. Keep that boundary in this test.
    archive_service.refresh_form_drafts(ctx.analysis,{},ctx.manifest,ctx.issues)
    original_renderer=archive_service.render_system_form_pdfs
    def render(*args,exclude_templates=()):
        return {k:v for k,v in original_renderer(*args).items() if k not in exclude_templates}
    monkeypatch.setattr(archive_service,'render_system_form_pdfs',render)
    await create_review(ctx)
    task=await make_draft(ctx)
    keys={item['key'] for item in task.artifacts['artifacts']}
    assert 'source_pdf:'+name in keys and 'docx:'+name not in keys
    assert len(list(Path(task.output_docx_dir).glob('*.docx')))==4
    with fitz.open(task.output_pdf) as d:
        text=''.join(p.get_text() for p in d)
        assert text.count('UNIQUE_SYNTHETIC_SOURCE_A')==1 and text.count('UNIQUE_SYNTHETIC_SOURCE_B')==1
    response=await ctx.client.get(f'/api/tasks/{ctx.task_id}')
    assert response.status_code==200 and response.json()['has_docx'] and response.json()['has_archive']
    for route in ('preview-fields','docx'):
        response=await ctx.client.get(f'/api/tasks/{ctx.task_id}/{route}/{name}')
        assert response.status_code==409
    report=json.loads(Path(task.artifacts['result_dir'],'归档质检清单.json').read_text(encoding='utf-8'))
    assert name in report['derived_output']['original_forms']
    assert not any(r['template']==name for r in report['form_fill_audit'])
    check=next(r for r in report['material_completeness']['checks'] if r['id']=='execution:'+name)
    assert check['material_found'] and check['status']=='source_present_execution_unverified'
    assert check['sources'] and '另附原件' not in check['message']
