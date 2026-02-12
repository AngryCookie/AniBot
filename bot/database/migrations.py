from __future__ import annotations

from typing import Awaitable, Callable, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bot.database.models import Base
import bot.betting.models  # noqa: F401
import bot.referral.models  # noqa: F401

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
                amount INTEGER NOT NULL,
                balance_before INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                source VARCHAR(128) NOT NULL,
                metadata_json JSON NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    table_columns = await conn.execute(text("PRAGMA table_info(economy_transactions)"))
    column_names = {str(row[1]) for row in table_columns}
    if "metadata_json" not in column_names:
        await conn.execute(text("ALTER TABLE economy_transactions ADD COLUMN metadata_json JSON"))
    if "metadata" in column_names:
        await conn.execute(
            text(
                "UPDATE economy_transactions SET metadata_json = metadata "
                "WHERE metadata_json IS NULL AND metadata IS NOT NULL"
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
            "CREATE INDEX IF NOT EXISTS ix_economy_transactions_source "
            "ON economy_transactions (source)"
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




async def migration_create_referrals(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS referral_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                creator_user_id BIGINT NULL,
                code VARCHAR(64) NOT NULL,
                reward_amount INTEGER NOT NULL,
                max_uses INTEGER NULL,
                current_uses INTEGER NOT NULL DEFAULT 0,
                expires_at DATETIME NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_referral_code_guild_code UNIQUE (guild_id, code)
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_codes_guild_id "
            "ON referral_codes (guild_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_codes_creator_user_id "
            "ON referral_codes (creator_user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_codes_guild_active "
            "ON referral_codes (guild_id, is_active)"
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS referral_usages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                inviter_user_id BIGINT NOT NULL,
                invited_user_id BIGINT NOT NULL,
                reward_amount INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_referral_usage_invited_guild UNIQUE (guild_id, invited_user_id),
                CONSTRAINT ck_referral_not_self CHECK (inviter_user_id != invited_user_id)
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_usages_guild_id "
            "ON referral_usages (guild_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_usages_created_at "
            "ON referral_usages (created_at)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_usages_guild_inviter "
            "ON referral_usages (guild_id, inviter_user_id)"
        )
    )


async def migration_create_referral_core(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS referral_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                referrer_user_id BIGINT NOT NULL,
                referred_user_id BIGINT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_referral_link_guild_referred UNIQUE (guild_id, referred_user_id),
                CONSTRAINT ck_referral_link_not_self CHECK (referrer_user_id != referred_user_id)
            )
            """
        )
    )
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_referral_links_guild_id ON referral_links (guild_id)"))
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_links_referrer_user_id "
            "ON referral_links (referrer_user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_links_referred_user_id "
            "ON referral_links (referred_user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_links_guild_referrer "
            "ON referral_links (guild_id, referrer_user_id)"
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS referral_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                referrer_user_id BIGINT NOT NULL,
                referred_user_id BIGINT NOT NULL,
                source_type VARCHAR(32) NOT NULL,
                amount INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_referral_rewards_guild_id ON referral_rewards (guild_id)"))
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_rewards_guild_referrer "
            "ON referral_rewards (guild_id, referrer_user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_rewards_guild_referred "
            "ON referral_rewards (guild_id, referred_user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_rewards_source_type "
            "ON referral_rewards (source_type)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_rewards_created_at "
            "ON referral_rewards (created_at)"
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS referral_settings (
                guild_id BIGINT PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT 0,
                signup_bonus_referrer INTEGER NOT NULL DEFAULT 0,
                signup_bonus_referred INTEGER NOT NULL DEFAULT 0,
                activity_percent FLOAT NOT NULL DEFAULT 0,
                activity_duration_days INTEGER NOT NULL DEFAULT 30,
                milestone_level INTEGER NOT NULL DEFAULT 0,
                milestone_bonus INTEGER NOT NULL DEFAULT 0,
                max_referrals_per_user INTEGER NOT NULL DEFAULT 0
            )
            """
        )
    )


