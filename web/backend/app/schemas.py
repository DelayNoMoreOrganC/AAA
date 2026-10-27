"""Pydantic API request/response models."""
from __future__ import annotations

from typing import Any, Optional
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from .models import CaseType


# ---- Auth ----
class LoginRequest(BaseModel):
    username: str
    password: str


class NameLoginRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        import unicodedata
        value = unicodedata.normalize("NFKC", value).strip()
        if not value or len(value) > 40 or any(unicodedata.category(c).startswith("C") for c in value):
            raise ValueError("请输入1至40字的称呼，不含控制字符")
        return " ".join(value.split())


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=100)
    org_name: str = Field(..., min_length=2, max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码不能超过72字节")
        if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
            raise ValueError("密码必须同时包含字母和数字")
        return value


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    org_id: str
    is_active: bool

    model_config = {"from_attributes": True}


# ---- Cases ----
class CaseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    case_type: CaseType = CaseType.civil
    stage: str = Field(default="", max_length=40)

    @model_validator(mode="after")
    def validate_stage(self):
        from .services.archive_rules import STAGES
        if self.stage and self.stage not in STAGES.get(self.case_type.value, ()):
            raise ValueError("所选程序阶段不适用于该业务类型")
        return self


class CaseTaskSummary(BaseModel):
    id: int
    status: str
    phase: str
    error: str = ""
    recovery_target: Optional[dict] = None
    delivery_kind: str = ""
    has_archive: bool = False
    can_resume: bool = False
    can_assemble: bool = False
    source_changed: bool = False
    revision: int = 1
    formal_ready: bool = False


class CaseOut(BaseModel):
    id: str
    title: str
    case_type: str
    stage: str = ""
    created_at: str
    file_count: int = 0
    last_task_status: Optional[str] = None
    last_task_id: Optional[int] = None
    last_task_summary: Optional[CaseTaskSummary] = None


class CaseFileOut(BaseModel):
    id: str
    filename: str
    doc_type: str
    file_size: int
    created_at: str


class CaseFileUpdate(BaseModel):
    doc_type: str = Field(..., min_length=1, max_length=50)


class DocTypeOption(BaseModel):
    value: str
    label: str
    seq: Optional[int] = None


class TaskBriefOut(BaseModel):
    id: int
    status: str
    finished_at: Optional[str] = None
    output_pdf: str = ""
    preview_only: bool = False
    has_docx: bool = False
    delivery_kind: str = ""
    revision: int = 1

class CaseDetail(CaseOut):
    files: list[CaseFileOut] = []
    done_tasks: list[TaskBriefOut] = []


# ---- Tasks ----
class TaskOut(BaseModel):
    id: int
    case_id: str
    status: str
    progress: float
    stage: str
    error: str
    recovery_target: Optional[dict] = None
    fields: Optional[dict] = None
    catalog_status: Optional[list] = None
    output_pdf: str = ""
    order_mode: str = "catalog"
    preview_only: bool = False
    can_assemble: bool = True
    has_docx: bool = False
    has_archive: bool = False
    delivery_kind: str = ""
    created_at: str
    finished_at: Optional[str] = None
    revision: int = 1
    parent_task_id: Optional[int] = None
    source_version: str = ""
    source_changed: bool = False
    phase: str = "queued"
    issues: list[dict] = Field(default_factory=list)
    review_queue: list[dict] = Field(default_factory=list)
    formal_ready: bool = False
    rule_readiness: dict = Field(default_factory=dict)
    artifacts: list[dict] = Field(default_factory=list)
    can_resume: bool = False
    execution_profile: Optional[dict] = None


class GenerateRequest(BaseModel):
    model_config = {"extra": "forbid"}
    order_mode: Literal["catalog", "original"] = "catalog"
    parent_task_id: Optional[int] = None
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=128)
    cloud_consent: bool = Field(default=False, strict=True)
    expected_processing_mode: Optional[Literal["local", "ollama_local", "cloud", "glm_cloud", "deepseek_cloud"]] = None


