from __future__ import annotations

import calendar
import datetime as dt
import random

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from bot.betting.enums import BettingMatchStatus
from bot.betting.models import BettingMatch, BettingTeam
from bot.betting.service import BettingService

from .database import database
from .schemas_betting import (
    BettingMatchCreate,
    BettingMatchOut,
    BettingScheduleGenerateIn,
    BettingScheduleGenerateOut,
    BettingTeamCreate,
    BettingTeamOut,
    BettingTeamUpdate,
)
from .security import ensure_guild_access, fetch_user_guilds, get_access_token

router = APIRouter(prefix="/api/betting", tags=["betting"])


async def _require_admin_guild(
    guild_id: int, access_token: str = Depends(get_access_token)
) -> int:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    return guild_id


def _parse_month(month: str) -> tuple[dt.datetime, dt.datetime, int]:
    try:
        year_str, month_str = month.split("-")
        year = int(year_str)
        month_value = int(month_str)
    except (ValueError, AttributeError):
        raise ValueError("Некорректный формат месяца, ожидается YYYY-MM.")
    if not 1 <= month_value <= 12:
        raise ValueError("Месяц должен быть в диапазоне 01-12.")
    days_in_month = calendar.monthrange(year, month_value)[1]
    start = dt.datetime(year, month_value, 1)
    if month_value == 12:
        end = dt.datetime(year + 1, 1, 1)
    else:
        end = dt.datetime(year, month_value + 1, 1)
    return start, end, days_in_month


@router.get("/teams", response_model=list[BettingTeamOut])
async def list_teams(guild_id: int = Depends(_require_admin_guild)) -> list[BettingTeamOut]:
    async with database.session() as session:
        result = await session.execute(select(BettingTeam).order_by(BettingTeam.id))
        teams = result.scalars().all()
    return [
        BettingTeamOut(
            id=team.id,
            name=team.name,
            description=team.description,
            base_power=team.base_power,
            current_power=team.current_power,
            is_active=team.is_active,
        )
        for team in teams
    ]


@router.post("/teams", response_model=BettingTeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: BettingTeamCreate, guild_id: int = Depends(_require_admin_guild)
) -> BettingTeamOut:
    team = BettingTeam(
        name=payload.name,
        description=payload.description,
        base_power=payload.base_power,
        current_power=payload.base_power,
        is_active=payload.is_active,
    )
    async with database.session() as session:
        session.add(team)
        await session.commit()
        await session.refresh(team)
    return BettingTeamOut(
        id=team.id,
        name=team.name,
        description=team.description,
        base_power=team.base_power,
        current_power=team.current_power,
        is_active=team.is_active,
    )


@router.put("/teams/{team_id}", response_model=BettingTeamOut)
async def update_team(
    team_id: int,
    payload: BettingTeamUpdate,
    guild_id: int = Depends(_require_admin_guild),
) -> BettingTeamOut:
    async with database.session() as session:
        result = await session.execute(select(BettingTeam).where(BettingTeam.id == team_id))
        team = result.scalars().first()
        if team is None:
            raise HTTPException(status_code=404, detail="Команда не найдена.")
        team.description = payload.description
        team.base_power = payload.base_power
        team.current_power = payload.base_power
        team.is_active = payload.is_active
        await session.commit()
        await session.refresh(team)
    return BettingTeamOut(
        id=team.id,
        name=team.name,
        description=team.description,
        base_power=team.base_power,
        current_power=team.current_power,
        is_active=team.is_active,
    )


@router.post("/teams/reset-ratings", response_model=list[BettingTeamOut])
async def reset_team_ratings(
    guild_id: int = Depends(_require_admin_guild),
) -> list[BettingTeamOut]:
    async with database.session() as session:
        service = BettingService(session)
        try:
            teams = await service.reset_team_ratings()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await session.commit()
    return [
        BettingTeamOut(
            id=team.id,
            name=team.name,
            description=team.description,
            base_power=team.base_power,
            current_power=team.current_power,
            is_active=team.is_active,
        )
        for team in teams
    ]


