import os
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
    return Config(token=token, database_url=database_url)