async def migration_create_server_monthly_goals(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS server_monthly_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                month VARCHAR(7) NOT NULL,
                metric_type VARCHAR(32) NOT NULL,
                target_value FLOAT NOT NULL,
                reward_role_id BIGINT NOT NULL,
                min_user_contribution FLOAT NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                completed_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT ck_server_monthly_goals_metric_type
                    CHECK (metric_type IN ('voice_hours', 'messages', 'bets_volume'))
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_server_monthly_goals_guild_id "
            "ON server_monthly_goals (guild_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_server_monthly_goals_month "
            "ON server_monthly_goals (month)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_server_monthly_goals_guild_month "
            "ON server_monthly_goals (guild_id, month)"
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_server_monthly_goals_active_guild_month "
            "ON server_monthly_goals (guild_id, month) WHERE is_active = 1"
        )
    )


async def migration_create_referral_extended(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS referral_campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(128) NOT NULL,
                description TEXT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                start_at DATETIME NULL,
                end_at DATETIME NULL,
                signup_bonus_type VARCHAR(16) NOT NULL,
                signup_bonus_value FLOAT NOT NULL,
                revenue_share_percent FLOAT NOT NULL,
                min_user_lifetime_revenue INTEGER NOT NULL DEFAULT 0,
                allow_self_referral BOOLEAN NOT NULL DEFAULT 0,
                max_referrals_per_user INTEGER NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT ck_referral_campaigns_signup_bonus_type
                    CHECK (signup_bonus_type IN ('fixed', 'percent'))
            )
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS referral_seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(128) NOT NULL,
                start_at DATETIME NOT NULL,
                end_at DATETIME NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 0,
                reset_scores BOOLEAN NOT NULL DEFAULT 0
            )
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS referral_links_extended (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                owner_user_id BIGINT NOT NULL,
                code VARCHAR(64) NOT NULL,
                campaign_id INTEGER NOT NULL,
                season_id INTEGER NULL,
                total_invited INTEGER NOT NULL DEFAULT 0,
                total_active_invited INTEGER NOT NULL DEFAULT 0,
                total_revenue_generated INTEGER NOT NULL DEFAULT 0,
                total_reward_paid INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_referral_links_extended_code UNIQUE (code),
                CONSTRAINT uq_referral_links_extended_owner_campaign
                    UNIQUE (guild_id, owner_user_id, campaign_id),
                CONSTRAINT fk_referral_links_extended_campaign
                    FOREIGN KEY (campaign_id) REFERENCES referral_campaigns (id),
                CONSTRAINT fk_referral_links_extended_season
                    FOREIGN KEY (season_id) REFERENCES referral_seasons (id)
            )
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS referral_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                invited_user_id BIGINT NOT NULL,
                inviter_user_id BIGINT NOT NULL,
                referral_link_id INTEGER NOT NULL,
                campaign_id INTEGER NOT NULL,
                season_id INTEGER NULL,
                invited_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                activated_at DATETIME NULL,
                lifetime_revenue_generated INTEGER NOT NULL DEFAULT 0,
                total_reward_paid INTEGER NOT NULL DEFAULT 0,
                CONSTRAINT uq_referral_relationships_invited UNIQUE (guild_id, invited_user_id),
                CONSTRAINT fk_referral_relationships_link
                    FOREIGN KEY (referral_link_id) REFERENCES referral_links_extended (id),
                CONSTRAINT fk_referral_relationships_campaign
                    FOREIGN KEY (campaign_id) REFERENCES referral_campaigns (id),
                CONSTRAINT fk_referral_relationships_season
                    FOREIGN KEY (season_id) REFERENCES referral_seasons (id)
            )
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS referral_reward_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                inviter_user_id BIGINT NOT NULL,
                invited_user_id BIGINT NULL,
                campaign_id INTEGER NOT NULL,
                season_id INTEGER NULL,
                reward_type VARCHAR(32) NOT NULL,
                reward_amount INTEGER NOT NULL,
                source_amount INTEGER NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT ck_referral_reward_log_reward_type
                    CHECK (reward_type IN ('signup', 'revenue_share', 'seasonal_bonus')),
                CONSTRAINT fk_referral_reward_log_campaign
                    FOREIGN KEY (campaign_id) REFERENCES referral_campaigns (id),
                CONSTRAINT fk_referral_reward_log_season
                    FOREIGN KEY (season_id) REFERENCES referral_seasons (id)
            )
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS promo_codes_extended (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                campaign_id INTEGER NULL,
                code VARCHAR(64) NOT NULL,
                reward_type VARCHAR(16) NOT NULL,
                reward_value FLOAT NOT NULL,
                max_total_uses INTEGER NULL,
                max_uses_per_user INTEGER NULL,
                min_balance_required INTEGER NULL,
                min_account_age_days INTEGER NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                start_at DATETIME NULL,
                end_at DATETIME NULL,
                total_uses INTEGER NOT NULL DEFAULT 0,
                created_by_admin_id BIGINT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_promo_codes_extended_code UNIQUE (code),
                CONSTRAINT ck_promo_codes_extended_reward_type
                    CHECK (reward_type IN ('fixed', 'percent', 'multiplier')),
                CONSTRAINT fk_promo_codes_extended_campaign
                    FOREIGN KEY (campaign_id) REFERENCES referral_campaigns (id)
            )
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS promo_code_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_code_id INTEGER NOT NULL,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                used_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reward_amount INTEGER NOT NULL,
                CONSTRAINT uq_promo_code_usage_per_user UNIQUE (promo_code_id, user_id),
                CONSTRAINT fk_promo_code_usage_code
                    FOREIGN KEY (promo_code_id) REFERENCES promo_codes_extended (id)
            )
            """
        )
    )

    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_links_extended_guild_id "
            "ON referral_links_extended (guild_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_links_extended_owner_user_id "
            "ON referral_links_extended (owner_user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_links_extended_code "
            "ON referral_links_extended (code)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_relationships_guild_id "
            "ON referral_relationships (guild_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_relationships_inviter_user_id "
            "ON referral_relationships (inviter_user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_relationships_invited_user_id "
            "ON referral_relationships (invited_user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_reward_log_guild_id "
            "ON referral_reward_log (guild_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_reward_log_inviter_user_id "
            "ON referral_reward_log (inviter_user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_referral_reward_log_invited_user_id "
            "ON referral_reward_log (invited_user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_promo_codes_extended_guild_id "
            "ON promo_codes_extended (guild_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_promo_codes_extended_code "
            "ON promo_codes_extended (code)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_promo_code_usage_guild_id "
            "ON promo_code_usage (guild_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_promo_code_usage_user_id "
            "ON promo_code_usage (user_id)"
        )
    )


async def migration_create_pvp_duels(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pvp_duels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                challenger_id BIGINT NOT NULL,
                opponent_id BIGINT NOT NULL,
                amount INTEGER NOT NULL,
                fee_percent FLOAT NOT NULL DEFAULT 0,
                winner_id BIGINT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'pending'
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_pvp_duels_guild_id ON pvp_duels (guild_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_pvp_duels_guild_status ON pvp_duels (guild_id, status)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_pvp_duels_challenger_status ON pvp_duels (challenger_id, status)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_pvp_duels_opponent_status ON pvp_duels (opponent_id, status)"
        )
    )



async def migration_create_pvp_stats(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pvp_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                total_volume INTEGER NOT NULL DEFAULT 0,
                total_profit INTEGER NOT NULL DEFAULT 0,
                total_fees_paid INTEGER NOT NULL DEFAULT 0,
                rating INTEGER NOT NULL DEFAULT 1000,
                current_streak INTEGER NOT NULL DEFAULT 0,
                best_streak INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_pvp_stats_guild_user UNIQUE (guild_id, user_id)
            )
            """
        )
    )
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pvp_stats_guild_id ON pvp_stats (guild_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pvp_stats_user_id ON pvp_stats (user_id)"))
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_pvp_stats_guild_rating "
            "ON pvp_stats (guild_id, rating DESC)"
        )
    )


