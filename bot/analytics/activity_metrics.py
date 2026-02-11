from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import UserProfile

SUPPORTED_PERIODS = {7, 30, 90}


def _validate_period(period_days: int) -> None:
    if period_days not in SUPPORTED_PERIODS:
        raise ValueError("period_days must be one of: 7, 30, 90")


def _date_to_iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)


async def get_activity_metrics(session: AsyncSession, guild_id: int, period_days: int) -> dict:
    """Build guild activity metrics for the requested period.

    Current schema does not include dedicated voice history/message event tables,
    therefore:
    - ``total_messages`` is based on users with recent message timestamps.
    - ``total_voice_minutes`` is returned as ``0`` until voice tracking table exists.
    """
    _validate_period(period_days)
    cutoff = datetime.utcnow() - timedelta(days=period_days)

    recent_messages_result = await session.execute(
        select(func.count(UserProfile.id)).where(
            (UserProfile.guild_id == guild_id)
            & (UserProfile.last_message_ts.is_not(None))
            & (UserProfile.last_message_ts >= cutoff)
        )
    )
    total_messages = int(recent_messages_result.scalar() or 0)

    active_users_result = await session.execute(
        select(func.count(UserProfile.id)).where(
            (UserProfile.guild_id == guild_id)
            & or_(
                (UserProfile.last_message_ts.is_not(None)) & (UserProfile.last_message_ts >= cutoff),
                (UserProfile.last_xp_date.is_not(None)) & (UserProfile.last_xp_date >= cutoff),
            )
        )
    )
    active_users_count = int(active_users_result.scalar() or 0)

    total_voice_minutes = 0
    avg_messages_per_user = (total_messages / active_users_count) if active_users_count else 0.0

    return {
        "total_messages": total_messages,
        "total_voice_minutes": total_voice_minutes,
        "active_users_count": active_users_count,
        "avg_messages_per_user": avg_messages_per_user,
    }


async def get_activity_daily_stats(session: AsyncSession, guild_id: int, period_days: int) -> dict:
    """Return daily message/voice activity aggregates for the selected period."""
    _validate_period(period_days)
    cutoff = datetime.utcnow() - timedelta(days=period_days)

    date_col = func.date(UserProfile.last_message_ts).label("date")
    result = await session.execute(
        select(date_col, func.count(UserProfile.id).label("messages"))
        .where(
            (UserProfile.guild_id == guild_id)
            & (UserProfile.last_message_ts.is_not(None))
            & (UserProfile.last_message_ts >= cutoff)
        )
        .group_by(date_col)
        .order_by(date_col.asc())
    )
    rows = result.all()

    return {
        "daily_messages": [
            {"date": _date_to_iso(row.date), "count": int(row.messages or 0)} for row in rows
        ],
        "daily_voice_minutes": [],
    }
