from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, func, select

from bot.betting.enums import BettingMatchStatus
from bot.betting.models import BettingBet, BettingMatch, BettingTeam
from bot.betting.service import DEFAULT_BETTING_SETTINGS, BettingService, announce_match_result
from bot.database.models import GuildConfig

from .database import database
from .schemas_betting import (
    BettingMatchCreate,
    BettingMatchOut,
    BettingMatchUpdate,
    BettingSettings,
    BettingTeamCreate,
    BettingTeamOut,
    BettingTeamUpdate,
)
from .security import ensure_guild_access, fetch_user_guilds, get_access_token

router = APIRouter(prefix="/api/guilds/{guild_id}/betting", tags=["betting"])


async def _require_admin_guild(guild_id: int, access_token: str = Depends(get_access_token)) -> int:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    return guild_id


def _to_team_out(team: BettingTeam) -> BettingTeamOut:
    return BettingTeamOut(
        id=team.id,
        guild_id=int(team.guild_id),
        name=team.name,
        description=team.description,
        base_power=team.base_power,
        current_power=team.current_power,
        active=team.active,
    )


def _to_match_out(match: BettingMatch) -> BettingMatchOut:
    return BettingMatchOut(
        id=match.id,
        guild_id=int(match.guild_id),
        team_a_id=match.team_a_id,
        team_b_id=match.team_b_id,
        odds_a=match.odds_a,
        odds_b=match.odds_b,
        betting_open_at=match.betting_open_at,
        betting_close_at=match.betting_close_at,
        resolved_at=match.resolved_at,
        winner_team_id=match.winner_team_id,
        min_bet=match.min_bet,
        max_bet=match.max_bet,
        announce_channel_id=match.announce_channel_id,
        status=match.status,
    )


@router.get("/settings", response_model=BettingSettings)
async def get_betting_settings(guild_id: int = Depends(_require_admin_guild)) -> BettingSettings:
    async with database.session() as session:
        cfg = await session.get(GuildConfig, guild_id)
    payload = {}
    if cfg and cfg.settings:
        try:
            payload = json.loads(cfg.settings)
        except json.JSONDecodeError:
            payload = {}
    data = dict(DEFAULT_BETTING_SETTINGS)
    data.update(payload.get("betting", {}))
    data["odds"] = {**DEFAULT_BETTING_SETTINGS["odds"], **data.get("odds", {})}
    data["resolve"] = {**DEFAULT_BETTING_SETTINGS["resolve"], **data.get("resolve", {})}
    return BettingSettings(**data)


@router.put("/settings", response_model=BettingSettings)
async def update_betting_settings(payload: BettingSettings, guild_id: int = Depends(_require_admin_guild)) -> BettingSettings:
    async with database.session() as session:
        cfg = await session.get(GuildConfig, guild_id)
        if cfg is None:
            cfg = GuildConfig(guild_id=guild_id)
            session.add(cfg)
        raw = {}
        if cfg.settings:
            try:
                raw = json.loads(cfg.settings)
            except json.JSONDecodeError:
                raw = {}
        raw["betting"] = payload.model_dump()
        cfg.settings = json.dumps(raw)
        await session.commit()
    return payload


@router.get("/teams", response_model=list[BettingTeamOut])
async def list_teams(guild_id: int = Depends(_require_admin_guild)) -> list[BettingTeamOut]:
    async with database.session() as session:
        result = await session.execute(
            select(BettingTeam).where(BettingTeam.guild_id == guild_id).order_by(BettingTeam.id)
        )
        teams = result.scalars().all()
    return [_to_team_out(team) for team in teams]


