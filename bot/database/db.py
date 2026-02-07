from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(database_url, echo=False, future=True)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )
        self.scoped_session = async_scoped_session(
            self.session_factory, scopefunc=asyncio.current_task
        )

    async def init_models(self, base_metadata) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(base_metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncSession:
        session = self.scoped_session()
        try:
            yield session
        finally:
            await session.close()
            self.scoped_session.remove()
