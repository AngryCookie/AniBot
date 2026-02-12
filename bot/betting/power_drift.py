from __future__ import annotations

import datetime as dt
import hashlib
import random
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.betting.enums import BettingMatchStatus
from bot.betting.models import BettingMatch, BettingTeam, PowerDriftLog
from bot.betting.service import merge_power_drift_settings


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _seeded_random(guild_id: int, team_id: int, day: dt.date) -> random.Random:
    seed_raw = f"{guild_id}:{team_id}:{day.isoformat()}".encode("utf-8")
    digest = hashlib.sha256(seed_raw).hexdigest()
    return random.Random(int(digest[:16], 16))


async def _momentum_delta(
    session: AsyncSession,
    *,
    guild_id: int,
    team_id: int,
    base_power: float,
    window_matches: int,
    win_influence_percent: float,
    max_deviation_percent: float,
) -> tuple[float, int]:
    q = (
        select(BettingMatch.winner_team_id, BettingMatch.team_a_id, BettingMatch.team_b_id)
        .where(
            and_(
                BettingMatch.guild_id == guild_id,
                BettingMatch.status == BettingMatchStatus.resolved,
                (BettingMatch.team_a_id == team_id) | (BettingMatch.team_b_id == team_id),
            )
        )
        .order_by(BettingMatch.resolved_at.desc(), BettingMatch.id.desc())
        .limit(window_matches)
    )
    rows = (await session.execute(q)).all()
    score = 0
    for winner_team_id, _, _ in rows:
        score += 1 if int(winner_team_id or 0) == team_id else -1

    raw_delta = score * (win_influence_percent / 100.0) * base_power
    cap = (max_deviation_percent / 100.0) * base_power * 0.5
    return _clamp(raw_delta, -cap, cap), score


async def apply_daily_power_drift(
    session: AsyncSession,
    *,
    guild_id: int,
    day: dt.date,
    cfg: dict[str, Any],
) -> int:
    drift_cfg = merge_power_drift_settings((cfg or {}).get("power_drift", {}))
    if not bool(drift_cfg.get("enabled", True)):
        return 0

    max_dev = max(0.0, float(drift_cfg.get("max_deviation_percent", 15.0)))
    daily_noise_percent = max(0.0, float(drift_cfg.get("daily_noise_percent", 3.0)))
    mean_reversion = _clamp(float(drift_cfg.get("mean_reversion", 0.20)), 0.0, 1.0)
    momentum_cfg = drift_cfg.get("momentum", {}) if isinstance(drift_cfg, dict) else {}

    teams = (
        await session.execute(
            select(BettingTeam)
            .where(and_(BettingTeam.guild_id == guild_id, BettingTeam.active.is_(True)))
            .order_by(BettingTeam.id)
        )
    ).scalars().all()

    applied = 0
    for team in teams:
        existing = (
            await session.execute(
                select(PowerDriftLog).where(
                    and_(PowerDriftLog.guild_id == guild_id, PowerDriftLog.team_id == team.id, PowerDriftLog.day == day)
                )
            )
        ).scalars().first()
        if existing is not None:
            continue

        old_power = float(team.current_power)
        base_power = float(team.base_power)
        rng = _seeded_random(guild_id, int(team.id), day)
        noise = rng.uniform(-daily_noise_percent / 100.0, daily_noise_percent / 100.0) * base_power
        reversion = (base_power - old_power) * mean_reversion
        momentum_delta = 0.0
        momentum_score = 0

        if bool(momentum_cfg.get("enabled", False)):
            momentum_delta, momentum_score = await _momentum_delta(
                session,
                guild_id=guild_id,
                team_id=int(team.id),
                base_power=base_power,
                window_matches=max(1, int(momentum_cfg.get("window_matches", 10))),
                win_influence_percent=max(0.0, float(momentum_cfg.get("win_influence_percent", 2))),
                max_deviation_percent=max_dev,
            )

        min_power = base_power * (1.0 - max_dev / 100.0)
        max_power = base_power * (1.0 + max_dev / 100.0)
        new_power = _clamp(old_power + noise + reversion + momentum_delta, min_power, max_power)

        team.current_power = new_power
        session.add(
            PowerDriftLog(
                guild_id=guild_id,
                team_id=int(team.id),
                day=day,
                old_power=old_power,
                new_power=new_power,
                delta=new_power - old_power,
                reason_json={
                    "noise": noise,
                    "reversion": reversion,
                    "momentum": momentum_delta,
                    "momentum_score": momentum_score,
                    "seed": f"{guild_id}:{int(team.id)}:{day.isoformat()}",
                },
            )
        )
        applied += 1

    await session.flush()
    return applied


async def fetch_power_drift_logs(
    session: AsyncSession,
    *,
    guild_id: int,
    days: int,
) -> list[dict[str, Any]]:
    latest_day = (
        await session.execute(select(func.max(PowerDriftLog.day)).where(PowerDriftLog.guild_id == guild_id))
    ).scalar_one_or_none()

    if latest_day is None:
        rows = (
            await session.execute(
                select(BettingTeam).where(BettingTeam.guild_id == guild_id).order_by(BettingTeam.id)
            )
        ).scalars().all()
        return [
            {
                "team_id": t.id,
                "team_name": t.name,
                "base_power": float(t.base_power),
                "current_power": float(t.current_power),
                "deviation_percent": ((float(t.current_power) - float(t.base_power)) / float(t.base_power) * 100.0)
                if float(t.base_power)
                else 0.0,
                "last_delta": 0.0,
            }
            for t in rows
        ]

    min_day = latest_day - dt.timedelta(days=max(1, days) - 1)
    latest_log_subq = (
        select(PowerDriftLog.team_id, func.max(PowerDriftLog.day).label("last_day"))
        .where(and_(PowerDriftLog.guild_id == guild_id, PowerDriftLog.day >= min_day))
        .group_by(PowerDriftLog.team_id)
        .subquery()
    )

    q = (
        select(
            BettingTeam.id,
            BettingTeam.name,
            BettingTeam.base_power,
            BettingTeam.current_power,
            func.coalesce(PowerDriftLog.delta, 0.0).label("last_delta"),
        )
        .select_from(BettingTeam)
        .outerjoin(
            latest_log_subq,
            latest_log_subq.c.team_id == BettingTeam.id,
        )
        .outerjoin(
            PowerDriftLog,
            and_(PowerDriftLog.team_id == BettingTeam.id, PowerDriftLog.day == latest_log_subq.c.last_day),
        )
        .where(BettingTeam.guild_id == guild_id)
        .order_by(BettingTeam.id)
    )

    rows = (await session.execute(q)).all()
    return [
        {
            "team_id": int(team_id),
            "team_name": str(team_name),
            "base_power": float(base_power),
            "current_power": float(current_power),
            "deviation_percent": ((float(current_power) - float(base_power)) / float(base_power) * 100.0)
            if float(base_power)
            else 0.0,
            "last_delta": float(last_delta),
        }
        for team_id, team_name, base_power, current_power, last_delta in rows
    ]
