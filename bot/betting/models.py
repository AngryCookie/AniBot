from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum

from bot.betting.enums import BettingBetStatus, BettingMatchStatus
from bot.database.models import Base


class BettingTeam(Base):
    __tablename__ = "betting_teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), default="")
    base_power = Column(Integer, nullable=False)
    current_power = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class BettingMatch(Base):
    __tablename__ = "betting_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_a_id = Column(Integer, ForeignKey("betting_teams.id"), nullable=False)
    team_b_id = Column(Integer, ForeignKey("betting_teams.id"), nullable=False)
    odds_a = Column(Float, nullable=False)
    odds_b = Column(Float, nullable=False)
    betting_open_at = Column(DateTime, nullable=False)
    betting_close_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    winner_team_id = Column(Integer, ForeignKey("betting_teams.id"), nullable=True)
    status = Column(
        SAEnum(BettingMatchStatus, name="betting_match_status", native_enum=False),
        default=BettingMatchStatus.scheduled,
        nullable=False,
    )


class BettingBet(Base):
    __tablename__ = "betting_bets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    match_id = Column(Integer, ForeignKey("betting_matches.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("betting_teams.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    odds_at_bet = Column(Float, nullable=False)
    payout = Column(Integer, nullable=True)
    status = Column(
        SAEnum(BettingBetStatus, name="betting_bet_status", native_enum=False),
        default=BettingBetStatus.pending,
        nullable=False,
    )
