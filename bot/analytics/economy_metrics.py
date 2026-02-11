from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from bot.database.models import EconomyLedger, EconomyTransaction, UserProfile

SUPPORTED_PERIODS = {7, 30, 90}


def _validate_period(period_days: int) -> None:
    if period_days not in SUPPORTED_PERIODS:
        raise ValueError("period_days must be one of: 7, 30, 90")


def _median(values: list[int]) -> float:
    """Return median value for a list of integers."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return float(sorted_values[middle])
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2


def _date_to_iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)


async def get_economy_metrics(session: AsyncSession, guild_id: int, period_days: int) -> dict:
    """Build economy analytics snapshot for a guild and period.

    Notes:
    - Current balances are taken from ``UserProfile`` (state of wallets now).
    - Earned/spent are computed from ``EconomyTransaction`` in the requested period.
    """
    _validate_period(period_days)
    cutoff = datetime.utcnow() - timedelta(days=period_days)

    circulation_result = await session.execute(
        select(func.coalesce(func.sum(UserProfile.balance), 0)).where(
            UserProfile.guild_id == guild_id
        )
    )
    total_currency_in_circulation = int(circulation_result.scalar() or 0)

    flow_result = await session.execute(
        select(
            func.coalesce(
                func.sum(case((EconomyTransaction.amount > 0, EconomyTransaction.amount), else_=0)),
                0,
            ).label("total_earned"),
            func.coalesce(
                func.sum(case((EconomyTransaction.amount < 0, -EconomyTransaction.amount), else_=0)),
                0,
            ).label("total_spent"),
        ).where(
            (EconomyTransaction.guild_id == guild_id)
            & (EconomyTransaction.created_at >= cutoff)
        )
    )
    flow_row = flow_result.one()

    balances_result = await session.execute(
        select(UserProfile.balance).where(UserProfile.guild_id == guild_id)
    )
    balances = [int(balance or 0) for (balance,) in balances_result.all()]

    top_result = await session.execute(
        select(UserProfile.user_id, UserProfile.balance)
        .where(UserProfile.guild_id == guild_id)
        .order_by(UserProfile.balance.desc(), UserProfile.user_id.asc())
        .limit(10)
    )
    top_balances = [
        {"user_id": int(user_id), "balance": int(balance or 0)}
        for user_id, balance in top_result.all()
    ]

    return {
        "total_currency_in_circulation": total_currency_in_circulation,
        "total_earned": int(flow_row.total_earned or 0),
        "total_spent": int(flow_row.total_spent or 0),
        "median_balance": _median(balances),
        "top_balances": top_balances,
    }


async def get_economy_daily_flow(session: AsyncSession, guild_id: int, period_days: int) -> dict:
    """Return earned/spent day-by-day time-series for the selected period."""
    _validate_period(period_days)
    cutoff = datetime.utcnow() - timedelta(days=period_days)

    date_col = func.date(EconomyLedger.timestamp).label("date")
    ledger_stmt = (
        select(
            date_col,
            func.coalesce(
                func.sum(case((EconomyLedger.amount > 0, EconomyLedger.amount), else_=0)),
                0,
            ).label("earned"),
            func.coalesce(
                func.sum(case((EconomyLedger.amount < 0, -EconomyLedger.amount), else_=0)),
                0,
            ).label("spent"),
        )
        .where((EconomyLedger.guild_id == guild_id) & (EconomyLedger.timestamp >= cutoff))
        .group_by(date_col)
        .order_by(date_col.asc())
    )

    try:
        result = await session.execute(ledger_stmt)
        rows = result.all()
    except SQLAlchemyError:
        tx_date_col = func.date(EconomyTransaction.created_at).label("date")
        tx_stmt = (
            select(
                tx_date_col,
                func.coalesce(
                    func.sum(case((EconomyTransaction.amount > 0, EconomyTransaction.amount), else_=0)),
                    0,
                ).label("earned"),
                func.coalesce(
                    func.sum(case((EconomyTransaction.amount < 0, -EconomyTransaction.amount), else_=0)),
                    0,
                ).label("spent"),
            )
            .where(
                (EconomyTransaction.guild_id == guild_id)
                & (EconomyTransaction.created_at >= cutoff)
            )
            .group_by(tx_date_col)
            .order_by(tx_date_col.asc())
        )
        tx_result = await session.execute(tx_stmt)
        rows = tx_result.all()

    daily_earned = [{"date": _date_to_iso(row.date), "amount": int(row.earned or 0)} for row in rows]
    daily_spent = [{"date": _date_to_iso(row.date), "amount": int(row.spent or 0)} for row in rows]

    return {
        "daily_earned": daily_earned,
        "daily_spent": daily_spent,
    }
