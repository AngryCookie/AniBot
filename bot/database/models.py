from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class GuildConfig(Base):
    __tablename__ = "guilds"

    guild_id = Column(BigInteger, primary_key=True)
    server_rate = Column(Float, default=1.0)
    currency_name = Column(String(64), default="Coins")
    analytics_channel_id = Column(BigInteger, nullable=True)
    settings = Column(Text, default="{}")


class UserProfile(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("user_id", "guild_id", name="uq_user_guild"),
        Index("ix_users_guild_user", "guild_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    guild_id = Column(BigInteger, nullable=False)
    xp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    balance = Column(Integer, default=0)
    daily_income = Column(Integer, default=0)
    gambling_stats = Column(Text, default="{}")
    last_message_ts = Column(DateTime, default=None)
    last_message_content = Column(Text, default=None)
    last_daily_ts = Column(DateTime, default=None)
    voice_join_ts = Column(DateTime, default=None)
    daily_bet_amount = Column(Integer, default=0)
    daily_xp = Column(Integer, default=0)
    last_xp_date = Column(DateTime, default=None)
    last_pvp_at = Column(DateTime, default=None)
    total_pvp_wins = Column(Integer, default=0)
    total_pvp_losses = Column(Integer, default=0)
    total_pvp_volume = Column(Integer, default=0)


class EconomyLedger(Base):
    __tablename__ = "economy_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    guild_id = Column(BigInteger, nullable=False)
    amount = Column(Integer, nullable=False)
    type = Column(String(16), nullable=False)
    source = Column(String(100), nullable=False)
    timestamp = Column(DateTime, default=dt.datetime.utcnow, nullable=False)


class EconomyTransaction(Base):
    __tablename__ = "economy_transactions"
    __table_args__ = (
        Index("ix_economy_transactions_guild_user_created", "guild_id", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    balance_before = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    source = Column(String(128), nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False, index=True)


class Warning(Base):
    __tablename__ = "warnings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    moderator_id = Column(BigInteger, nullable=False)
    reason = Column(Text, default="No reason provided")
    created_at = Column(DateTime, default=dt.datetime.utcnow)


class ModLog(Base):
    __tablename__ = "mod_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    action = Column(String(64), nullable=False)
    user_id = Column(BigInteger, nullable=True)
    moderator_id = Column(BigInteger, nullable=False)
    reason = Column(Text, default="")
    created_at = Column(DateTime, default=dt.datetime.utcnow)


class ShopItem(Base):
    __tablename__ = "shop_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    base_price = Column(Integer, default=0)
    item_type = Column(String(32), default="role")
    role_id = Column(BigInteger, nullable=True)
    is_active = Column(Boolean, default=True)


class ShopPurchase(Base):
    __tablename__ = "shop_purchases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    item_id = Column(Integer, nullable=False)
    price = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)


class CustomCommand(Base):
    __tablename__ = "custom_commands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    name = Column(String(50), nullable=False)
    response = Column(Text, nullable=False)


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    name = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)


class LevelReward(Base):
    __tablename__ = "level_rewards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    level = Column(Integer, nullable=False)
    role_id = Column(BigInteger, nullable=True)
    reward_amount = Column(Integer, default=0)


class GuildLevelSettings(Base):
    __tablename__ = "guild_level_settings"

    guild_id = Column(BigInteger, primary_key=True)
    enabled = Column(Boolean, default=True)
    cooldown_seconds = Column(Integer, default=60)
    min_message_length = Column(Integer, default=6)
    max_xp_per_day = Column(Integer, default=500)
    xp_formula = Column(String(32), default="standard")
    rewards_currency = Column(Boolean, default=True)
    rewards_roles = Column(Boolean, default=True)
    blacklisted_channels = Column(Text, default="[]")


class GuildGamblingSettings(Base):
    __tablename__ = "guild_gambling_settings"

    guild_id = Column(BigInteger, primary_key=True)
    enabled = Column(Boolean, default=True)
    house_edge = Column(Float, default=0.05)
    tax_rate = Column(Float, default=0.1)
    daily_limit = Column(Integer, default=10000)
    max_bet = Column(Integer, default=1000)
    rate_limit_seconds = Column(Integer, default=5)


class GuildLogSettings(Base):
    __tablename__ = "guild_logs_settings"

    guild_id = Column(BigInteger, primary_key=True)
    log_channel_id = Column(BigInteger, nullable=True)
    log_moderation = Column(Boolean, default=True)
    log_economy = Column(Boolean, default=True)
    log_gambling = Column(Boolean, default=True)


class ReactionRole(Base):
    __tablename__ = "reaction_roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    emoji = Column(String(100), nullable=False)
    role_id = Column(BigInteger, nullable=False)


class GuildConfigHistory(Base):
    __tablename__ = "guild_config_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    actor_id = Column(BigInteger, nullable=True)
    category = Column(String(50), nullable=False)
    previous_settings = Column(Text, nullable=False)
    new_settings = Column(Text, nullable=False)
    reason = Column(Text, default="")
    created_at = Column(DateTime, default=dt.datetime.utcnow)


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    name = Column(String(64), primary_key=True)
    enabled = Column(Boolean, default=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    updated_at = Column(DateTime, default=dt.datetime.utcnow)


class GuildFeatureFlag(Base):
    __tablename__ = "guild_feature_flags"
    __table_args__ = (UniqueConstraint("guild_id", "flag_name", name="uq_guild_flag"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    flag_name = Column(String(64), nullable=False)
    enabled = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=dt.datetime.utcnow)


class MonthlyAnalyticsReport(Base):
    __tablename__ = "monthly_analytics_reports"
    __table_args__ = (
        UniqueConstraint("guild_id", "year", "month", name="uq_monthly_analytics_guild_period"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    report_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    autoposted_at = Column(DateTime, nullable=True)


class GuildReport(Base):
    __tablename__ = "guild_reports"
    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "report_type",
            "period_start",
            "period_end",
            name="uq_guild_reports_period",
        ),
        Index("ix_guild_reports_guild_id", "guild_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    report_type = Column(String(32), nullable=False, default="monthly")
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=True)
    payload_json = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False, default="posted")


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (
        Index("ix_activity_events_guild_created", "guild_id", "created_at"),
        Index("ix_activity_events_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    event_type = Column(String(32), nullable=False)
    value = Column(Integer, nullable=False, default=1)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)


class UserTrustProfile(Base):
    __tablename__ = "user_trust_profiles"
    __table_args__ = (UniqueConstraint("user_id", "guild_id", name="uq_trust_user_guild"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    guild_id = Column(BigInteger, nullable=False)
    trust_score = Column(Float, default=1.0)
    account_age_days = Column(Integer, default=0)
    activity_score = Column(Float, default=0.0)
    command_rate = Column(Float, default=0.0)
    warnings_count = Column(Integer, default=0)
    abuse_count = Column(Integer, default=0)
    last_updated = Column(DateTime, default=dt.datetime.utcnow)


class ShadowPenaltyLog(Base):
    __tablename__ = "shadow_penalties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    penalty_type = Column(String(64), nullable=False)
    multiplier = Column(Float, default=1.0)
    reason = Column(Text, default="")
    applied_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)


class CommunityGoal(Base):
    __tablename__ = "community_goals"
    __table_args__ = (
        Index("ix_community_goals_guild_status", "guild_id", "status"),
        Index(
            "uq_community_goals_active_guild",
            "guild_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    metric_type = Column(String(32), nullable=False)
    target_value = Column(Integer, nullable=False)
    current_value = Column(Integer, default=0, nullable=False)
    starts_at = Column(DateTime, nullable=False, index=True)
    ends_at = Column(DateTime, nullable=False, index=True)
    reward_role_id = Column(BigInteger, nullable=True)
    min_participation_threshold = Column(Integer, default=0, nullable=False)
    status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=dt.datetime.utcnow,
        onupdate=dt.datetime.utcnow,
        nullable=False,
    )


class CommunityGoalParticipant(Base):
    __tablename__ = "community_goal_participants"
    __table_args__ = (
        UniqueConstraint("goal_id", "user_id", name="uq_goal_participant"),
        Index("ix_goal_participants_goal_id", "goal_id"),
        Index("ix_goal_participants_user_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    goal_id = Column(Integer, ForeignKey("community_goals.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    contribution_value = Column(Integer, nullable=False, default=0)
    rewarded = Column(Boolean, nullable=False, default=False)


class ServerMonthlyGoal(Base):
    __tablename__ = "server_monthly_goals"
    __table_args__ = (
        Index("ix_server_monthly_goals_guild_month", "guild_id", "month"),
        Index(
            "uq_server_monthly_goals_active_guild_month",
            "guild_id",
            "month",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
        CheckConstraint(
            "metric_type IN ('voice_hours', 'messages', 'bets_volume')",
            name="ck_server_monthly_goals_metric_type",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    metric_type = Column(String(32), nullable=False)
    target_value = Column(Float, nullable=False)
    reward_role_id = Column(BigInteger, nullable=False)
    min_user_contribution = Column(Float, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)


class ReferralCode(Base):
    __tablename__ = "referral_codes"
    __table_args__ = (
        UniqueConstraint("guild_id", "code", name="uq_referral_code_guild_code"),
        Index("ix_referral_codes_guild_active", "guild_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    creator_user_id = Column(BigInteger, nullable=True, index=True)
    code = Column(String(64), nullable=False)
    reward_amount = Column(Integer, nullable=False)
    max_uses = Column(Integer, nullable=True)
    current_uses = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)


class ReferralUsage(Base):
    __tablename__ = "referral_usages"
    __table_args__ = (
        UniqueConstraint("guild_id", "invited_user_id", name="uq_referral_usage_invited_guild"),
        CheckConstraint("inviter_user_id != invited_user_id", name="ck_referral_not_self"),
        Index("ix_referral_usages_guild_inviter", "guild_id", "inviter_user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    inviter_user_id = Column(BigInteger, nullable=False)
    invited_user_id = Column(BigInteger, nullable=False)
    reward_amount = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False, index=True)


class ReferralLink(Base):
    __tablename__ = "referral_links"
    __table_args__ = (
        UniqueConstraint("guild_id", "referred_user_id", name="uq_referral_link_guild_referred"),
        CheckConstraint("referrer_user_id != referred_user_id", name="ck_referral_link_not_self"),
        Index("ix_referral_links_guild_referrer", "guild_id", "referrer_user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    referrer_user_id = Column(BigInteger, nullable=False, index=True)
    referred_user_id = Column(BigInteger, nullable=False, index=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)


class ReferralReward(Base):
    __tablename__ = "referral_rewards"
    __table_args__ = (
        Index("ix_referral_rewards_guild_referrer", "guild_id", "referrer_user_id"),
        Index("ix_referral_rewards_guild_referred", "guild_id", "referred_user_id"),
        Index("ix_referral_rewards_source_type", "source_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    referrer_user_id = Column(BigInteger, nullable=False)
    referred_user_id = Column(BigInteger, nullable=False)
    source_type = Column(String(32), nullable=False)
    amount = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False, index=True)


class ReferralSettings(Base):
    __tablename__ = "referral_settings"

    guild_id = Column(BigInteger, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    signup_bonus_referrer = Column(Integer, nullable=False, default=0)
    signup_bonus_referred = Column(Integer, nullable=False, default=0)
    activity_percent = Column(Float, nullable=False, default=0.0)
    activity_duration_days = Column(Integer, nullable=False, default=30)
    milestone_level = Column(Integer, nullable=False, default=0)
    milestone_bonus = Column(Integer, nullable=False, default=0)
    max_referrals_per_user = Column(Integer, nullable=False, default=0)


class PvpDuel(Base):
    __tablename__ = "pvp_duels"
    __table_args__ = (
        Index("ix_pvp_duels_guild_status", "guild_id", "status"),
        Index("ix_pvp_duels_challenger_status", "challenger_id", "status"),
        Index("ix_pvp_duels_opponent_status", "opponent_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    challenger_id = Column(BigInteger, nullable=False, index=True)
    opponent_id = Column(BigInteger, nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    fee_percent = Column(Float, nullable=False, default=0.0)
    winner_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False, default="pending")


class PvpStats(Base):
    __tablename__ = "pvp_stats"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", name="uq_pvp_stats_guild_user"),
        Index("ix_pvp_stats_guild_rating", "guild_id", "rating"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    total_volume = Column(Integer, nullable=False, default=0)
    total_profit = Column(Integer, nullable=False, default=0)
    total_fees_paid = Column(Integer, nullable=False, default=0)
    rating = Column(Integer, nullable=False, default=1000)
    current_streak = Column(Integer, nullable=False, default=0)
    best_streak = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime,
        default=dt.datetime.utcnow,
        onupdate=dt.datetime.utcnow,
        nullable=False,
    )


class PvpSeason(Base):
    __tablename__ = "pvp_seasons"
    __table_args__ = (
        UniqueConstraint("guild_id", "season_number", name="uq_pvp_seasons_guild_number"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    season_number = Column(Integer, nullable=False)
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    summary_message_id = Column(BigInteger, nullable=True)
    summary_channel_id = Column(BigInteger, nullable=True)


class PvpSeasonResult(Base):
    __tablename__ = "pvp_season_results"
    __table_args__ = (
        Index("ix_pvp_season_results_guild_season_rank", "guild_id", "season_id", "rank"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    season_id = Column(Integer, ForeignKey("pvp_seasons.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, nullable=False, index=True)
    final_rating = Column(Integer, nullable=False, default=1000)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    total_profit = Column(Integer, nullable=False, default=0)
    total_volume = Column(Integer, nullable=False, default=0)
    rank = Column(Integer, nullable=False)
