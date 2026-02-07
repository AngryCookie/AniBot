from __future__ import annotations

from typing import Awaitable, Callable, List

from sqlalchemy.ext.asyncio import AsyncConnection

from bot.database.models import Base

Migration = Callable[[AsyncConnection], Awaitable[None]]


async def migration_create_all(conn: AsyncConnection) -> None:
    await conn.run_sync(Base.metadata.create_all)


MIGRATIONS: List[Migration] = [migration_create_all]
