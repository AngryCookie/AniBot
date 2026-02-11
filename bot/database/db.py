from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text


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

    async def apply_migrations(self, migrations) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_versions ("
                    "version INTEGER NOT NULL,"
                    "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            result = await conn.execute(
                text("SELECT COALESCE(MAX(version), 0) FROM schema_versions")
            )
            current_version = result.scalar_one()
            for index, migration in enumerate(migrations, start=1):
                if index <= current_version:
                    continue
                await migration(conn)
                await conn.execute(
                    text("INSERT INTO schema_versions (version) VALUES (:version)"),
                    {"version": index},
                )

    @asynccontextmanager
    async def session(self) -> AsyncSession:
        session = self.scoped_session()
        try:
            yield session
        except Exception:
            if session.in_transaction():
                await session.rollback()
            raise
        finally:
            await session.close()
            await self.scoped_session.remove()
