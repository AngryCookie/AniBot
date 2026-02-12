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


def _require_env(name: str, *, allow_empty: bool = False) -> str:
    value = os.getenv(name, "")
    if value or allow_empty:
        return value
    raise RuntimeError(f"{name} is required")


def _validate_secret_strength(name: str, value: str, *, min_len: int = 24) -> str:
    if len(value) < min_len:
        raise RuntimeError(f"{name} must be at least {min_len} characters")
    return value


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
    session_max_age_seconds=int(os.getenv("SESSION_MAX_AGE_SECONDS", "2592000")),
    session_same_site=os.getenv("SESSION_SAME_SITE", "lax").lower(),
    session_https_only=os.getenv("SESSION_HTTPS_ONLY", "false").lower() in {"1", "true", "yes", "on"},
    session_cookie_path=os.getenv("SESSION_COOKIE_PATH", "/"),
    cors_allowed_origins=tuple(
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ),
)
