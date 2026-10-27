"""Passwordless workspace isolation. Synthetic database, no OCR/model calls."""
import asyncio
from types import SimpleNamespace
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database import Base, get_db
from app.config import get_settings
from app.models import User, Org, Role, NamedWorkspace, ArchiveTask, TaskStatus
from app.routers import auth, cases, tasks
from app.security import hash_password

@pytest_asyncio.fixture
async def ctx(tmp_path, monkeypatch):
    engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'profiles.db'))
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(get_settings(),'name_login_enabled',True)
    monkeypatch.setattr(get_settings(),'secret_key','synthetic-only-secret-for-name-workspace-tests')
    app=FastAPI();app.include_router(auth.router);app.include_router(cases.router);app.include_router(tasks.router)
    async def db():
        async with sessions() as s: yield s
    app.dependency_overrides[get_db]=db
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://synthetic') as client:
        yield SimpleNamespace(client=client,sessions=sessions)
    await engine.dispose()

async def enter(ctx,name):
    r=await ctx.client.post('/api/auth/name-login',json={'name':name});assert r.status_code==200,r.text
    return r.json(),{'Authorization':'Bearer '+r.json()['access_token']}

@pytest.mark.asyncio
async def test_names_separate_history_download_and_resume(ctx):
    a,ha=await enter(ctx,'虚构甲');b,hb=await enter(ctx,'虚构乙')
    ca=await ctx.client.post('/api/cases',json={'title':'虚构甲的档案'},headers=ha);assert ca.status_code==201
    cid=ca.json()['id']
    assert len((await ctx.client.get('/api/cases',headers=ha)).json())==1
    assert (await ctx.client.get('/api/cases',headers=hb)).json()==[]
    assert (await ctx.client.get('/api/cases/'+cid,headers=hb)).status_code==404
    ua=(await ctx.client.get('/api/auth/me',headers=ha)).json()
    async with ctx.sessions() as db:
        t=ArchiveTask(case_id=cid,created_by=ua['id'],status=TaskStatus.done);db.add(t);await db.commit();tid=t.id
    for path in [f'/api/tasks/{tid}',f'/api/tasks/{tid}/download/zip']:
        assert (await ctx.client.get(path,headers=hb)).status_code==404
    again,hagain=await enter(ctx,'  虚构甲  ')
    assert (await ctx.client.get('/api/auth/me',headers=hagain)).json()['id']==ua['id']
    assert (await ctx.client.get('/api/admin/users',headers=ha)).status_code in (403,404)
    refresh=await ctx.client.post('/api/auth/refresh',json={'refresh_token':again['refresh_token']});assert refresh.status_code==200
    assert (await ctx.client.get('/api/auth/me',headers={'Authorization':'Bearer '+refresh.json()['access_token']})).json()['id']==ua['id']

@pytest.mark.asyncio
async def test_admin_and_existing_accounts_not_claimed(ctx):
    async with ctx.sessions() as db:
        org=Org(name='原机构');db.add(org);await db.flush()
        admin=User(username='admin',display_name='原使用者',role=Role.admin,org_id=org.id,hashed_password=hash_password('syntheticOnly123'))
        db.add(admin);await db.commit();old_id=admin.id
    for reserved in ['admin','ＡＤＭＩＮ','管理员']:
        assert (await ctx.client.post('/api/auth/name-login',json={'name':reserved})).status_code==400
    _,h=await enter(ctx,'原使用者');u=(await ctx.client.get('/api/auth/me',headers=h)).json()
    assert u['id']!=old_id and u['role']=='lawyer'
    assert (await ctx.client.post('/api/auth/login',json={'username':'admin','password':'syntheticOnly123'})).status_code==200

@pytest.mark.asyncio
async def test_invalid_disabled_and_setting_shutdown(ctx,monkeypatch):
    for name in ['', '   ', 'a'*41, '隐\u200b藏']:
        assert (await ctx.client.post('/api/auth/name-login',json={'name':name})).status_code==422
    token,h=await enter(ctx,'虚构停用')
    monkeypatch.setattr(get_settings(),'name_login_enabled',False)
    assert (await ctx.client.get('/api/auth/options')).json()['name_login_enabled'] is False
    assert (await ctx.client.post('/api/auth/name-login',json={'name':'虚构停用'})).status_code==403
    assert (await ctx.client.get('/api/auth/me',headers=h)).status_code==401
    assert (await ctx.client.post('/api/auth/refresh',json={'refresh_token':token['refresh_token']})).status_code==401
    monkeypatch.setattr(get_settings(),'name_login_enabled',True)
    async with ctx.sessions() as db:
        u=await db.scalar(select(User).where(User.display_name=='虚构停用'));u.is_active=False;await db.commit()
    assert (await ctx.client.post('/api/auth/name-login',json={'name':'虚构停用'})).status_code==403

@pytest.mark.asyncio
async def test_simultaneous_first_login_same_name(ctx):
    results=await asyncio.gather(enter(ctx,'并发虚构'),enter(ctx,'并发虚构'))
    users=[(await ctx.client.get('/api/auth/me',headers=h)).json()['id'] for _,h in results]
    assert users[0]==users[1]
    async with ctx.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(NamedWorkspace))==1
        assert await db.scalar(select(func.count()).select_from(Org))==1
