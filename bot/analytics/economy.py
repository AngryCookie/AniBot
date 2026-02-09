from __future__ import annotations

from datetime import datetime, timedelta
import math

from sqlalchemy import case, distinct, func, select

from bot.database.models import EconomyLedger, UserProfile

SUPPORTED_PERIOD_DAYS = {7, 30, 90}


def _median(values: list[int]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return float(sorted_values[mid])
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2


def _top_10_percent_share(balances: list[int]) -> float:
    if not balances:
        return 0.0
    total_balance = sum(balances)
    if total_balance == 0:
        return 0.0
    top_count = max(1, math.ceil(len(balances) * 0.1))
    top_balances = sorted(balances, reverse=True)[:top_count]
    return sum(top_balances) / total_balance


async def build_economy_analytics(*, database, guild_id: int, period_days: int) -> dict:
    """Собрать read-only метрики экономики для гильдии за указанный период."""
    if period_days not in SUPPORTED_PERIOD_DAYS:
        raise ValueError("Unsupported analytics period")

    cutoff = datetime.utcnow() - timedelta(days=period_days)

    async with database.session() as session:
        flow_result = await session.execute(
            select(
                func.coalesce(
                    func.sum(
                        case((EconomyLedger.amount > 0, EconomyLedger.amount), else_=0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case((EconomyLedger.amount < 0, -EconomyLedger.amount), else_=0)
                    ),
                    0,
                ),
            ).where(
                (EconomyLedger.guild_id == guild_id)
                & (EconomyLedger.timestamp >= cutoff)
            )
        )
        total_created, total_spent = flow_result.one()

        # Балансы берём из UserProfile (текущее состояние кошельков).
        balances_result = await session.execute(
            select(UserProfile.balance).where(
                (UserProfile.guild_id == guild_id) & (UserProfile.balance > 0)
            )
        )
        balances = [int(row[0] or 0) for row in balances_result.all()]

        active_result = await session.execute(
            select(func.count(distinct(EconomyLedger.user_id))).where(
                (EconomyLedger.guild_id == guild_id)
                & (EconomyLedger.timestamp >= cutoff)
            )
        )
        active_users = int(active_result.scalar() or 0)

    total_users_with_balance = len(balances)
    average_balance = (sum(balances) / total_users_with_balance) if balances else 0.0
    median_balance = _median(balances)
    top_10_share = _top_10_percent_share(balances)

    net_flow = int(total_created) - int(total_spent)

    # Economy flow: сумма начислений (EconomyLedger.amount > 0) за период.
    created_value = float(total_created or 0)
    # Economy flow: сумма списаний (EconomyLedger.amount < 0) за период.
    spent_value = float(total_spent or 0)

    # Activity: пользователи с любыми записями в EconomyLedger за период.
    active_users_percent = (
        active_users / total_users_with_balance if total_users_with_balance else 0.0
    )

    # Health: отношение списаний к начислениям, защита от деления на ноль.
    sink_ratio = spent_value / max(created_value, 1)
    # Health: флаг инфляции, если чистый приток > 30% от начислений.
    inflation_flag = (net_flow / max(created_value, 1)) > 0.3

    return {
        "period_days": period_days,
        "created": created_value,
        "spent": spent_value,
        "net_flow": net_flow,
        "distribution": {
            "average_balance": average_balance,
            "median_balance": median_balance,
            "top_10_percent_share": top_10_share,
        },
        "activity": {
            "active_users": active_users,
            "active_users_percent": active_users_percent,
        },
        "health": {
            "sink_ratio": sink_ratio,
            "inflation_flag": inflation_flag,
        },
    }
