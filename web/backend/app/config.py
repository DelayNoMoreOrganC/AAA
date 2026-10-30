"""Application configuration via environment variables / pydantic-settings."""
from __future__ import annotations

import os
import shutil
import secrets
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from dotenv import dotenv_values


# Resolve project root: this file lives at web/backend/app/config.py
BACKEND_DIR = Path(__file__).resolve().parent.parent          # web/backend
WEB_DIR = BACKEND_DIR.parent                                   # web
PROJECT_ROOT = WEB_DIR.parent                                  # F:\GD
_env_data_dir = dotenv_values(WEB_DIR / ".env").get("V5_DATA_DIR")
DATA_DIR = Path(os.environ.get("V5_DATA_DIR") or _env_data_dir or str(WEB_DIR / "data")).expanduser().resolve()
DB_PATH = DATA_DIR / "archive.db"
ORGS_DIR = DATA_DIR / "orgs"
# Freeze each process's build directory at import time. A staged deployment may
# select its own immutable build without changing the default used by old workers.
FRONTEND_DIST = Path(os.environ.get("V5_FRONTEND_DIST") or str(WEB_DIR / "frontend" / "dist")).expanduser().resolve()

V4_ROOT = str(WEB_DIR.parent)


def find_chromium(configured_path: str = "") -> str:
    """Return a usable Chrome/Chromium executable for HTML-to-PDF rendering."""
    candidates = [configured_path]
    if os.name == "nt":
        candidates.extend([
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        ])
    elif os.sys.platform == "darwin":
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])
    for command in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(command)
        if found:
            candidates.append(found)
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=WEB_DIR / ".env",
        env_prefix="V5_",
        extra="ignore",
    )

    # JWT
    secret_key: str = ""
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    chromium_path: str = ""

    # Cross-platform document workflow. macOS/Linux default to browser-only
    # preview editing because Word COM is unavailable there. Windows keeps the
    # original DOCX generation/assembly workflow unless explicitly overridden.
    preview_only: bool = os.name != "nt"
    registration_enabled: bool = False
    # Opt-in for a trusted workstation; a name is a profile selector, not proof of identity.
    name_login_enabled: bool = False
    allow_external_ai: bool = False
    # User-approved DeepSeek ceiling (2026-10-30). An operator may reduce it,
    # but cannot silently exceed the approved 20 dispatches per new task.
    deepseek_request_limit: int = Field(default=20, ge=0, le=20)
    # Optional tighter cross-provider ceiling. Local Ollama is not assigned
    # the cloud limit. Both choices are frozen when a new task is created.
    model_request_limit: int | None = Field(default=None, ge=0, le=100000)
    # Legacy initial default; the explicit administrator policy overrides it.
    # Deployment administrators may enforce this separate, non-overridable lock.
    external_ai_locked: bool = False
    cors_origins: list[str] = []
    local_llm_base_url: str = "http://127.0.0.1:11434/v1"
    local_llm_model: str = ""

    # File upload limits
    max_upload_mb: int = 200

    # Database
    database_url: str = ""

    # Bootstrap admin (created on first run if no users exist)
    bootstrap_admin_user: str = ""
    bootstrap_admin_password: str = ""

    @property
    def sqlite_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"

    @property
    def capabilities(self) -> dict[str, object]:
        from .services.cloud_policy import external_ai_allowed
        chromium = find_chromium(self.chromium_path)
        return {
            "platform": os.sys.platform,
            "mode": "workstation" if self.preview_only else "docx",
            "preview_only": self.preview_only,
            "docx_generation": True,
            "archive_assembly": not self.preview_only or bool(chromium),
            "html_pdf_generation": bool(chromium),
            "registration_enabled": self.registration_enabled,
            "external_ai_allowed": external_ai_allowed(self),
        }

    @property
    def chromium_executable(self) -> str:
        return find_chromium(self.chromium_path)


@lru_cache
def get_settings() -> "Settings":
    s = Settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ORGS_DIR.mkdir(parents=True, exist_ok=True)
    if not s.secret_key or s.secret_key == "change-me-in-production-please":
        s.secret_key = local_secret("jwt.secret")
    if len(s.secret_key.encode("utf-8")) < 32:
        raise ValueError("V5_SECRET_KEY 必须至少 32 字节，或留空由工作站自动生成")
    return s


def local_secret(filename: str) -> str:
    """Persist installation-specific secrets, never a universal password."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(48)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value)
    return value
