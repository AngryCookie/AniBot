from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Database:
    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(database_url, echo=False, future=True)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def init_models(self, base_metadata) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(base_metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncSession:
        async with self.session_factory() as session:
            yield session
