import os
from urllib.parse import urlparse
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    token: str
    database_url: str
    default_currency: str = "Coins"



def load_config() -> Config:
    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        raise RuntimeError("DISCORD_TOKEN environment variable is required")

    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")
    parsed = urlparse(database_url)
    if not parsed.scheme:
        raise RuntimeError("DATABASE_URL must include a scheme")
    if parsed.scheme not in {"sqlite+aiosqlite", "postgresql+asyncpg"}:
        raise RuntimeError("DATABASE_URL must use sqlite+aiosqlite or postgresql+asyncpg")
    return Config(token=token, database_url=database_url)
