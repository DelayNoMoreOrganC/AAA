from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func

from .config import FRONTEND_DIST, get_settings
from .bootstrap import ensure_bootstrap_admin
from .database import init_db
from .routers import admin, auth, cases, settings as settings_router, tasks, setup, demo, workstation, evidence, assistant, assistant_drafts, upload_intents, experiences
from .services.word_service import shutdown_word
from .services.recovery import recover_interrupted_tasks
from .services.http_privacy import ConfidentialityMiddleware
from .core.v4_bridge import load
from .models import ArchiveTask, TaskStatus
from . import database
from .services.task_manager import task_manager

logger = logging.getLogger("v6")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app):
    await init_db()
    await ensure_bootstrap_admin()
    await recover_interrupted_tasks()
    app.state.recognition_identity = load("recognition_identity").recognition_identity()
    yield
    shutdown_word()


app = FastAPI(title="GD 归档助理 · 工作站", version="0.2.0", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(cases.router)
app.include_router(tasks.router)
app.include_router(settings_router.router)
app.include_router(admin.router)
app.include_router(setup.router)
app.include_router(demo.router)
app.include_router(workstation.router)
app.include_router(evidence.router)
app.include_router(assistant.router)
app.include_router(assistant_drafts.router)
app.include_router(upload_intents.router)
app.include_router(experiences.router)


app.add_middleware(ConfidentialityMiddleware)


@app.exception_handler(RequestValidationError)
async def private_validation_error(request, exc):
    # FastAPI's default validation response includes the rejected input; it can
    # be a complete form, question, password or document excerpt.
    return JSONResponse(status_code=422, content={
        "detail": "输入格式或长度不符合要求，请检查填写内容后重试。 [GD_INPUT_INVALID]"
    })


@app.get("/api/health")
async def health():
    # Counts only: no case titles, source paths or data are exposed. Unknown DB
    # state fails the scheduled-run preflight closed, never masquerades as idle.
    active = None
    try:
        async with database.AsyncSessionLocal() as db:
            active = await db.scalar(select(func.count()).select_from(ArchiveTask).where(
                ArchiveTask.status.in_((TaskStatus.pending, TaskStatus.running))))
    except Exception:
        pass
    return {"status": "ok", "application": "gd-workstation", "version": app.version,
            "diagnostic_policy": "fixed-errors-v1", "capabilities": _settings.capabilities,
            "pid": os.getpid(), "active_archive_tasks": active,
            "processing_busy": task_manager.semaphore.locked(),
            **getattr(app.state, "recognition_identity", {})}


@app.get("/api/capabilities")
async def capabilities():
    return _settings.capabilities


if FRONTEND_DIST.exists():
    @app.get("/", include_in_schema=False)
    async def index_html():
        return FileResponse(str(FRONTEND_DIST / "index.html"))
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

if FRONTEND_DIST.exists():
    @app.get("/{path:path}", include_in_schema=False)
    async def catch_all_spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        target = (FRONTEND_DIST / (path or "index.html")).resolve()
        if not target.is_relative_to(FRONTEND_DIST.resolve()):
            raise HTTPException(404)
        if target.is_file():
            return FileResponse(str(target))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
