"""Async SQLAlchemy engine + session factory for SQLite (WAL mode)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings, DB_PATH


class Base(DeclarativeBase):
    pass


settings = get_settings()

engine = create_async_engine(
    settings.sqlite_url,
    echo=False,
    hide_parameters=True,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Create tables and enable WAL pragma."""
    # ensure parent dir exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON;")
        await conn.run_sync(Base.metadata.create_all)
        await migrate_task_columns(conn)
        await migrate_case_columns(conn)
        await migrate_upload_columns(conn)
        await migrate_assistant_columns(conn)
        from .services.assistant_history import recover_pending
        await recover_pending(conn)
        from .services.assistant_journal import recover_applications
        await recover_applications(conn)


async def migrate_assistant_columns(conn) -> None:
    existing = {row[1] for row in (await conn.exec_driver_sql("PRAGMA table_info(assistant_turns)")).all()}
    for name, sql_type in {"snapshot_before": "JSON", "target_revision": "INTEGER"}.items():
        if name not in existing:
            await conn.exec_driver_sql(f"ALTER TABLE assistant_turns ADD COLUMN {name} {sql_type}")


async def migrate_case_columns(conn) -> None:
    existing = {row[1] for row in (await conn.exec_driver_sql("PRAGMA table_info(cases)")).all()}
    if "stage" not in existing:
        await conn.exec_driver_sql("ALTER TABLE cases ADD COLUMN stage VARCHAR(40) NOT NULL DEFAULT ''")


async def migrate_upload_columns(conn) -> None:
    """Optional upload receipts; historical material rows remain unchanged."""
    existing = {row[1] for row in (await conn.exec_driver_sql("PRAGMA table_info(case_files)")).all()}
    for name, sql_type in {"upload_owner_id": "VARCHAR(32)", "upload_request_id": "VARCHAR(128)",
                           "upload_fingerprint": "VARCHAR(64)", "upload_pdf_sha256": "VARCHAR(64)"}.items():
        if name not in existing:
            await conn.exec_driver_sql(f"ALTER TABLE case_files ADD COLUMN {name} {sql_type}")
    await conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_case_files_upload_request "
                              "ON case_files(case_id, upload_owner_id, upload_request_id)")


async def migrate_task_columns(conn) -> None:
    """Additive SQLite migration: preserve existing users, files and task history."""
    columns = {
        "created_by": "VARCHAR(32) NOT NULL DEFAULT ''",
        "parent_task_id": "INTEGER",
        "idempotency_key": "VARCHAR(128)",
        "revision": "INTEGER NOT NULL DEFAULT 1",
        "source_version": "VARCHAR(64) NOT NULL DEFAULT ''",
        "source_manifest": "JSON",
        "execution_profile": "JSON",
        "phase": "VARCHAR(40) NOT NULL DEFAULT 'queued'",
        "checkpoint": "VARCHAR(40) NOT NULL DEFAULT ''",
        "requested_operation": "VARCHAR(20) NOT NULL DEFAULT 'analyze'",
        "manual_fields": "JSON", "issues": "JSON", "artifacts": "JSON", "previous_artifacts": "JSON", "recovery_target": "JSON",
        "rule_readiness": "JSON", "confirmation": "JSON", "heartbeat_at": "DATETIME",
    }
    existing = {row[1] for row in (await conn.exec_driver_sql("PRAGMA table_info(tasks)")).all()}
    for name, sql_type in columns.items():
        if name not in existing:
            await conn.exec_driver_sql(f"ALTER TABLE tasks ADD COLUMN {name} {sql_type}")
    await conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_tasks_case_request ON tasks(case_id, idempotency_key) WHERE idempotency_key IS NOT NULL")
