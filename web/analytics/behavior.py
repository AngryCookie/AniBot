from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy import func, select

from bot.database.models import EconomyLedger, UserProfile
from web.schemas import BehaviorAnalyticsResponse

PERIOD_DAYS = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
}


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    if percentile <= 0:
        return float(min(values))
    if percentile >= 100:
        return float(max(values))
    sorted_values = sorted(values)
    index = math.ceil((percentile / 100) * len(sorted_values)) - 1
    index = max(0, min(index, len(sorted_values) - 1))
    return float(sorted_values[index])


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return float(sorted_values[mid])
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2


async def build_behavior_analytics(*, database, guild_id: int, period: str) -> BehaviorAnalyticsResponse:
    days = PERIOD_DAYS.get(period)
    if days is None:
        raise ValueError("Unsupported analytics period")
    cutoff = datetime.utcnow() - timedelta(days=days)

    async with database.session() as session:
        total_result = await session.execute(
            select(func.count(UserProfile.id)).where(UserProfile.guild_id == guild_id)
        )
        users_total = total_result.scalar() or 0

        profile_result = await session.execute(
            select(
                UserProfile.user_id,
                UserProfile.balance,
                UserProfile.last_message_ts,
                UserProfile.last_xp_date,
            ).where(UserProfile.guild_id == guild_id)
        )
        profiles = profile_result.all()

        activity_result = await session.execute(
            select(EconomyLedger.user_id, func.count(EconomyLedger.id))
            .where(
                (EconomyLedger.guild_id == guild_id)
                & (EconomyLedger.timestamp >= cutoff)
            )
            .group_by(EconomyLedger.user_id)
        )
        activity_counts = {row[0]: row[1] for row in activity_result.all()}

    active_user_ids: set[int] = set()
    balances: list[int] = []
    activity_values: list[int] = []

    for row in profiles:
        user_id = int(row[0])
        balance = int(row[1] or 0)
        last_message_ts = row[2]
        last_xp_date = row[3]
        balances.append(balance)
        activity_count = int(activity_counts.get(user_id, 0))
        activity_values.append(activity_count)
        if activity_count > 0:
            active_user_ids.add(user_id)
            continue
        if last_message_ts and last_message_ts >= cutoff:
            active_user_ids.add(user_id)
            continue
        if last_xp_date and last_xp_date >= cutoff:
            active_user_ids.add(user_id)

    active_users = len(active_user_ids)
    inactive_users = max(users_total - active_users, 0)
    activity_rate = (active_users / users_total) if users_total else 0.0

    average_balance = (sum(balances) / len(balances)) if balances else None
    median_balance = _median(balances)

    total_balance = sum(balances)
    top_10_balance_share = None
    if balances:
        if total_balance == 0:
            top_10_balance_share = 0.0
        else:
            top_count = max(1, math.ceil(len(balances) * 0.1))
            top_balances = sorted(balances, reverse=True)[:top_count]
            top_10_balance_share = sum(top_balances) / total_balance

    total_activity = sum(activity_counts.values())
    top_10_activity_share = None
    if activity_values and total_activity > 0:
        top_count = max(1, math.ceil(len(activity_values) * 0.1))
        top_activity = sorted(activity_values, reverse=True)[:top_count]
        top_10_activity_share = sum(top_activity) / total_activity

    balance_p80 = _percentile(balances, 80)
    balance_p30 = _percentile(balances, 30)
    activity_p70 = _percentile(activity_values, 70) if total_activity > 0 else None

    rich_but_inactive = None
    if balance_p80 is not None:
        rich_but_inactive = sum(
            1
            for row in profiles
            if int(row[1] or 0) >= balance_p80 and int(row[0]) not in active_user_ids
        )

    active_but_poor = None
    if activity_p70 is not None and balance_p30 is not None:
        active_but_poor = sum(
            1
            for row in profiles
            if int(activity_counts.get(int(row[0]), 0)) >= activity_p70
            and int(row[1] or 0) <= balance_p30
        )

    return BehaviorAnalyticsResponse(
        period=period,
        users_total=users_total,
        active_users=active_users,
        inactive_users=inactive_users,
        activity_rate=activity_rate,
        segments={
            "new_users": None,
            "new_users_active": None,
            "new_users_inactive": None,
            "rich_but_inactive": rich_but_inactive,
            "active_but_poor": active_but_poor,
        },
        retention_rate=None,
        distribution={
            "median_balance": median_balance,
            "average_balance": average_balance,
            "top_10_balance_share": top_10_balance_share,
            "top_10_activity_share": top_10_activity_share,
        },
    )
