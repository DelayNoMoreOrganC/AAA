"""ORM models: Org / User / Case / CaseFile / Task / Setting."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


class Role(str, enum.Enum):
    admin = "admin"
    lawyer = "lawyer"


class CaseType(str, enum.Enum):
    civil = "civil"
    criminal = "criminal"
    admin = "admin"
    nonlit = "nonlit"
    counsel = "counsel"
    arbitration = "arbitration"
    consultation = "consultation"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    awaiting_review = "awaiting_review"
    done = "done"
    failed = "failed"


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="org", cascade="all, delete-orphan")
    cases: Mapped[list["Case"]] = relationship(back_populates="org", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), ForeignKey("orgs.id"), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), default="")
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.lawyer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    org: Mapped["Org"] = relationship(back_populates="users")
    api_settings: Mapped[list["UserSetting"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    assistant_turns: Mapped[list["AssistantTurn"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    assistant_drafts: Mapped[list["AssistantDraft"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    upload_intents: Mapped[list["UploadIntent"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class NamedWorkspace(Base):
    """Explicitly passwordless profiles, separate from existing login accounts."""
    __tablename__ = "named_workspaces"

    name_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), unique=True, nullable=False)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), ForeignKey("orgs.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    case_type: Mapped[str] = mapped_column(String(50), default="civil", nullable=False)
    stage: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    org: Mapped["Org"] = relationship(back_populates="cases")
    files: Mapped[list["CaseFile"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    tasks: Mapped[list["ArchiveTask"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    assistant_turns: Mapped[list["AssistantTurn"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    assistant_drafts: Mapped[list["AssistantDraft"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    upload_intents: Mapped[list["UploadIntent"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class CaseFile(Base):
    __tablename__ = "case_files"
    __table_args__ = (Index("ix_case_files_upload_request", "case_id", "upload_owner_id", "upload_request_id", unique=True),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(32), ForeignKey("cases.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(300), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), default="default", nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # Nullable preserves deliberate duplicate uploads from older clients. A
    # retry receipt belongs to one authenticated user in one authorized case.
    upload_owner_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    upload_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    upload_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upload_pdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    case: Mapped["Case"] = relationship(back_populates="files")

    @property
    def abs_path(self) -> str:
        """Absolute path on disk — resolved relative to project root at runtime."""
        from .config import ORGS_DIR
        return str(ORGS_DIR / self.stored_name)


class UploadIntent(Base):
    """Private metadata only. Terminal rows retain request-key tombstones."""
    __tablename__ = "upload_intents"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "case_id", "request_id", name="uq_upload_intent_scope"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(32), ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    filename: Mapped[str] = mapped_column(String(250), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    # No FK: a deleted material must leave a completed-but-unavailable receipt,
    # never release this old request ID to upload its bytes again.
    file_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    user: Mapped["User"] = relationship(back_populates="upload_intents")
    case: Mapped["Case"] = relationship(back_populates="upload_intents")


class ArchiveTask(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(32), ForeignKey("cases.id"), nullable=False, index=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.pending, nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(200), default="")
    log_text: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    recovery_target: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    catalog_status: Mapped[list | None] = mapped_column(JSON, nullable=True)
    output_pdf: Mapped[str] = mapped_column(String(500), default="")
    output_docx_dir: Mapped[str] = mapped_column(String(500), default="")
    order_mode: Mapped[str] = mapped_column(String(20), default="catalog")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(32), default="")
    parent_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), default="")
    source_manifest: Mapped[list | None] = mapped_column(JSON, nullable=True)
    execution_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    phase: Mapped[str] = mapped_column(String(40), default="queued")
    checkpoint: Mapped[str] = mapped_column(String(40), default="")
    requested_operation: Mapped[str] = mapped_column(String(20), default="analyze")
    manual_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    issues: Mapped[list | None] = mapped_column(JSON, nullable=True)
    artifacts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    previous_artifacts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rule_readiness: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confirmation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    case: Mapped["Case"] = relationship(back_populates="tasks")
    assistant_turns: Mapped[list["AssistantTurn"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    assistant_drafts: Mapped[list["AssistantDraft"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class ExperienceVersion(Base):
    """Immutable structured proposal; lifecycle updates use compare-and-swap."""
    __tablename__ = "experience_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), ForeignKey("orgs.id"), nullable=False, index=True)
    author_id: Mapped[str] = mapped_column(String(32), nullable=False)
    case_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_decision_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="case")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ExperienceOrigin(Base):
    """Private correction evidence, never included in reusable rules/prompts."""
    __tablename__ = "experience_origins"
    experience_id: Mapped[str] = mapped_column(String(32), ForeignKey("experience_versions.id"), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_key: Mapped[str] = mapped_column(String(100), nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    record: Mapped[dict] = mapped_column(JSON, nullable=False)
    record_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_binding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ExperienceEvaluation(Base):
    """Only a server evaluator writes receipts; no public 'passed' input."""
    __tablename__ = "experience_evaluations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    experience_id: Mapped[str] = mapped_column(String(32), ForeignKey("experience_versions.id"), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(80), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ExperienceEvent(Base):
    __tablename__ = "experience_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    experience_id: Mapped[str] = mapped_column(String(32), ForeignKey("experience_versions.id"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AssistantDraft(Base):
    """Private unsent text; clearing keeps a versioned tombstone."""
    __tablename__ = "assistant_drafts"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "case_id", "task_id", name="uq_assistant_draft_scope"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(32), ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    consumed_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    user: Mapped["User"] = relationship(back_populates="assistant_drafts")
    case: Mapped["Case"] = relationship(back_populates="assistant_drafts")
    task: Mapped["ArchiveTask"] = relationship(back_populates="assistant_drafts")


class AssistantTurn(Base):
    """Private conversation data, never operational logs or caller-supplied history."""
    __tablename__ = "assistant_turns"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "case_id", "task_id", "request_id",
                                      name="uq_assistant_turn_request"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(32), ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    safe_error: Mapped[str] = mapped_column(Text, default="")
    error_status: Mapped[int] = mapped_column(Integer, default=503)
    proposal_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    proposal_state: Mapped[str] = mapped_column(String(20), default="")
    proposal_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    proposal_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    applied_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    target_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    user: Mapped["User"] = relationship(back_populates="assistant_turns")
    case: Mapped["Case"] = relationship(back_populates="assistant_turns")
    task: Mapped["ArchiveTask"] = relationship(back_populates="assistant_turns")


class Setting(Base):
    """Legacy global settings retained only for one-time admin migration."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class UserSetting(Base):
    """Per-account LLM/OCR and workflow settings."""

    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    user: Mapped["User"] = relationship(back_populates="api_settings")
