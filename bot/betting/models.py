from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy import Enum as SAEnum

from bot.betting.enums import BettingBetStatus, BettingMatchStatus
from bot.database.models import Base


class BettingTeam(Base):
    __tablename__ = "betting_teams"
    __table_args__ = (
        Index("ix_betting_teams_guild_id", "guild_id"),
        Index("ix_betting_teams_guild_active", "guild_id", "active"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(255), default="")
    base_power = Column(Float, nullable=False)
    current_power = Column(Float, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow, nullable=False)


class BettingMatch(Base):
    __tablename__ = "betting_matches"
    __table_args__ = (
        Index("ix_betting_matches_status_close", "status", "betting_close_at"),
        Index("ix_betting_matches_guild_match", "guild_id", "id"),
        Index("ix_betting_matches_guild_status", "guild_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    team_a_id = Column(Integer, ForeignKey("betting_teams.id"), nullable=False)
    team_b_id = Column(Integer, ForeignKey("betting_teams.id"), nullable=False)
    odds_a = Column(Float, nullable=False)
    odds_b = Column(Float, nullable=False)
    betting_open_at = Column(DateTime, nullable=False)
    betting_close_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    winner_team_id = Column(Integer, ForeignKey("betting_teams.id"), nullable=True)
    min_bet = Column(Integer, nullable=False, default=50)
    max_bet = Column(Integer, nullable=False, default=5000)
    announce_channel_id = Column(BigInteger, nullable=True)
    status = Column(
        SAEnum(BettingMatchStatus, name="betting_match_status", native_enum=False),
        default=BettingMatchStatus.scheduled,
        nullable=False,
    )
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow, nullable=False)


class BettingBet(Base):
    __tablename__ = "betting_bets"
    __table_args__ = (
        Index("ix_betting_bets_match_status", "match_id", "status"),
        Index("ix_betting_bets_user_id", "user_id"),
        Index("ix_betting_bets_guild_match", "guild_id", "match_id"),
        Index("ix_betting_bets_guild_user", "guild_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    match_id = Column(Integer, ForeignKey("betting_matches.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("betting_teams.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    odds = Column(Float, nullable=False)
    payout = Column(Integer, nullable=True)
    status = Column(
        SAEnum(BettingBetStatus, name="betting_bet_status", native_enum=False),
        default=BettingBetStatus.pending,
        nullable=False,
    )
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)


class BettingPayout(Base):
    __tablename__ = "betting_payouts"
    __table_args__ = (
        Index("ix_betting_payouts_guild_match", "guild_id", "match_id"),
        Index("ix_betting_payouts_guild_user", "guild_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    match_id = Column(Integer, ForeignKey("betting_matches.id"), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    bet_id = Column(Integer, ForeignKey("betting_bets.id"), nullable=False)
    payout_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
