from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    discord_client_id: str
    discord_client_secret: str
    discord_redirect_uri: str
    session_secret: str
    session_encryption_key: str
    readonly_api_key: str
    web_base_url: str
    session_cookie_name: str
    session_max_age_seconds: int
    session_same_site: str
    session_https_only: bool
    session_cookie_path: str
    cors_allowed_origins: tuple[str, ...]
    app_env: str


def _require_env(name: str, *, allow_empty: bool = False) -> str:
    value = os.getenv(name, "")
    if value or allow_empty:
        return value
    raise RuntimeError(f"{name} is required")


def _validate_secret_strength(name: str, value: str, *, min_len: int = 24) -> str:
    if len(value) < min_len:
        raise RuntimeError(f"{name} must be at least {min_len} characters")
    return value


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        f"{name} must be a boolean value (true/false/1/0/yes/no/on/off), got {raw!r}"
    )


def _parse_same_site(name: str, default: str = "lax") -> str:
    raw = os.getenv(name, default)
    normalized = raw.strip().lower()
    if normalized in {"lax", "strict", "none"}:
        return normalized
    raise RuntimeError(
        f"{name} must be one of: lax, strict, none (case-insensitive), got {raw!r}"
    )


settings = Settings(
    database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db"),
    discord_client_id=os.getenv("DISCORD_CLIENT_ID", ""),
    discord_client_secret=os.getenv("DISCORD_CLIENT_SECRET", ""),
    discord_redirect_uri=os.getenv("DISCORD_REDIRECT_URI", ""),
    session_secret=_validate_secret_strength("SESSION_SECRET", _require_env("SESSION_SECRET")),
    session_encryption_key=_require_env("SESSION_ENCRYPTION_KEY"),
    readonly_api_key=os.getenv("READONLY_API_KEY", ""),
    web_base_url=os.getenv("WEB_BASE_URL", "http://localhost:8000"),
    session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "anibot_session"),
    session_max_age_seconds=_parse_int_env("SESSION_MAX_AGE_SECONDS", 2592000),
    session_same_site=_parse_same_site("SESSION_SAME_SITE", "lax"),
    session_https_only=_parse_bool_env("SESSION_HTTPS_ONLY", False),
    session_cookie_path=os.getenv("SESSION_COOKIE_PATH", "/"),
    cors_allowed_origins=tuple(
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ),
    app_env=os.getenv("APP_ENV", "development").strip().lower(),
)
