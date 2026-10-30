import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.test_api import client, reset_database, _login
from app.bootstrap import ensure_bootstrap_admin
from app.config import DATA_DIR, Settings, get_settings
from app.database import AsyncSessionLocal, engine
from app.models import Base, User, TaskStatus
from app.services.archive_service import invalidate_output, _safe_base_name
from app.services.readiness import validate_local_url, check_readiness
from app.services.task_manager import TaskManager


@pytest.mark.asyncio
async def test_first_run_requires_token_and_never_ships_accounts(client):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await ensure_bootstrap_admin()
    async with AsyncSessionLocal() as db:
        assert (await db.execute(select(User))).scalars().all() == []
    assert (await client.get('/api/setup/status')).json() == {'required': True}
    body = {'username': 'owner', 'password': 'TestOnlyPass123', 'org_name': '虚构测试律所', 'setup_token': 'x' * 64}
    assert (await client.post('/api/setup', json=body)).status_code == 403
    body['setup_token'] = (DATA_DIR / 'setup.token').read_text().strip()
    assert (await client.post('/api/setup', json=dict(body, password='short123'))).status_code == 422
    assert (await client.post('/api/setup', json=body)).status_code == 200
    assert (await client.post('/api/setup', json=body)).status_code == 409
    assert not (DATA_DIR / 'setup.token').exists()
    assert (await client.get('/api/setup/status')).json() == {'required': False}
    assert await _login(client, 'owner', body['password'])
    assert (await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'})).status_code == 401


@pytest.mark.parametrize('url', ['https://api.deepseek.com', 'http://localhost:8000', 'http://127.0.0.1.evil.test', 'http://10.0.0.1', 'file:///test', 'http://user@127.0.0.1', 'http://127.0.0.1?url=https://example.com'])
def test_local_profile_rejects_ambiguous_or_remote_endpoints(url):
    with pytest.raises(ValueError):
        validate_local_url(url)


def test_local_loopback_supported():
    assert validate_local_url('http://127.0.0.1:11434/v1/') == 'http://127.0.0.1:11434/v1'
    assert validate_local_url('http://[::1]:11434/v1')


def test_edit_invalidates_previous_archive():
    task = SimpleNamespace(output_pdf='previous.pdf', status=TaskStatus.done, progress=100, finished_at='old')
    invalidate_output(task)
    assert task.status == TaskStatus.awaiting_review
    assert task.output_pdf == ''
    assert task.finished_at is None


@pytest.mark.parametrize('name', ['C:escape', '../../escape', 'CON', 'NUL.txt', 'x/y', 'x\\y', 'a' * 500])
def test_export_names_stay_inside_task_directory(name):
    safe = _safe_base_name(name)
    assert not any(char in safe for char in ':\\/')
    assert len(safe) <= 104
    assert safe not in ('CON', 'NUL.txt')


@pytest.mark.asyncio
async def test_cloud_is_blocked_by_workstation_policy(client):
    token = await _login(client)
    headers = {'Authorization': 'Bearer ' + token}
    await client.put('/api/settings', json={'processing_mode': 'cloud', 'deepseek_api_key': 'test-key', 'mineru_api_token': 'test-key'}, headers=headers)
    result = (await client.get('/api/settings/readiness', headers=headers)).json()
    assert result['ready'] is False
    assert any('禁止外部' in item for item in result['issues'])


@pytest.mark.asyncio
async def test_task_manager_serializes_work_and_delivers_thread_logs():
    manager = TaskManager()
    active = 0
    peak = 0
    async def work():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.01)
        active -= 1
    manager.start(1, work())
    manager.start(2, work())
    await asyncio.gather(*manager._tasks.values())
    assert peak == 1
    tracker = manager.get_tracker(1)
    queue = await tracker.subscribe()
    message = '归档助理：正在阅读 1 个页面片段'
    await asyncio.to_thread(tracker.log, message)
    assert (await asyncio.wait_for(queue.get(), 1))['text'] == message
