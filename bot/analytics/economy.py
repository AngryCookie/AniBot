from __future__ import annotations

from datetime import datetime, timedelta
import math

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import EconomyLedger, EconomyTransaction, UserProfile

SUPPORTED_PERIOD_DAYS = {7, 30, 90}


class EconomyAnalyticsService:
    """Read-only analytics service powered by economy_transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _get_cutoff(days: int | None) -> datetime | None:
        if days is None:
            return None
        return datetime.utcnow() - timedelta(days=days)

    @staticmethod
    def _with_period(stmt, cutoff: datetime | None):
        if cutoff is None:
            return stmt
        return stmt.where(EconomyTransaction.created_at >= cutoff)

    async def get_guild_overview(self, guild_id: int, days: int | None = None) -> dict:
        cutoff = self._get_cutoff(days)

        overview_stmt = (
            select(
                func.coalesce(
                    func.sum(
                        case((EconomyTransaction.amount > 0, EconomyTransaction.amount), else_=0)
                    ),
                    0,
                ).label("total_earned"),
                func.coalesce(
                    func.sum(
                        case((EconomyTransaction.amount < 0, -EconomyTransaction.amount), else_=0)
                    ),
                    0,
                ).label("total_spent"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (EconomyTransaction.source == "bet_placement")
                                & (EconomyTransaction.amount < 0),
                                -EconomyTransaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("total_bets_volume"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (EconomyTransaction.source == "bet_win")
                                & (EconomyTransaction.amount > 0),
                                EconomyTransaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("total_bets_won"),
                func.coalesce(func.count(distinct(EconomyTransaction.user_id)), 0).label(
                    "active_users_count"
                ),
            )
            .where(EconomyTransaction.guild_id == guild_id)
        )
        overview_stmt = self._with_period(overview_stmt, cutoff)

        result = await self.session.execute(overview_stmt)
        row = result.one()

        total_earned = int(row.total_earned or 0)
        total_spent = int(row.total_spent or 0)
        total_bets_volume = int(row.total_bets_volume or 0)
        total_bets_won = int(row.total_bets_won or 0)
        total_bets_lost = max(total_bets_volume - total_bets_won, 0)
        house_profit = total_bets_lost
        net_flow = total_earned - total_spent
        active_users_count = int(row.active_users_count or 0)

        return {
            "total_earned": total_earned,
            "total_spent": total_spent,
            "total_bets_volume": total_bets_volume,
            "total_bets_won": total_bets_won,
            "total_bets_lost": total_bets_lost,
            "house_profit": house_profit,
            "net_flow": net_flow,
            "active_users_count": active_users_count,
        }

    async def get_betting_stats(self, guild_id: int, days: int | None = None) -> dict:
        cutoff = self._get_cutoff(days)

        stats_stmt = (
            select(
                func.coalesce(
                    func.count(
                        case((EconomyTransaction.source == "bet_placement", EconomyTransaction.id))
                    ),
                    0,
                ).label("bets_count"),
                func.coalesce(
                    func.count(case((EconomyTransaction.source == "bet_win", EconomyTransaction.id))),
                    0,
                ).label("wins_count"),
                func.coalesce(
                    func.avg(
                        case(
                            (
                                (EconomyTransaction.source == "bet_placement")
                                & (EconomyTransaction.amount < 0),
                                -EconomyTransaction.amount,
                            ),
                            else_=None,
                        )
                    ),
                    0,
                ).label("average_bet_size"),
                func.coalesce(
                    func.max(
                        case(
                            (
                                (EconomyTransaction.source == "bet_win")
                                & (EconomyTransaction.amount > 0),
                                EconomyTransaction.amount,
                            ),
                            else_=None,
                        )
                    ),
                    0,
                ).label("biggest_win"),
                func.coalesce(
                    func.max(
                        case(
                            (
                                (EconomyTransaction.source == "bet_placement")
                                & (EconomyTransaction.amount < 0),
                                -EconomyTransaction.amount,
                            ),
                            else_=None,
                        )
                    ),
                    0,
                ).label("biggest_loss"),
            )
            .where(EconomyTransaction.guild_id == guild_id)
        )
        stats_stmt = self._with_period(stats_stmt, cutoff)

        result = await self.session.execute(stats_stmt)
        row = result.one()

        bets_count = int(row.bets_count or 0)
        wins_count = int(row.wins_count or 0)
        winrate_percent = (wins_count / bets_count * 100) if bets_count else 0.0

        return {
            "winrate_percent": round(winrate_percent, 2),
            "average_bet_size": float(row.average_bet_size or 0),
            "biggest_win": int(row.biggest_win or 0),
            "biggest_loss": int(row.biggest_loss or 0),
        }

    async def get_user_top_earners(
        self,
        guild_id: int,
        days: int | None = None,
        limit: int = 10,
    ) -> list[dict]:
        cutoff = self._get_cutoff(days)

        stmt = (
            select(
                EconomyTransaction.user_id.label("user_id"),
                func.coalesce(func.sum(EconomyTransaction.amount), 0).label("net_amount"),
            )
            .where(EconomyTransaction.guild_id == guild_id)
            .group_by(EconomyTransaction.user_id)
            .having(func.sum(EconomyTransaction.amount) > 0)
            .order_by(func.sum(EconomyTransaction.amount).desc(), EconomyTransaction.user_id.asc())
            .limit(limit)
        )
        stmt = self._with_period(stmt, cutoff)

        result = await self.session.execute(stmt)
        return [
            {"user_id": int(row.user_id), "net_earned": int(row.net_amount)}
            for row in result.all()
        ]

    async def get_user_top_losers(
        self,
        guild_id: int,
        days: int | None = None,
        limit: int = 10,
    ) -> list[dict]:
        cutoff = self._get_cutoff(days)

        stmt = (
            select(
                EconomyTransaction.user_id.label("user_id"),
                func.coalesce(func.sum(EconomyTransaction.amount), 0).label("net_amount"),
            )
            .where(EconomyTransaction.guild_id == guild_id)
            .group_by(EconomyTransaction.user_id)
            .having(func.sum(EconomyTransaction.amount) < 0)
            .order_by(func.sum(EconomyTransaction.amount).asc(), EconomyTransaction.user_id.asc())
            .limit(limit)
        )
        stmt = self._with_period(stmt, cutoff)

        result = await self.session.execute(stmt)
        return [
            {"user_id": int(row.user_id), "net_lost": abs(int(row.net_amount))}
            for row in result.all()
        ]


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
