"""Authenticated original-PDF pixels, pagination and safe failure responses."""
import fitz
import pytest
from tests.test_file_import_api import upload_context
from app.models import ArchiveTask, TaskStatus
from app.routers import tasks


@pytest.mark.asyncio
async def test_original_template_page_pixels_and_isolation(upload_context,monkeypatch,tmp_path):
    path=tmp_path/'original.pdf'
    with fitz.open() as document:
        for text in ('FICTIONAL PAGE ONE','FICTIONAL PAGE TWO'):
            document.new_page().insert_text((72,72),text)
        document.save(path)
    async with upload_context.sessions() as db:
        task=ArchiveTask(case_id='case-a',created_by='test-user',status=TaskStatus.awaiting_review,revision=3)
        db.add(task);await db.commit();task_id=task.id
    calls=[]
    async def preview(*args):calls.append(True);return str(path)
    monkeypatch.setattr(tasks,'preview_template_pdf',preview)
    endpoint=f'/api/tasks/{task_id}/preview/质量监督卡'
    response=await upload_context.client.get(endpoint+'?page=2')
    assert response.status_code==200
    assert response.headers['x-template-pages']=='2'
    assert response.headers['x-template-page']=='2'
    assert response.headers['x-task-revision']=='3'
    assert response.headers['x-template-fidelity']=='original'
    assert response.headers['cache-control']=='no-store'
    with fitz.open(path) as document:
        expected=document[1].get_pixmap(matrix=fitz.Matrix(1.6,1.6),alpha=False)
    actual=fitz.Pixmap(response.content)
    assert actual.samples==expected.samples
    assert (await upload_context.client.get(endpoint+'?page=3')).status_code==404
    assert (await upload_context.client.get(endpoint+'?page=0')).status_code==422
    count=len(calls)
    assert (await upload_context.client.get('/api/tasks/999999/preview/质量监督卡?page=1')).status_code==404
    assert len(calls)==count
    response=await upload_context.client.get(endpoint)
    assert response.content==path.read_bytes() and response.headers['content-type']=='application/pdf'


@pytest.mark.asyncio
async def test_corrupt_page_preview_error_does_not_leak_contents(upload_context,monkeypatch,tmp_path):
    path=tmp_path/'bad.pdf';path.write_bytes(b'FICTIONAL_PRIVATE_CORRUPT_FILE')
    async with upload_context.sessions() as db:
        task=ArchiveTask(case_id='case-a',created_by='test-user',status=TaskStatus.awaiting_review)
        db.add(task);await db.commit();task_id=task.id
    async def preview(*args):return str(path)
    monkeypatch.setattr(tasks,'preview_template_pdf',preview)
    response=await upload_context.client.get(f'/api/tasks/{task_id}/preview/质量监督卡?page=1')
    assert response.status_code==500 and 'GD_PREVIEW_FAILED' in response.text
    assert 'FICTIONAL_PRIVATE' not in response.text and str(path) not in response.text