async def migration_add_pvp_user_fields(conn: AsyncConnection) -> None:
    columns_result = await conn.execute(text("PRAGMA table_info(users)"))
    column_names = {str(row[1]) for row in columns_result}
    if "last_pvp_at" not in column_names:
        await conn.execute(text("ALTER TABLE users ADD COLUMN last_pvp_at DATETIME"))
    if "total_pvp_wins" not in column_names:
        await conn.execute(text("ALTER TABLE users ADD COLUMN total_pvp_wins INTEGER NOT NULL DEFAULT 0"))
    if "total_pvp_losses" not in column_names:
        await conn.execute(text("ALTER TABLE users ADD COLUMN total_pvp_losses INTEGER NOT NULL DEFAULT 0"))
    if "total_pvp_volume" not in column_names:
        await conn.execute(text("ALTER TABLE users ADD COLUMN total_pvp_volume INTEGER NOT NULL DEFAULT 0"))


async def migration_create_pvp_seasons(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pvp_seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                season_number INTEGER NOT NULL,
                starts_at DATETIME NOT NULL,
                ends_at DATETIME NOT NULL,
                closed_at DATETIME NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                summary_message_id BIGINT NULL,
                summary_channel_id BIGINT NULL,
                CONSTRAINT uq_pvp_seasons_guild_number UNIQUE (guild_id, season_number)
            )
            """
        )
    )
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pvp_seasons_guild_id ON pvp_seasons (guild_id)"))

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pvp_season_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                season_id INTEGER NOT NULL,
                user_id BIGINT NOT NULL,
                final_rating INTEGER NOT NULL DEFAULT 1000,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                total_profit INTEGER NOT NULL DEFAULT 0,
                total_volume INTEGER NOT NULL DEFAULT 0,
                rank INTEGER NOT NULL,
                FOREIGN KEY(season_id) REFERENCES pvp_seasons(id) ON DELETE CASCADE
            )
            """
        )
    )
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pvp_season_results_guild_id ON pvp_season_results (guild_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pvp_season_results_user_id ON pvp_season_results (user_id)"))
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_pvp_season_results_guild_season_rank "
            "ON pvp_season_results (guild_id, season_id, rank)"
        )
    )




