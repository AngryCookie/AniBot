from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class GuildConfig(Base):
    __tablename__ = "guilds"

    guild_id = Column(BigInteger, primary_key=True)
    server_rate = Column(Float, default=1.0)
    currency_name = Column(String(64), default="Coins")
    settings = Column(Text, default="{}")


class UserProfile(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("user_id", "guild_id", name="uq_user_guild"),)

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


class EconomyLedger(Base):
    __tablename__ = "economy_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    guild_id = Column(BigInteger, nullable=False)
    amount = Column(Integer, nullable=False)
    type = Column(String(16), nullable=False)
    source = Column(String(100), nullable=False)
    timestamp = Column(DateTime, default=dt.datetime.utcnow, nullable=False)


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