@router.post("/teams", response_model=BettingTeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(payload: BettingTeamCreate, guild_id: int = Depends(_require_admin_guild)) -> BettingTeamOut:
    team = BettingTeam(
        guild_id=guild_id,
        name=payload.name,
        description=payload.description,
        base_power=payload.base_power,
        current_power=payload.base_power,
        active=payload.active,
    )
    async with database.session() as session:
        session.add(team)
        await session.commit()
        await session.refresh(team)
    return _to_team_out(team)


@router.put("/teams/{team_id}", response_model=BettingTeamOut)
async def update_team(team_id: int, payload: BettingTeamUpdate, guild_id: int = Depends(_require_admin_guild)) -> BettingTeamOut:
    async with database.session() as session:
        team = (
            await session.execute(
                select(BettingTeam).where(and_(BettingTeam.id == team_id, BettingTeam.guild_id == guild_id))
            )
        ).scalars().first()
        if team is None:
            raise HTTPException(status_code=404, detail="Команда не найдена.")
        team.name = payload.name
        team.description = payload.description
        team.base_power = payload.base_power
        team.current_power = payload.current_power
        team.active = payload.active
        await session.commit()
        await session.refresh(team)
    return _to_team_out(team)


@router.delete("/teams/{team_id}")
async def delete_team(team_id: int, guild_id: int = Depends(_require_admin_guild)) -> dict[str, bool]:
    async with database.session() as session:
        team = (
            await session.execute(
                select(BettingTeam).where(and_(BettingTeam.id == team_id, BettingTeam.guild_id == guild_id))
            )
        ).scalars().first()
        if team is None:
            raise HTTPException(status_code=404, detail="Команда не найдена.")
        await session.delete(team)
        await session.commit()
    return {"ok": True}


@router.get("/matches", response_model=list[BettingMatchOut])
async def list_matches(
    guild_id: int = Depends(_require_admin_guild),
    status: BettingMatchStatus | None = None,
    start_date: dt.datetime | None = None,
    end_date: dt.datetime | None = None,
) -> list[BettingMatchOut]:
    async with database.session() as session:
        service = BettingService(session)
        matches = await service.list_matches(guild_id=guild_id, status=status, start_date=start_date, end_date=end_date)
    return [_to_match_out(match) for match in matches]


@router.post("/matches", response_model=BettingMatchOut, status_code=status.HTTP_201_CREATED)
async def create_match(payload: BettingMatchCreate, guild_id: int = Depends(_require_admin_guild)) -> BettingMatchOut:
    async with database.session() as session:
        service = BettingService(session)
        try:
            match = await service.create_match(
                guild_id=guild_id,
                team_a_id=payload.team_a_id,
                team_b_id=payload.team_b_id,
                betting_open_at=payload.betting_open_at,
                betting_close_at=payload.betting_close_at,
                min_bet=payload.min_bet,
                max_bet=payload.max_bet,
                announce_channel_id=payload.announce_channel_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await session.commit()
        await session.refresh(match)
    return _to_match_out(match)


@router.put("/matches/{match_id}", response_model=BettingMatchOut)
async def update_match(match_id: int, payload: BettingMatchUpdate, guild_id: int = Depends(_require_admin_guild)) -> BettingMatchOut:
    if payload.max_bet < payload.min_bet:
        raise HTTPException(status_code=400, detail="max_bet должен быть >= min_bet")
    async with database.session() as session:
        match = (
            await session.execute(
                select(BettingMatch).where(and_(BettingMatch.id == match_id, BettingMatch.guild_id == guild_id))
            )
        ).scalars().first()
        if match is None:
            raise HTTPException(status_code=404, detail="Матч не найден.")
        if payload.betting_close_at <= payload.betting_open_at:
            raise HTTPException(status_code=400, detail="Время закрытия должно быть позже открытия.")
        match.betting_open_at = payload.betting_open_at
        match.betting_close_at = payload.betting_close_at
        match.min_bet = payload.min_bet
        match.max_bet = payload.max_bet
        match.announce_channel_id = payload.announce_channel_id
        match.status = payload.status
        await session.commit()
        await session.refresh(match)
    return _to_match_out(match)


@router.delete("/matches/{match_id}")
async def delete_match(match_id: int, guild_id: int = Depends(_require_admin_guild)) -> dict[str, bool]:
    async with database.session() as session:
        match = (
            await session.execute(
                select(BettingMatch).where(and_(BettingMatch.id == match_id, BettingMatch.guild_id == guild_id))
            )
        ).scalars().first()
        if match is None:
            raise HTTPException(status_code=404, detail="Матч не найден.")
        await session.delete(match)
        await session.commit()
    return {"ok": True}


@router.post("/matches/{match_id}/resolve", response_model=BettingMatchOut)
async def resolve_match(request: Request, match_id: int, guild_id: int = Depends(_require_admin_guild)) -> BettingMatchOut:
    async with database.session() as session:
        service = BettingService(session)
        try:
            match = await service.resolve_match(guild_id=guild_id, match_id=match_id, now=dt.datetime.utcnow())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        winner_team = await session.get(BettingTeam, match.winner_team_id) if match.winner_team_id else None
        stats = await session.execute(
            select(func.coalesce(func.sum(BettingBet.amount), 0), func.coalesce(func.sum(BettingBet.payout), 0), func.coalesce(func.max(BettingBet.payout), 0)).where(
                and_(BettingBet.guild_id == guild_id, BettingBet.match_id == match.id)
            )
        )
        volume_total, payout_total, top_win = stats.one()
        await session.commit()
        await session.refresh(match)

    bot = getattr(request.app.state, "bot", None)
    settings = await get_betting_settings(guild_id)
    await announce_match_result(
        bot=bot,
        guild_id=guild_id,
        match=match,
        winner_name=winner_team.name if winner_team else "—",
        volume_total=int(volume_total or 0),
        payout_total=int(payout_total or 0),
        top_win=int(top_win or 0),
        channel_id=match.announce_channel_id or settings.announce_channel_id,
    )
    return _to_match_out(match)
