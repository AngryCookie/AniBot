from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from bot.betting.enums import BettingMatchStatus


class BettingTeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=255)
    base_power: float = Field(..., ge=1, le=10000)
    active: bool = True


class BettingTeamUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=255)
    base_power: float = Field(..., ge=1, le=10000)
    current_power: float = Field(..., ge=1, le=10000)
    active: bool = True


class BettingTeamOut(BaseModel):
    id: int
    guild_id: int
    name: str
    description: str
    base_power: float
    current_power: float
    active: bool


class BettingMatchCreate(BaseModel):
    team_a_id: int
    team_b_id: int
    betting_open_at: dt.datetime
    betting_close_at: dt.datetime
    min_bet: int | None = Field(default=None, ge=1, le=1_000_000)
    max_bet: int | None = Field(default=None, ge=1, le=1_000_000)
    announce_channel_id: int | None = None


class BettingMatchUpdate(BaseModel):
    betting_open_at: dt.datetime
    betting_close_at: dt.datetime
    min_bet: int = Field(..., ge=1, le=1_000_000)
    max_bet: int = Field(..., ge=1, le=1_000_000)
    announce_channel_id: int | None = None
    status: BettingMatchStatus


class BettingMatchOut(BaseModel):
    id: int
    guild_id: int
    team_a_id: int
    team_b_id: int
    odds_a: float
    odds_b: float
    betting_open_at: dt.datetime
    betting_close_at: dt.datetime
    resolved_at: dt.datetime | None
    winner_team_id: int | None
    min_bet: int
    max_bet: int
    announce_channel_id: int | None
    status: BettingMatchStatus


class BettingSettingsOdds(BaseModel):
    min: float = Field(1.20, ge=1.01, le=20.0)
    max: float = Field(3.50, ge=1.01, le=20.0)
    randomness: float = Field(0.35, ge=0.0, le=1.0)
    power_influence: float = Field(0.50, ge=0.0, le=2.0)


class BettingSettingsResolve(BaseModel):
    power_weight: float = Field(0.60, ge=0.0, le=2.0)


class BettingSettings(BaseModel):
    enabled: bool = True
    announce_channel_id: int | None = None
    min_bet_default: int = Field(50, ge=1, le=1_000_000)
    max_bet_default: int = Field(5000, ge=1, le=1_000_000)
    odds: BettingSettingsOdds = Field(default_factory=BettingSettingsOdds)
    resolve: BettingSettingsResolve = Field(default_factory=BettingSettingsResolve)


class BettingAnalyticsKpis(BaseModel):
    bets_count: int
    unique_bettors: int
    total_volume: int
    total_payout: float
    net_sink: float
    avg_bet: float
    avg_odds: float


class BettingAnalyticsDayPoint(BaseModel):
    day: str
    volume: int
    payout: float
    net: float
    bets: int


class BettingAnalyticsOverviewOut(BaseModel):
    days: int
    period_start: dt.datetime
    period_end: dt.datetime
    kpis: BettingAnalyticsKpis
    timeseries: list[BettingAnalyticsDayPoint]


class BettingLeaderboardVolumeRow(BaseModel):
    user_id: int
    volume: int
    bets: int


class BettingLeaderboardProfitRow(BaseModel):
    user_id: int
    profit: float
    bets: int


class BettingLeaderboardBiggestWinRow(BaseModel):
    user_id: int
    match_id: int
    payout: float
    bet_amount: int
    odds: float


class BettingLeaderboardMatchRow(BaseModel):
    match_id: int
    volume: int
    bets: int


class BettingAnalyticsLeaderboardsOut(BaseModel):
    top_by_volume: list[BettingLeaderboardVolumeRow]
    top_by_profit: list[BettingLeaderboardProfitRow]
    biggest_wins: list[BettingLeaderboardBiggestWinRow]
    top_matches: list[BettingLeaderboardMatchRow]
