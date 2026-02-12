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
)
