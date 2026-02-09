from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from bot.betting.enums import BettingMatchStatus


class BettingTeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=255)
    base_power: int = Field(..., ge=1, le=10000)
    is_active: bool = True


class BettingTeamUpdate(BaseModel):
    description: str = Field("", max_length=255)
    base_power: int = Field(..., ge=1, le=10000)
    is_active: bool = True


class BettingTeamOut(BaseModel):
    id: int
    name: str
    description: str
    base_power: int
    current_power: int
    is_active: bool


class BettingMatchCreate(BaseModel):
    team_a_id: int
    team_b_id: int
    betting_open_at: dt.datetime
    betting_close_at: dt.datetime


class BettingMatchOut(BaseModel):
    id: int
    team_a_id: int
    team_b_id: int
    odds_a: float
    odds_b: float
    betting_open_at: dt.datetime
    betting_close_at: dt.datetime
    resolved_at: dt.datetime | None
    winner_team_id: int | None
    status: BettingMatchStatus


class BettingScheduleGenerateIn(BaseModel):
    month: str = Field(..., pattern=r"^\\d{4}-\\d{2}$")
    matches_per_day: int = Field(..., ge=1, le=20)
    betting_open_offset_minutes: int = Field(..., ge=-1440, le=1440)
    betting_close_offset_minutes: int = Field(..., ge=-1440, le=1440)


class BettingScheduleGenerateOut(BaseModel):
    month: str
    matches_created: int
    days_scheduled: int
