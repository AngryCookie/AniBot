from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.betting.enums import BettingMatchStatus
from bot.betting.models import BettingMatch, BettingTeam
from bot.betting.schedule import ScheduleGenerationError, generate_month_schedule
from bot.betting.service import BettingService

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
