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


settings = Settings(
    database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db"),
    discord_client_id=os.getenv("DISCORD_CLIENT_ID", ""),
    discord_client_secret=os.getenv("DISCORD_CLIENT_SECRET", ""),
    discord_redirect_uri=os.getenv("DISCORD_REDIRECT_URI", ""),
    session_secret=os.getenv("SESSION_SECRET", ""),
    session_encryption_key=os.getenv("SESSION_ENCRYPTION_KEY", ""),
)
