from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, case, func, select

from bot.betting.enums import BettingMatchStatus
from bot.betting.models import BettingBet, BettingMatch, BettingPayout, BettingTeam
from bot.betting.service import DEFAULT_BETTING_SETTINGS, BettingService, announce_match_result
from bot.database.models import GuildConfig

from .database import database
from .schemas_betting import (
    BettingAnalyticsDayPoint,
    BettingAnalyticsKpis,
    BettingAnalyticsLeaderboardsOut,
    BettingAnalyticsOverviewOut,
    BettingLeaderboardBiggestWinRow,
    BettingLeaderboardMatchRow,
    BettingLeaderboardProfitRow,
    BettingLeaderboardVolumeRow,
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


_ALLOWED_DAYS = {7, 30, 90}


def _normalize_days(days: int) -> int:
    if days not in _ALLOWED_DAYS:
        raise HTTPException(status_code=400, detail="days must be one of: 7, 30, 90")
    return days


def _window_bounds(days: int) -> tuple[dt.datetime, dt.datetime]:
    period_end = dt.datetime.utcnow()
    period_start = period_end - dt.timedelta(days=days - 1)
    period_start = period_start.replace(hour=0, minute=0, second=0, microsecond=0)
    return period_start, period_end


def _date_label(value: dt.datetime | dt.date) -> str:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    return value.isoformat()


async def _has_betting_payouts(session) -> bool:
    res = await session.execute(select(func.count(BettingPayout.id)))
    return int(res.scalar_one() or 0) > 0


def _fallback_payout_expr():
    return case((BettingBet.team_id == BettingMatch.winner_team_id, BettingBet.amount * BettingBet.odds), else_=0.0)


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


@router.get("/analytics/overview", response_model=BettingAnalyticsOverviewOut)
async def get_betting_analytics_overview(
    days: int = 30,
    guild_id: int = Depends(_require_admin_guild),
) -> BettingAnalyticsOverviewOut:
    days = _normalize_days(days)
    period_start, period_end = _window_bounds(days)

    async with database.session() as session:
        has_payout_rows = await _has_betting_payouts(session)
        if has_payout_rows:
            payout_expr = func.coalesce(func.sum(BettingPayout.payout_amount), 0.0)
            kpi_stmt = (
                select(
                    func.count(BettingBet.id),
                    func.count(func.distinct(BettingBet.user_id)),
                    func.coalesce(func.sum(BettingBet.amount), 0),
                    payout_expr,
                    func.coalesce(func.avg(BettingBet.amount), 0.0),
                    func.coalesce(func.avg(BettingBet.odds), 0.0),
                )
                .select_from(BettingBet)
                .outerjoin(BettingPayout, BettingPayout.bet_id == BettingBet.id)
                .where(
                    and_(
                        BettingBet.guild_id == guild_id,
                        BettingBet.created_at >= period_start,
                        BettingBet.created_at <= period_end,
                    )
                )
            )
            day_stmt = (
                select(
                    func.date(BettingBet.created_at).label("day"),
                    func.coalesce(func.sum(BettingBet.amount), 0).label("volume"),
                    payout_expr.label("payout"),
                    func.count(BettingBet.id).label("bets"),
                )
                .select_from(BettingBet)
                .outerjoin(BettingPayout, BettingPayout.bet_id == BettingBet.id)
                .where(
                    and_(
                        BettingBet.guild_id == guild_id,
                        BettingBet.created_at >= period_start,
                        BettingBet.created_at <= period_end,
                    )
                )
                .group_by(func.date(BettingBet.created_at))
                .order_by(func.date(BettingBet.created_at))
            )
        else:
            payout_expr = func.coalesce(func.sum(_fallback_payout_expr()), 0.0)
            base_where = and_(
                BettingBet.guild_id == guild_id,
                BettingBet.created_at >= period_start,
                BettingBet.created_at <= period_end,
            )
            kpi_stmt = (
                select(
                    func.count(BettingBet.id),
                    func.count(func.distinct(BettingBet.user_id)),
                    func.coalesce(func.sum(BettingBet.amount), 0),
                    payout_expr,
                    func.coalesce(func.avg(BettingBet.amount), 0.0),
                    func.coalesce(func.avg(BettingBet.odds), 0.0),
                )
                .select_from(BettingBet)
                .join(BettingMatch, BettingMatch.id == BettingBet.match_id)
                .where(base_where)
            )
            day_stmt = (
                select(
                    func.date(BettingBet.created_at).label("day"),
                    func.coalesce(func.sum(BettingBet.amount), 0).label("volume"),
                    payout_expr.label("payout"),
                    func.count(BettingBet.id).label("bets"),
                )
                .select_from(BettingBet)
                .join(BettingMatch, BettingMatch.id == BettingBet.match_id)
                .where(base_where)
                .group_by(func.date(BettingBet.created_at))
                .order_by(func.date(BettingBet.created_at))
            )

        bets_count, unique_bettors, total_volume, total_payout, avg_bet, avg_odds = (await session.execute(kpi_stmt)).one()
        rows = (await session.execute(day_stmt)).all()

    total_payout_val = float(total_payout or 0.0)
    total_volume_val = int(total_volume or 0)
    kpis = BettingAnalyticsKpis(
        bets_count=int(bets_count or 0),
        unique_bettors=int(unique_bettors or 0),
        total_volume=total_volume_val,
        total_payout=total_payout_val,
        net_sink=float(total_volume_val - total_payout_val),
        avg_bet=float(avg_bet or 0.0),
        avg_odds=float(avg_odds or 0.0),
    )
    series = [
        BettingAnalyticsDayPoint(
            day=_date_label(row.day),
            volume=int(row.volume or 0),
            payout=float(row.payout or 0.0),
            net=float((row.volume or 0) - (row.payout or 0.0)),
            bets=int(row.bets or 0),
        )
        for row in rows
    ]
    return BettingAnalyticsOverviewOut(days=days, period_start=period_start, period_end=period_end, kpis=kpis, timeseries=series)


@router.get("/analytics/leaderboards", response_model=BettingAnalyticsLeaderboardsOut)
async def get_betting_analytics_leaderboards(
    days: int = 30,
    guild_id: int = Depends(_require_admin_guild),
) -> BettingAnalyticsLeaderboardsOut:
    days = _normalize_days(days)
    period_start, period_end = _window_bounds(days)

    async with database.session() as session:
        has_payout_rows = await _has_betting_payouts(session)
        if has_payout_rows:
            payout_value = func.coalesce(func.sum(BettingPayout.payout_amount), 0.0)
            payout_single = func.coalesce(BettingPayout.payout_amount, 0.0)
        else:
            payout_single = _fallback_payout_expr()
            payout_value = func.coalesce(func.sum(_fallback_payout_expr()), 0.0)

        base_filter = and_(BettingBet.guild_id == guild_id, BettingBet.created_at >= period_start, BettingBet.created_at <= period_end)

        if has_payout_rows:
            top_volume_stmt = (
                select(BettingBet.user_id, func.coalesce(func.sum(BettingBet.amount), 0).label("volume"), func.count(BettingBet.id).label("bets"))
                .select_from(BettingBet)
                .where(base_filter)
                .group_by(BettingBet.user_id)
                .order_by(func.sum(BettingBet.amount).desc())
                .limit(10)
            )
            top_profit_stmt = (
                select(BettingBet.user_id, (payout_value - func.coalesce(func.sum(BettingBet.amount), 0)).label("profit"), func.count(BettingBet.id).label("bets"))
                .select_from(BettingBet)
                .outerjoin(BettingPayout, BettingPayout.bet_id == BettingBet.id)
                .where(base_filter)
                .group_by(BettingBet.user_id)
                .order_by((payout_value - func.coalesce(func.sum(BettingBet.amount), 0)).desc())
                .limit(10)
            )
            biggest_wins_stmt = (
                select(BettingBet.user_id, BettingBet.match_id, payout_single.label("payout"), BettingBet.amount, BettingBet.odds)
                .select_from(BettingBet)
                .outerjoin(BettingPayout, BettingPayout.bet_id == BettingBet.id)
                .where(base_filter)
                .order_by(payout_single.desc())
                .limit(10)
            )
        else:
            top_volume_stmt = (
                select(BettingBet.user_id, func.coalesce(func.sum(BettingBet.amount), 0).label("volume"), func.count(BettingBet.id).label("bets"))
                .select_from(BettingBet)
                .join(BettingMatch, BettingMatch.id == BettingBet.match_id)
                .where(base_filter)
                .group_by(BettingBet.user_id)
                .order_by(func.sum(BettingBet.amount).desc())
                .limit(10)
            )
            top_profit_stmt = (
                select(BettingBet.user_id, (payout_value - func.coalesce(func.sum(BettingBet.amount), 0)).label("profit"), func.count(BettingBet.id).label("bets"))
                .select_from(BettingBet)
                .join(BettingMatch, BettingMatch.id == BettingBet.match_id)
                .where(base_filter)
                .group_by(BettingBet.user_id)
                .order_by((payout_value - func.coalesce(func.sum(BettingBet.amount), 0)).desc())
                .limit(10)
            )
            biggest_wins_stmt = (
                select(BettingBet.user_id, BettingBet.match_id, payout_single.label("payout"), BettingBet.amount, BettingBet.odds)
                .select_from(BettingBet)
                .join(BettingMatch, BettingMatch.id == BettingBet.match_id)
                .where(base_filter)
                .order_by(payout_single.desc())
                .limit(10)
            )

        top_matches_stmt = (
            select(BettingBet.match_id, func.coalesce(func.sum(BettingBet.amount), 0).label("volume"), func.count(BettingBet.id).label("bets"))
            .where(base_filter)
            .group_by(BettingBet.match_id)
            .order_by(func.sum(BettingBet.amount).desc())
            .limit(10)
        )

        top_volume_rows = (await session.execute(top_volume_stmt)).all()
        top_profit_rows = (await session.execute(top_profit_stmt)).all()
        biggest_wins_rows = (await session.execute(biggest_wins_stmt)).all()
        top_match_rows = (await session.execute(top_matches_stmt)).all()

    return BettingAnalyticsLeaderboardsOut(
        top_by_volume=[BettingLeaderboardVolumeRow(user_id=int(r.user_id), volume=int(r.volume or 0), bets=int(r.bets or 0)) for r in top_volume_rows],
        top_by_profit=[BettingLeaderboardProfitRow(user_id=int(r.user_id), profit=float(r.profit or 0.0), bets=int(r.bets or 0)) for r in top_profit_rows],
        biggest_wins=[BettingLeaderboardBiggestWinRow(user_id=int(r.user_id), match_id=int(r.match_id), payout=float(r.payout or 0.0), bet_amount=int(r.amount or 0), odds=float(r.odds or 0.0)) for r in biggest_wins_rows],
        top_matches=[BettingLeaderboardMatchRow(match_id=int(r.match_id), volume=int(r.volume or 0), bets=int(r.bets or 0)) for r in top_match_rows],
    )


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
