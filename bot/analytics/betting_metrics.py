from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import EconomyTransaction

SUPPORTED_PERIODS = {7, 30, 90}


def _validate_period(period_days: int) -> None:
    if period_days not in SUPPORTED_PERIODS:
        raise ValueError("period_days must be one of: 7, 30, 90")


async def get_betting_metrics(session: AsyncSession, guild_id: int, period_days: int) -> dict:
    """Build betting-related metrics using immutable economy transactions.

    The implementation intentionally reuses transaction types:
    - ``bet_placement`` for stake volume
    - ``bet_win`` for user payouts
    """
    _validate_period(period_days)
    cutoff = datetime.utcnow() - timedelta(days=period_days)

    result = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            (EconomyTransaction.type == "bet_placement")
                            & (EconomyTransaction.amount < 0),
                            -EconomyTransaction.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("total_bets_amount"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (EconomyTransaction.type == "bet_win")
                            & (EconomyTransaction.amount > 0),
                            EconomyTransaction.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("total_won_amount"),
            func.coalesce(
                func.count(
                    case(
                        (EconomyTransaction.type == "bet_placement", EconomyTransaction.id),
                        else_=None,
                    )
                ),
                0,
            ).label("bets_count"),
            func.coalesce(
                func.count(
                    case((EconomyTransaction.type == "bet_win", EconomyTransaction.id), else_=None)
                ),
                0,
            ).label("won_bets_count"),
        ).where(
            (EconomyTransaction.guild_id == guild_id)
            & (EconomyTransaction.created_at >= cutoff)
        )
    )

    row = result.one()
    total_bets_amount = int(row.total_bets_amount or 0)
    total_won_amount = int(row.total_won_amount or 0)
    bets_count = int(row.bets_count or 0)
    won_bets_count = int(row.won_bets_count or 0)

    total_lost_amount = max(total_bets_amount - total_won_amount, 0)
    house_net = total_lost_amount - total_won_amount
    avg_bet = (total_bets_amount / bets_count) if bets_count else 0.0
    win_rate = (won_bets_count / bets_count) if bets_count else 0.0

    return {
        "total_bets_amount": total_bets_amount,
        "total_won_amount": total_won_amount,
        "total_lost_amount": total_lost_amount,
        "house_net": house_net,
        "bets_count": bets_count,
        "avg_bet": avg_bet,
        "win_rate": win_rate,
    }
