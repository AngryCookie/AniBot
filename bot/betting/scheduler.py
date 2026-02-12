from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable
from zoneinfo import ZoneInfo

from bot.betting.power_drift import apply_daily_power_drift

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.betting.enums import BettingMatchStatus
from bot.betting.models import BettingBet, BettingMatch, BettingTeam
from bot.betting.schedule import ScheduleGenerationError, generate_month_schedule
from bot.betting.service import BettingService, announce_match_close, announce_match_open, announce_match_result

logger = logging.getLogger(__name__)


def _month_iter(start_date: dt.date, end_date: dt.date) -> Iterable[tuple[int, int]]:
    cursor = dt.date(start_date.year, start_date.month, 1)
    while cursor <= end_date:
        yield cursor.year, cursor.month
        if cursor.month == 12:
            cursor = dt.date(cursor.year + 1, 1, 1)
        else:
            cursor = dt.date(cursor.year, cursor.month + 1, 1)


async def ensure_scheduling_horizon(*, session: AsyncSession, guild_id: int, now: dt.datetime | None = None) -> int:
    service = BettingService(session)
    cfg = await service._get_betting_settings(guild_id)
    scheduling = cfg.get("scheduling", {})
    auto_apply = scheduling.get("auto_apply", {})

    if not bool(scheduling.get("enabled", True)) or not bool(auto_apply.get("enabled", True)):
        return 0

    timezone_name = str(scheduling.get("timezone", "UTC"))
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        logger.warning("Invalid timezone for betting scheduling", extra={"guild_id": guild_id, "timezone": timezone_name})
        return 0

    now_utc = now or dt.datetime.utcnow()
    now_local = now_utc.replace(tzinfo=dt.timezone.utc).astimezone(tz)
    start_date = now_local.date()
    horizon_days = max(1, int(auto_apply.get("horizon_days", 14)))
    end_date = start_date + dt.timedelta(days=horizon_days)

    teams = (
        await session.execute(select(BettingTeam).where(BettingTeam.guild_id == guild_id).order_by(BettingTeam.id))
    ).scalars().all()
    teams_list = list(teams)

    rows_to_insert: list[dict] = []
    for year, month in _month_iter(start_date, end_date):
        try:
            generated = generate_month_schedule(guild_id, year, month, scheduling, teams_list)
        except ScheduleGenerationError:
            logger.exception("Failed to generate betting schedule", extra={"guild_id": guild_id, "year": year, "month": month})
            continue

        for item in generated:
            local_date = item.date_time_local.date()
            if local_date < start_date or local_date > end_date:
                continue
            team_a = next((t for t in teams_list if t.id == item.team_a_id), None)
            team_b = next((t for t in teams_list if t.id == item.team_b_id), None)
            if team_a is None or team_b is None:
                continue
            odds_a, odds_b = service.generate_odds(team_a.current_power, team_b.current_power, cfg)
            rows_to_insert.append(
                {
                    "guild_id": guild_id,
                    "team_a_id": item.team_a_id,
                    "team_b_id": item.team_b_id,
                    "odds_a": odds_a,
                    "odds_b": odds_b,
                    "betting_open_at": item.betting_open_at_utc,
                    "betting_close_at": item.betting_close_at_utc,
                    "min_bet": int(cfg.get("min_bet_default", 50)),
                    "max_bet": int(cfg.get("max_bet_default", 5000)),
                    "announce_channel_id": cfg.get("announce_channel_id"),
                    "schedule_key": item.seed_key,
                    "status": BettingMatchStatus.scheduled,
                    "created_at": now_utc,
                    "updated_at": now_utc,
                }
            )

    if not rows_to_insert:
        return 0

    dialect_name = session.bind.dialect.name if session.bind is not None else ""
    if dialect_name == "postgresql":
        stmt = pg_insert(BettingMatch).values(rows_to_insert)
        stmt = stmt.on_conflict_do_nothing(index_elements=["guild_id", "schedule_key"])
        result = await session.execute(stmt)
        return int(result.rowcount or 0)
    if dialect_name == "sqlite":
        stmt = sqlite_insert(BettingMatch).values(rows_to_insert)
        stmt = stmt.on_conflict_do_nothing(index_elements=["guild_id", "schedule_key"])
        result = await session.execute(stmt)
        return int(result.rowcount or 0)

    inserted = 0
    for row in rows_to_insert:
        exists = (
            await session.execute(
                select(BettingMatch.id).where(
                    and_(BettingMatch.guild_id == guild_id, BettingMatch.schedule_key == row["schedule_key"])
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue
        session.add(BettingMatch(**row))
        inserted += 1
    return inserted


async def update_match_statuses(*, session: AsyncSession, guild_id: int, now: dt.datetime | None = None) -> tuple[int, int]:
    now_utc = now or dt.datetime.utcnow()
    opened_result = await session.execute(
        update(BettingMatch)
        .where(
            and_(
                BettingMatch.guild_id == guild_id,
                BettingMatch.status == BettingMatchStatus.scheduled,
                BettingMatch.betting_open_at <= now_utc,
            )
        )
        .values(status=BettingMatchStatus.open, updated_at=now_utc)
    )
    closed_result = await session.execute(
        update(BettingMatch)
        .where(
            and_(
                BettingMatch.guild_id == guild_id,
                BettingMatch.status == BettingMatchStatus.open,
                BettingMatch.betting_close_at <= now_utc,
            )
        )
        .values(status=BettingMatchStatus.closed, updated_at=now_utc)
    )
    return int(opened_result.rowcount or 0), int(closed_result.rowcount or 0)


async def run_betting_automation_tick(*, session: AsyncSession, bot, guild_id: int, now: dt.datetime | None = None) -> dict[str, int]:
    service = BettingService(session)
    cfg = await service._get_betting_settings(guild_id)
    automation = cfg.get("automation", {})
    now_utc = now or dt.datetime.utcnow()
    announce_channel_id = automation.get("announce_channel_id")

    teams = (await session.execute(select(BettingTeam).where(BettingTeam.guild_id == guild_id))).scalars().all()
    team_names = {t.id: t.name for t in teams}
    result = {"open_announced": 0, "close_announced": 0, "auto_resolved": 0}

    if bool(automation.get("announce_on_open", True)):
        open_matches = (
            await session.execute(
                select(BettingMatch)
                .where(
                    and_(
                        BettingMatch.guild_id == guild_id,
                        BettingMatch.status == BettingMatchStatus.open,
                        BettingMatch.open_announce_message_id.is_(None),
                        BettingMatch.betting_open_at <= now_utc,
                    )
                )
                .order_by(BettingMatch.betting_open_at.asc())
            )
        ).scalars().all()
        for match in open_matches:
            msg_id = await announce_match_open(
                bot=bot,
                match=match,
                team_a_name=team_names.get(match.team_a_id, str(match.team_a_id)),
                team_b_name=team_names.get(match.team_b_id, str(match.team_b_id)),
                channel_id=match.announce_channel_id or announce_channel_id,
                now=now_utc,
            )
            if msg_id:
                match.open_announce_message_id = msg_id
                result["open_announced"] += 1

    if bool(automation.get("announce_on_close", True)):
        delay_seconds = max(0, int(automation.get("close_message_delay_seconds", 0)))
        close_deadline = now_utc - dt.timedelta(seconds=delay_seconds)
        close_matches = (
            await session.execute(
                select(BettingMatch)
                .where(
                    and_(
                        BettingMatch.guild_id == guild_id,
                        BettingMatch.status == BettingMatchStatus.closed,
                        BettingMatch.close_announce_message_id.is_(None),
                        BettingMatch.betting_close_at <= close_deadline,
                    )
                )
                .order_by(BettingMatch.betting_close_at.asc())
            )
        ).scalars().all()
        for match in close_matches:
            stats = await session.execute(
                select(func.coalesce(func.count(BettingBet.id), 0), func.coalesce(func.sum(BettingBet.amount), 0)).where(
                    and_(BettingBet.guild_id == guild_id, BettingBet.match_id == match.id)
                )
            )
            bets_count, pool_total = stats.one()
            msg_id = await announce_match_close(
                bot=bot,
                match=match,
                team_a_name=team_names.get(match.team_a_id, str(match.team_a_id)),
                team_b_name=team_names.get(match.team_b_id, str(match.team_b_id)),
                bets_count=int(bets_count or 0),
                pool_total=int(pool_total or 0),
                channel_id=match.announce_channel_id or announce_channel_id,
            )
            if msg_id:
                match.close_announce_message_id = msg_id
                match.close_announced_at = now_utc
                result["close_announced"] += 1

    auto_resolve = automation.get("auto_resolve", {}) if isinstance(automation, dict) else {}
    if bool(auto_resolve.get("enabled", False)):
        delay_seconds = max(0, int(auto_resolve.get("delay_seconds", 300)))
        min_bets = max(0, int(auto_resolve.get("require_min_bets", 1)))
        resolve_deadline = now_utc - dt.timedelta(seconds=delay_seconds)
        candidates = (
            await session.execute(
                select(BettingMatch)
                .where(
                    and_(
                        BettingMatch.guild_id == guild_id,
                        BettingMatch.status == BettingMatchStatus.closed,
                        BettingMatch.resolved_at.is_(None),
                        BettingMatch.betting_close_at <= resolve_deadline,
                    )
                )
                .order_by(BettingMatch.betting_close_at.asc())
            )
        ).scalars().all()
        for match in candidates:
            match.auto_resolve_scheduled_at = match.auto_resolve_scheduled_at or now_utc
            stats = await session.execute(
                select(func.coalesce(func.count(BettingBet.id), 0), func.coalesce(func.sum(BettingBet.amount), 0)).where(
                    and_(BettingBet.guild_id == guild_id, BettingBet.match_id == match.id)
                )
            )
            bets_count, pool_total = stats.one()
            if int(bets_count or 0) < min_bets:
                continue
            try:
                resolved = await service.resolve_match(guild_id=guild_id, match_id=match.id, now=now_utc)
                payout_total = await session.scalar(
                    select(func.coalesce(func.sum(BettingBet.payout), 0)).where(and_(BettingBet.guild_id == guild_id, BettingBet.match_id == match.id))
                )
                winner_name = team_names.get(resolved.winner_team_id, "—")
                top_win = await session.scalar(
                    select(func.coalesce(func.max(BettingBet.payout), 0)).where(and_(BettingBet.guild_id == guild_id, BettingBet.match_id == match.id))
                )
                await announce_match_result(
                    bot=bot,
                    guild_id=guild_id,
                    match=resolved,
                    winner_name=winner_name,
                    volume_total=int(pool_total or 0),
                    payout_total=int(payout_total or 0),
                    top_win=int(top_win or 0),
                    channel_id=resolved.announce_channel_id or announce_channel_id,
                )
            except Exception:
                logger.exception("Auto resolve failed", extra={"guild_id": guild_id, "match_id": match.id})
                continue
            match.auto_resolved_at = now_utc
            result["auto_resolved"] += 1

    return result


async def apply_power_drift_for_guild(*, session: AsyncSession, guild_id: int, now: dt.datetime | None = None) -> int:
    service = BettingService(session)
    cfg = await service._get_betting_settings(guild_id)
    drift_cfg = cfg.get("power_drift", {})
    if not bool(drift_cfg.get("enabled", True)):
        return 0

    timezone_name = str(drift_cfg.get("timezone", "UTC"))
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        logger.warning("Invalid timezone for betting power drift", extra={"guild_id": guild_id, "timezone": timezone_name})
        return 0

    now_utc = now or dt.datetime.utcnow()
    today_local = now_utc.replace(tzinfo=dt.timezone.utc).astimezone(tz).date()
    return await apply_daily_power_drift(session, guild_id=guild_id, day=today_local, cfg=cfg)
