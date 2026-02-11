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


async def migration_create_economy_transactions(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS economy_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                type VARCHAR(64) NOT NULL,
                amount INTEGER NOT NULL,
                balance_before INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                source VARCHAR(128) NULL,
                reference_id INTEGER NULL,
                metadata JSON NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_economy_transactions_guild_id "
            "ON economy_transactions (guild_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_economy_transactions_user_id "
            "ON economy_transactions (user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_economy_transactions_type "
            "ON economy_transactions (type)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_economy_transactions_created_at "
            "ON economy_transactions (created_at)"
        )
    )


async def migration_add_monthly_analytics_support(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS monthly_analytics_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                report_payload JSON NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                autoposted_at DATETIME NULL,
                CONSTRAINT uq_monthly_analytics_guild_period UNIQUE (guild_id, year, month)
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_monthly_analytics_reports_guild_id "
            "ON monthly_analytics_reports (guild_id)"
        )
    )
    await conn.execute(
        text(
            "INSERT OR IGNORE INTO feature_flags (name, enabled, description, created_at, updated_at) "
            "VALUES (:name, :enabled, :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "name": "monthly_reports_enabled",
            "enabled": 0,
            "description": "Enable monthly analytics report generation.",
        },
    )
    await conn.execute(
        text(
            "INSERT OR IGNORE INTO feature_flags (name, enabled, description, created_at, updated_at) "
            "VALUES (:name, :enabled, :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "name": "monthly_reports_autopost",
            "enabled": 0,
            "description": "Enable automatic posting of monthly analytics reports.",
        },
    )
    guild_columns = await conn.execute(text("PRAGMA table_info(guilds)"))
    guild_column_names = {str(row[1]) for row in guild_columns}
    if "analytics_channel_id" not in guild_column_names:
        await conn.execute(text("ALTER TABLE guilds ADD COLUMN analytics_channel_id BIGINT"))


MIGRATIONS: List[Migration] = [
    migration_create_all,
    migration_create_community_goals,
    migration_create_community_goal_participants,
    migration_create_economy_transactions,
    migration_add_monthly_analytics_support,
]
