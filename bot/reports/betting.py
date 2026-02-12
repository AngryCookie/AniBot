from __future__ import annotations

import datetime as dt

from sqlalchemy import case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.betting.enums import BettingBetStatus, BettingMatchStatus
from bot.betting.models import BettingBet, BettingMatch, BettingPayout


async def build_betting_report_metrics(
    session: AsyncSession,
    *,
    guild_id: int,
    period_start: dt.datetime,
    period_end: dt.datetime,
) -> dict:
    """Build betting metrics for a period.

    Attribution rule: a bet belongs to the period where its match was resolved
    (``BettingMatch.resolved_at`` in ``[period_start, period_end)``).
    """

    payout_subquery = (
        select(
            BettingPayout.bet_id.label("bet_id"),
            func.coalesce(func.sum(BettingPayout.payout_amount), 0).label("payout"),
        )
        .where(BettingPayout.guild_id == guild_id)
        .group_by(BettingPayout.bet_id)
        .subquery()
    )

    computed_payout = case(
        (payout_subquery.c.payout.is_not(None), payout_subquery.c.payout),
        (
            BettingBet.status == BettingBetStatus.won,
            BettingBet.amount * BettingBet.odds,
        ),
        else_=literal(0.0),
    )

    scoped_bets = (
        select(
            BettingBet.id.label("bet_id"),
            BettingBet.user_id.label("user_id"),
            BettingBet.match_id.label("match_id"),
            BettingBet.amount.label("amount"),
            BettingBet.odds.label("odds"),
            func.coalesce(computed_payout, 0).label("payout"),
        )
        .select_from(BettingBet)
        .join(BettingMatch, BettingMatch.id == BettingBet.match_id)
        .outerjoin(payout_subquery, payout_subquery.c.bet_id == BettingBet.id)
        .where(
            (BettingBet.guild_id == guild_id)
            & (BettingMatch.guild_id == guild_id)
            & (BettingMatch.status == BettingMatchStatus.resolved)
            & (BettingMatch.resolved_at.is_not(None))
            & (BettingMatch.resolved_at >= period_start)
            & (BettingMatch.resolved_at < period_end)
        )
        .subquery()
    )

    totals = await session.execute(
        select(
            func.coalesce(func.count(scoped_bets.c.bet_id), 0),
            func.coalesce(func.count(func.distinct(scoped_bets.c.user_id)), 0),
            func.coalesce(func.sum(scoped_bets.c.amount), 0),
            func.coalesce(func.sum(scoped_bets.c.payout), 0),
            func.coalesce(func.sum(scoped_bets.c.payout - scoped_bets.c.amount), 0),
        )
    )
    bets_count, unique_bettors, total_volume, total_payout, users_net_profit = totals.one()

    biggest_win_row = (
        (
            await session.execute(
                select(
                    scoped_bets.c.user_id,
                    scoped_bets.c.match_id,
                    scoped_bets.c.amount,
                    scoped_bets.c.odds,
                    scoped_bets.c.payout,
                )
                .where(scoped_bets.c.payout > 0)
                .order_by(scoped_bets.c.payout.desc(), scoped_bets.c.bet_id.asc())
                .limit(1)
            )
        )
        .mappings()
        .first()
    )

    top_bettors_rows = (
        (
            await session.execute(
                select(
                    scoped_bets.c.user_id,
                    func.coalesce(func.sum(scoped_bets.c.amount), 0).label("volume"),
                )
                .group_by(scoped_bets.c.user_id)
                .order_by(func.sum(scoped_bets.c.amount).desc())
                .limit(5)
            )
        )
        .mappings()
        .all()
    )

    top_profitable_rows = (
        (
            await session.execute(
                select(
                    scoped_bets.c.user_id,
                    func.coalesce(func.sum(scoped_bets.c.payout - scoped_bets.c.amount), 0).label("net_profit"),
                )
                .group_by(scoped_bets.c.user_id)
                .order_by(func.sum(scoped_bets.c.payout - scoped_bets.c.amount).desc())
                .limit(5)
            )
        )
        .mappings()
        .all()
    )

    total_volume_i = int(total_volume or 0)
    total_payout_i = int(float(total_payout or 0))
    users_net_profit_i = int(float(users_net_profit or 0))

    return {
        "attribution_rule": "resolved_at",
        "bets_count": int(bets_count or 0),
        "unique_bettors": int(unique_bettors or 0),
        "total_volume": total_volume_i,
        "total_payout": total_payout_i,
        "users_net_profit": users_net_profit_i,
        "system_net_sink": total_volume_i - total_payout_i,
        "biggest_win": {
            "payout": int(float(biggest_win_row["payout"])) if biggest_win_row else 0,
            "user_id": int(biggest_win_row["user_id"]) if biggest_win_row and biggest_win_row.get("user_id") is not None else None,
            "match_id": int(biggest_win_row["match_id"]) if biggest_win_row and biggest_win_row.get("match_id") is not None else None,
            "odds": float(biggest_win_row["odds"]) if biggest_win_row else 0.0,
            "bet_amount": int(biggest_win_row["amount"]) if biggest_win_row else 0,
        },
        "top_bettors_by_volume": [
            {"user_id": int(row["user_id"]), "volume": int(float(row["volume"] or 0))}
            for row in top_bettors_rows
            if row.get("user_id") is not None
        ],
        "top_profitable": [
            {"user_id": int(row["user_id"]), "net_profit": int(float(row["net_profit"] or 0))}
            for row in top_profitable_rows
            if row.get("user_id") is not None
        ],
    }
