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


class BettingPowerDriftMomentumSettings(BaseModel):
    enabled: bool = False
    window_matches: int = Field(10, ge=1, le=100)
    win_influence_percent: float = Field(2, ge=0, le=20)


class BettingPowerDriftSettings(BaseModel):
    enabled: bool = True
    timezone: str = Field("UTC", min_length=1, max_length=64)
    tick: str = Field("daily", pattern="^daily$")
    max_deviation_percent: float = Field(15, ge=1, le=100)
    daily_noise_percent: float = Field(3, ge=0, le=100)
    mean_reversion: float = Field(0.20, ge=0, le=1)
    momentum: BettingPowerDriftMomentumSettings = Field(default_factory=BettingPowerDriftMomentumSettings)


class BettingPowerDriftTeamLogRow(BaseModel):
    team_id: int
    team_name: str
    base_power: float
    current_power: float
    deviation_percent: float
    last_delta: float


class BettingPowerDriftLogsOut(BaseModel):
    day: str
    teams: list[BettingPowerDriftTeamLogRow]


class BettingSettings(BaseModel):
    enabled: bool = True
    announce_channel_id: int | None = None
    min_bet_default: int = Field(50, ge=1, le=1_000_000)
    max_bet_default: int = Field(5000, ge=1, le=1_000_000)
    odds: BettingSettingsOdds = Field(default_factory=BettingSettingsOdds)
    resolve: BettingSettingsResolve = Field(default_factory=BettingSettingsResolve)
    scheduling: "BettingSchedulingSettings" = Field(default_factory=lambda: BettingSchedulingSettings())
    power_drift: BettingPowerDriftSettings = Field(default_factory=BettingPowerDriftSettings)



class BettingSchedulingMonthTemplate(BaseModel):
    days_of_week: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7], min_length=1, max_length=7)
    matches_per_day: int = Field(1, ge=1, le=24)
    start_hour: int = Field(18, ge=0, le=23)
    betting_open_minutes_before: int = Field(120, ge=1, le=10_000)
    betting_close_minutes_before: int = Field(10, ge=0, le=10_000)


class BettingSchedulingPairingRules(BaseModel):
    avoid_same_pair_days: int = Field(14, ge=0, le=365)
    prefer_active_teams: bool = True
    min_active_teams: int = Field(4, ge=2, le=128)




class BettingSchedulingAutoApply(BaseModel):
    enabled: bool = True
    horizon_days: int = Field(14, ge=1, le=90)
    run_every_minutes: int = Field(30, ge=1, le=1440)

class BettingSchedulingSettings(BaseModel):
    enabled: bool = True
    auto_apply: BettingSchedulingAutoApply = Field(default_factory=BettingSchedulingAutoApply)
    timezone: str = Field("UTC", min_length=1, max_length=64)
    month_template: BettingSchedulingMonthTemplate = Field(default_factory=BettingSchedulingMonthTemplate)
    pairing_rules: BettingSchedulingPairingRules = Field(default_factory=BettingSchedulingPairingRules)


class BettingGeneratedMatchOut(BaseModel):
    date_time_local: dt.datetime
    betting_open_at_utc: dt.datetime
    betting_close_at_utc: dt.datetime
    team_a_id: int
    team_b_id: int
    seed_key: str


class BettingScheduleApplyOut(BaseModel):
    inserted: int
    skipped_existing: int
    total_generated: int


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
