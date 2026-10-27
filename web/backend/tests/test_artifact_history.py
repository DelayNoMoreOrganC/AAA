"""Obsolete generations survive edits and interrupted renders, never as current output."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import ArchiveTask, TaskStatus
from app.services import archive_service
from app.services.artifact_history import last_published_generation, retain_published_generation
from tests.test_automatic_draft import draft_context, create_review, make_draft
from tests.test_file_import_api import upload_context


def test_history_uses_only_published_manifest_and_copies_owned_state():
    old = {"valid": True, "result_dir": "previous", "artifacts": [{"key": "archive_pdf"}]}
    task = SimpleNamespace(artifacts={"valid": False, "result_dir": "failed", "artifacts": []}, previous_artifacts=old)
    retain_published_generation(task)
    assert task.previous_artifacts == old
    task.previous_artifacts["artifacts"][0]["key"] = "changed"
    assert old["artifacts"][0]["key"] == "archive_pdf"
    assert last_published_generation(SimpleNamespace(artifacts=None)) is None


@pytest.mark.asyncio
async def test_repeated_edits_keep_persisted_generation_and_new_outputs_chain(draft_context):
    ctx = draft_context
    await create_review(ctx)
    original = await make_draft(ctx)
    original_manifest = deepcopy(original.artifacts)
    old_bytes = {item['path']: Path(item['path']).read_bytes() for item in original_manifest['artifacts']}
    for value in ('虚构立卷人甲', '虚构立卷人乙'):
        response = await ctx.client.patch(f'/api/tasks/{ctx.task_id}/fields', json={'fields': {'立卷人': value}})
        assert response.status_code == 200, response.text
        assert not response.json()['has_archive'] and response.json()['artifacts'] == []
        assert 'previous_artifacts' not in response.json()
        async with ctx.sessions() as db:
            saved = await db.get(ArchiveTask, ctx.task_id)
            assert saved.artifacts is None
            assert saved.previous_artifacts == original_manifest
        assert (await ctx.client.get(f'/api/tasks/{ctx.task_id}/download/archive')).status_code == 409
    rebuilt = await make_draft(ctx)
    assert rebuilt.fields['立卷人'] == '虚构立卷人乙'
    previous = rebuilt.artifacts['previous_generation']
    assert previous['result_dir'] == original_manifest['result_dir']
    assert previous['source_version'] == original_manifest['source_version']
    assert previous['delivery_kind'] == 'draft'
    assert json.loads((Path(rebuilt.artifacts['result_dir'])/'previous_generation.json').read_text(encoding='utf-8')) == original_manifest
    assert all(Path(path).read_bytes() == value for path, value in old_bytes.items())
    response = await ctx.client.patch(f'/api/tasks/{ctx.task_id}/fields', json={'fields': {'立卷人': '虚构立卷人丙'}})
    assert response.status_code == 200
    newest = await make_draft(ctx)
    assert newest.artifacts['previous_generation']['result_dir'] == rebuilt.artifacts['result_dir']
    # The preceding manifest remains the durable link to the older generation.
    chain = json.loads((Path(rebuilt.artifacts['result_dir'])/'artifact_manifest.json').read_text(encoding='utf-8'))
    assert chain['previous_generation']['result_dir'] == original_manifest['result_dir']
    assert ctx.analysis_calls == []


@pytest.mark.asyncio
async def test_render_failure_retains_generation_across_new_database_session(draft_context, monkeypatch):
    ctx = draft_context
    await create_review(ctx)
    original = await make_draft(ctx)
    renderer = archive_service.render_system_form_pdfs
    def failed(*args, **kwargs):
        raise RuntimeError('synthetic renderer failure')
    monkeypatch.setattr(archive_service, 'render_system_form_pdfs', failed)
    await archive_service.run_assemble(ctx.task_id, 'case-a', 'org-a', 'test-user', draft=True)
    async with ctx.sessions() as db:
        failed_task = await db.get(ArchiveTask, ctx.task_id)
        assert failed_task.status == TaskStatus.failed and failed_task.artifacts is None
        assert failed_task.previous_artifacts == original.artifacts
    assert (await ctx.client.get(f'/api/tasks/{ctx.task_id}/download/archive')).status_code == 409
    monkeypatch.setattr(archive_service, 'render_system_form_pdfs', renderer)
    rebuilt = await make_draft(ctx)
    assert rebuilt.artifacts['previous_generation']['result_dir'] == original.artifacts['result_dir']
    assert ctx.analysis_calls == []