async def migration_create_guild_reports(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS guild_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                report_type VARCHAR(32) NOT NULL,
                period_start DATETIME NOT NULL,
                period_end DATETIME NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                channel_id BIGINT NOT NULL,
                message_id BIGINT NULL,
                payload_json JSON NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'posted',
                CONSTRAINT uq_guild_reports_period
                    UNIQUE (guild_id, report_type, period_start, period_end)
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_guild_reports_guild_id ON guild_reports (guild_id)"
        )
    )


async def migration_create_activity_events(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS activity_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                event_type VARCHAR(32) NOT NULL,
                value INTEGER NOT NULL DEFAULT 1,
                metadata_json JSON NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_activity_events_guild_created ON activity_events (guild_id, created_at)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_activity_events_user_created ON activity_events (user_id, created_at)"
        )
    )

async def migration_add_operational_indexes(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_users_guild_user ON users (guild_id, user_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_economy_transactions_guild_user_created "
            "ON economy_transactions (guild_id, user_id, created_at)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_betting_matches_status_close "
            "ON betting_matches (status, betting_close_at)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_betting_bets_match_status "
            "ON betting_bets (match_id, status)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_betting_bets_user_id ON betting_bets (user_id)"
        )
    )

MIGRATIONS: List[Migration] = [
    migration_create_all,
    migration_create_community_goals,
    migration_create_community_goal_participants,
    migration_create_economy_transactions,
    migration_add_monthly_analytics_support,
    migration_create_server_monthly_goals,
    migration_create_referrals,
    migration_create_referral_core,
    migration_create_referral_extended,
    migration_create_pvp_duels,
    migration_create_pvp_stats,
    migration_add_pvp_user_fields,
    migration_create_pvp_seasons,
    migration_create_guild_reports,
    migration_create_activity_events,
    migration_add_operational_indexes,
]
