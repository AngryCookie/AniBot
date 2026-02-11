from __future__ import annotations

from typing import Awaitable, Callable, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bot.database.models import Base
import bot.betting.models  # noqa: F401

Migration = Callable[[AsyncConnection], Awaitable[None]]


async def migration_create_all(conn: AsyncConnection) -> None:
    await conn.run_sync(Base.metadata.create_all)


async def migration_create_community_goals(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS community_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                metric_type VARCHAR(32) NOT NULL,
                target_value INTEGER NOT NULL,
                current_value INTEGER NOT NULL DEFAULT 0,
                starts_at DATETIME NOT NULL,
                ends_at DATETIME NOT NULL,
                reward_role_id BIGINT NULL,
                min_participation_threshold INTEGER NOT NULL DEFAULT 0,
                status VARCHAR(16) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_community_goals_guild_id ON community_goals (guild_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_community_goals_starts_at ON community_goals (starts_at)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_community_goals_ends_at ON community_goals (ends_at)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_community_goals_guild_status ON community_goals (guild_id, status)"
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_community_goals_active_guild "
            "ON community_goals (guild_id) WHERE status = 'active'"
        )
    )


async def migration_create_community_goal_participants(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS community_goal_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER NOT NULL,
                user_id BIGINT NOT NULL,
                contribution_value INTEGER NOT NULL DEFAULT 0,
                rewarded BOOLEAN NOT NULL DEFAULT 0,
                CONSTRAINT uq_goal_participant UNIQUE (goal_id, user_id),
                CONSTRAINT fk_goal_participants_goal
                    FOREIGN KEY (goal_id) REFERENCES community_goals (id) ON DELETE CASCADE
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_goal_participants_goal_id "
            "ON community_goal_participants (goal_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_goal_participants_user_id "
            "ON community_goal_participants (user_id)"
        )
    )


MIGRATIONS: List[Migration] = [
    migration_create_all,
    migration_create_community_goals,
    migration_create_community_goal_participants,
]