class ResumeRequest(BaseModel):
    model_config = {"extra": "forbid"}
    cloud_consent: bool = Field(default=False, strict=True)
    expected_processing_mode: Optional[Literal["local", "ollama_local", "cloud", "glm_cloud", "deepseek_cloud"]] = None


class FieldUpdate(BaseModel):
    """Edited field values, used to re-fill templates only (no re-OCR)."""
    fields: dict[str, Any]
    order_mode: str = "catalog"
    outcome_type: str = "auto"




class AssembleRequest(BaseModel):
    order_mode: Literal["catalog", "original"] = "catalog"
    skipped: list[int] = Field(default_factory=list)
    confirmed_revision: Optional[int] = None
    confirmation: bool = False


class DraftRequest(BaseModel):
    model_config = {"extra": "forbid"}
    expected_revision: int = Field(..., ge=1, strict=True)


class DocumentClassificationPatch(BaseModel):
    model_config = {"extra": "forbid"}
    expected_revision: int = Field(..., ge=1, strict=True)
    doc_type: str = Field(..., min_length=1, max_length=50)
    catalog_seq: int = Field(..., ge=0, strict=True)
    reason: str = Field(..., min_length=1, max_length=1000)


class RegenerateRequest(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    outcome_type: str = "auto"


class FieldsPatch(BaseModel):
    fields: dict[str, Any]


class FieldDecisionRequest(BaseModel):
    model_config = {"extra": "forbid"}
    action: Literal["accept_current", "accept_candidate"]
    field: str = Field(..., min_length=1, max_length=80, strict=True)
    current_value: str = Field(..., max_length=20000, strict=True)
    selected_value: str | None = Field(default=None, min_length=1, max_length=20000, strict=True)
    expected_revision: int = Field(..., ge=1, strict=True)
    source_version: str = Field(..., pattern=r"^[0-9a-f]{64}$", strict=True)
    request_id: str = Field(..., min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", strict=True)

    @field_validator("field", "selected_value")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("不得为空白")
        return value

    @model_validator(mode="after")
    def valid_choice(self):
        if self.action == 'accept_current' and (not self.current_value.strip() or self.selected_value is not None):
            raise ValueError('确认当前值时须提供非空当前内容')
        if self.action == 'accept_candidate' and self.selected_value is None:
            raise ValueError('请选择候选内容')
        return self


class PreviewFieldsUpdate(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1, strict=True)
    values: dict[str, Any] = Field(default_factory=dict)
    styles: dict[str, Any] = Field(default_factory=dict)
    custom_values: dict[str, Any] = Field(default_factory=dict)


# ---- Per-account API settings ----
class SystemSettings(BaseModel):
    local_vision_tier: Literal["minimum", "recommended", "top", "unified128"] = "minimum"
    processing_mode: Literal["local", "ollama_local", "cloud", "glm_cloud", "deepseek_cloud"] = "local"
    local_llm_base_url: str = "http://127.0.0.1:11434/v1"
    local_llm_model: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    order_mode: str = "catalog"
    glm_key_configured: bool = False
    deepseek_key_configured: bool = False
    mineru_key_configured: bool = False
    external_ai_allowed: bool = False


class SystemSettingsUpdate(SystemSettings):
    glm_api_key: Optional[str] = Field(default=None, max_length=512)
    deepseek_api_key: Optional[str] = Field(default=None, max_length=512)
    mineru_api_token: Optional[str] = Field(default=None, max_length=8192)


class CloudPolicyUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    allowed: bool = Field(strict=True)
    confirm_external_processing: bool = Field(default=False, strict=True)


class LocalVisionSelection(BaseModel):
    model_config = {"extra": "forbid"}
    tier: Literal["minimum", "recommended", "top", "unified128"] = "minimum"


# ---- Admin ----
class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = "lawyer"
    org_id: Optional[str] = None


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class OrgOut(BaseModel):
    id: str
    name: str

class OrgCreate(BaseModel):
    name: str