@router.get("/matches", response_model=list[BettingMatchOut])
async def list_matches(
    status: BettingMatchStatus | None = None,
    start_date: dt.datetime | None = None,
    end_date: dt.datetime | None = None,
    guild_id: int = Depends(_require_admin_guild),
) -> list[BettingMatchOut]:
    query = select(BettingMatch).order_by(BettingMatch.betting_open_at.desc())
    if status:
        query = query.where(BettingMatch.status == status)
    if start_date:
        query = query.where(BettingMatch.betting_open_at >= start_date)
    if end_date:
        query = query.where(BettingMatch.betting_open_at <= end_date)
    async with database.session() as session:
        result = await session.execute(query)
        matches = result.scalars().all()
    return [
        BettingMatchOut(
            id=match.id,
            team_a_id=match.team_a_id,
            team_b_id=match.team_b_id,
            odds_a=match.odds_a,
            odds_b=match.odds_b,
            betting_open_at=match.betting_open_at,
            betting_close_at=match.betting_close_at,
            resolved_at=match.resolved_at,
            winner_team_id=match.winner_team_id,
            status=match.status,
        )
        for match in matches
    ]


@router.post("/matches", response_model=BettingMatchOut, status_code=status.HTTP_201_CREATED)
async def create_match(
    payload: BettingMatchCreate, guild_id: int = Depends(_require_admin_guild)
) -> BettingMatchOut:
    async with database.session() as session:
        service = BettingService(session)
        try:
            match = await service.create_match(
                team_a_id=payload.team_a_id,
                team_b_id=payload.team_b_id,
                betting_open_at=payload.betting_open_at,
                betting_close_at=payload.betting_close_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await session.commit()
        await session.refresh(match)
    return BettingMatchOut(
        id=match.id,
        team_a_id=match.team_a_id,
        team_b_id=match.team_b_id,
        odds_a=match.odds_a,
        odds_b=match.odds_b,
        betting_open_at=match.betting_open_at,
        betting_close_at=match.betting_close_at,
        resolved_at=match.resolved_at,
        winner_team_id=match.winner_team_id,
        status=match.status,
    )


@router.post("/matches/{match_id}/resolve", response_model=BettingMatchOut)
async def resolve_match(
    match_id: int, guild_id: int = Depends(_require_admin_guild)
) -> BettingMatchOut:
    async with database.session() as session:
        service = BettingService(session)
        try:
            match = await service.resolve_match(
                guild_id=guild_id, match_id=match_id, now=dt.datetime.utcnow()
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await session.commit()
        await session.refresh(match)
    return BettingMatchOut(
        id=match.id,
        team_a_id=match.team_a_id,
        team_b_id=match.team_b_id,
        odds_a=match.odds_a,
        odds_b=match.odds_b,
        betting_open_at=match.betting_open_at,
        betting_close_at=match.betting_close_at,
        resolved_at=match.resolved_at,
        winner_team_id=match.winner_team_id,
        status=match.status,
    )


@router.post("/schedule/generate", response_model=BettingScheduleGenerateOut)
async def generate_schedule(
    payload: BettingScheduleGenerateIn,
    guild_id: int = Depends(_require_admin_guild),
) -> BettingScheduleGenerateOut:
    try:
        month_start, month_end, days_in_month = _parse_month(payload.month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    open_offset = dt.timedelta(minutes=payload.betting_open_offset_minutes)
    close_offset = dt.timedelta(minutes=payload.betting_close_offset_minutes)
    if month_start + close_offset <= month_start + open_offset:
        raise HTTPException(
            status_code=400, detail="Окно ставок должно закрываться позже открытия."
        )
    async with database.session() as session:
        result = await session.execute(
            select(BettingMatch.id).where(
                (BettingMatch.betting_open_at >= month_start)
                & (BettingMatch.betting_open_at < month_end)
            )
        )
        if result.first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Расписание на этот месяц уже существует.",
            )
        result = await session.execute(
            select(BettingTeam).where(BettingTeam.is_active.is_(True))
        )
        teams = list(result.scalars().all())
        if len(teams) < 2:
            raise HTTPException(
                status_code=400,
                detail="Для генерации расписания нужны минимум две активные команды.",
            )
        max_matches_per_day = len(teams) // 2
        if payload.matches_per_day > max_matches_per_day:
            raise HTTPException(
                status_code=400,
                detail="Слишком много матчей в день для текущего числа команд.",
            )
        service = BettingService(session)
        total_matches = 0
        for day in range(1, days_in_month + 1):
            day_start = dt.datetime(month_start.year, month_start.month, day)
            available = teams[:]
            random.shuffle(available)
            pairs = [
                (available[i], available[i + 1])
                for i in range(0, payload.matches_per_day * 2, 2)
            ]
            for team_a, team_b in pairs:
                await service.create_match(
                    team_a_id=team_a.id,
                    team_b_id=team_b.id,
                    betting_open_at=day_start + open_offset,
                    betting_close_at=day_start + close_offset,
                )
                total_matches += 1
        await session.commit()
    return BettingScheduleGenerateOut(
        month=payload.month,
        matches_created=total_matches,
        days_scheduled=days_in_month,
    )
