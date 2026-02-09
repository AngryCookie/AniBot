from __future__ import annotations

from bot.database.db import Database

from .config import settings

database = Database(settings.database_url)
