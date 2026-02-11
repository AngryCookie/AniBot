from __future__ import annotations

import datetime as dt
import math
import random

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import PvpDuel, PvpStats
from bot.services.economy import EconomyService


ACTIVE_DUEL_STATUSES = {"pending", "accepted"}
DEFAULT_RATING = 1000
DEFAULT_K_FACTOR = 32


class PvpService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.economy = EconomyService(session)

    async def create_duel(
        self,
        *,
        guild_id: int,
        challenger_id: int,
        opponent_id: int,
        amount: int,
        fee_percent: float,
    ) -> PvpDuel:
        if challenger_id == opponent_id:
            raise ValueError("Нельзя вызвать самого себя на дуэль.")
        if amount <= 0:
            raise ValueError("Ставка должна быть больше 0.")
        if fee_percent < 0 or fee_percent > 100:
            raise ValueError("Комиссия должна быть в диапазоне 0..100%.")

        await self._ensure_user_has_no_active_duel(guild_id, challenger_id)
        await self._ensure_user_has_no_active_duel(guild_id, opponent_id)

        challenger = await self.economy.get_or_create_user_locked(guild_id, challenger_id)
        opponent = await self.economy.get_or_create_user_locked(guild_id, opponent_id)
        if int(challenger.balance or 0) < amount:
            raise ValueError("У инициатора недостаточно средств.")
        if int(opponent.balance or 0) < amount:
            raise ValueError("У оппонента недостаточно средств.")

        duel = PvpDuel(
            guild_id=guild_id,
            challenger_id=challenger_id,
            opponent_id=opponent_id,
            amount=amount,
            fee_percent=fee_percent,
            status="pending",
        )
        self.session.add(duel)
        await self.session.flush()
        return duel

    async def accept_duel(
        self,
        *,
        guild_id: int,
        duel_id: int,
        actor_user_id: int,
    ) -> PvpDuel:
        duel = await self._get_duel_for_update(guild_id, duel_id)
        if duel.status != "pending":
            raise ValueError("Дуэль уже обработана.")
        if duel.opponent_id != actor_user_id:
            raise ValueError("Принять дуэль может только оппонент.")

        challenger = await self.economy.get_or_create_user_locked(guild_id, int(duel.challenger_id))
        opponent = await self.economy.get_or_create_user_locked(guild_id, int(duel.opponent_id))
        if int(challenger.balance or 0) < int(duel.amount):
            raise ValueError("У инициатора больше недостаточно средств.")
        if int(opponent.balance or 0) < int(duel.amount):
            raise ValueError("У оппонента недостаточно средств.")

        duel.status = "accepted"
        await self.economy.debit(
            guild_id,
            int(duel.challenger_id),
            int(duel.amount),
            "pvp_duel_lock",
            {"duel_id": duel.id, "role": "challenger"},
            ledger_type="pvp_lock",
        )
        await self.economy.debit(
            guild_id,
            int(duel.opponent_id),
            int(duel.amount),
            "pvp_duel_lock",
            {"duel_id": duel.id, "role": "opponent"},
            ledger_type="pvp_lock",
        )
        await self.session.flush()
        return duel

    async def decline_duel(
        self,
        *,
        guild_id: int,
        duel_id: int,
        actor_user_id: int,
    ) -> PvpDuel:
        duel = await self._get_duel_for_update(guild_id, duel_id)
        if duel.status != "pending":
            raise ValueError("Дуэль уже обработана.")
        if duel.opponent_id != actor_user_id:
            raise ValueError("Отклонить дуэль может только оппонент.")
        duel.status = "declined"
        duel.resolved_at = dt.datetime.utcnow()
        await self.session.flush()
        return duel

    async def resolve_duel(
        self,
        *,
        guild_id: int,
        duel_id: int,
        winner_id: int | None = None,
        k_factor: int = DEFAULT_K_FACTOR,
    ) -> PvpDuel:
        duel = await self._get_duel_for_update(guild_id, duel_id)
        if duel.status != "accepted":
            raise ValueError("Можно завершить только принятую дуэль.")

        participants = (int(duel.challenger_id), int(duel.opponent_id))
        if winner_id is None:
            winner_id = random.choice(participants)
        if winner_id not in participants:
            raise ValueError("Победитель должен быть участником дуэли.")

        loser_id = participants[1] if winner_id == participants[0] else participants[0]
        pot_total = int(duel.amount) * 2
        fee_amount = int(pot_total * float(duel.fee_percent) / 100.0)
        payout = pot_total - fee_amount
        if payout < 0:
            raise ValueError("Некорректная сумма выплаты.")

        if payout > 0:
            await self.economy.credit(
                guild_id,
                winner_id,
                payout,
                "pvp_duel_payout",
                {"duel_id": duel.id, "fee_amount": fee_amount},
                ledger_type="pvp_win",
            )

        await self._apply_duel_stats(
            guild_id=guild_id,
            winner_id=winner_id,
            loser_id=loser_id,
            amount=int(duel.amount),
            fee_amount=fee_amount,
            k_factor=k_factor,
        )

        duel.status = "resolved"
        duel.winner_id = winner_id
        duel.resolved_at = dt.datetime.utcnow()
        await self.session.flush()
        return duel

    async def get_user_stats(self, guild_id: int, user_id: int) -> PvpStats:
        return await self._get_or_create_stats(guild_id, user_id)

    async def get_top_players(self, guild_id: int, limit: int = 10) -> list[PvpStats]:
        result = await self.session.execute(
            select(PvpStats)
            .where(PvpStats.guild_id == guild_id)
            .order_by(PvpStats.rating.desc(), PvpStats.wins.desc(), PvpStats.user_id.asc())
            .limit(max(1, min(limit, 50)))
        )
        return list(result.scalars().all())

    async def get_guild_analytics(self, guild_id: int) -> dict:
        total_duels_result = await self.session.execute(
            select(func.count(PvpDuel.id)).where(
                (PvpDuel.guild_id == guild_id) & (PvpDuel.status == "resolved")
            )
        )
        totals_result = await self.session.execute(
            select(
                func.coalesce(func.sum(PvpStats.total_volume), 0),
                func.coalesce(func.sum(PvpStats.total_fees_paid), 0),
            ).where(PvpStats.guild_id == guild_id)
        )
        total_duels = int(total_duels_result.scalar() or 0)
        raw_volume, total_fees_burned = totals_result.one()
        total_volume = int(raw_volume or 0) // 2
        avg_bet = int((total_volume / total_duels)) if total_duels > 0 else 0

        dist = await self.session.execute(
            select(
                func.coalesce(func.sum(case((PvpStats.rating < 900, 1), else_=0)), 0).label("under_900"),
                func.coalesce(func.sum(case(((PvpStats.rating >= 900) & (PvpStats.rating < 1100), 1), else_=0)), 0).label("between_900_1099"),
                func.coalesce(func.sum(case(((PvpStats.rating >= 1100) & (PvpStats.rating < 1300), 1), else_=0)), 0).label("between_1100_1299"),
                func.coalesce(func.sum(case((PvpStats.rating >= 1300, 1), else_=0)), 0).label("over_1300"),
            ).where(PvpStats.guild_id == guild_id)
        )
        dist_row = dist.one()

        top_players = await self.get_top_players(guild_id, limit=10)
        return {
            "total_duels": int(total_duels or 0),
            "total_volume": int(total_volume or 0),
            "total_fees_burned": int(total_fees_burned or 0),
            "avg_bet": avg_bet,
            "rating_distribution": {
                "under_900": int(dist_row.under_900 or 0),
                "between_900_1099": int(dist_row.between_900_1099 or 0),
                "between_1100_1299": int(dist_row.between_1100_1299 or 0),
                "over_1300": int(dist_row.over_1300 or 0),
            },
            "top_players": [
                {
                    "user_id": int(player.user_id),
                    "rating": int(player.rating),
                    "wins": int(player.wins),
                    "losses": int(player.losses),
                    "profit": int(player.total_profit),
                }
                for player in top_players
            ],
        }

    async def reset_pvp_season(self, guild_id: int) -> None:
        result = await self.session.execute(select(PvpStats).where(PvpStats.guild_id == guild_id))
        for stat in result.scalars().all():
            stat.wins = 0
            stat.losses = 0
            stat.total_volume = 0
            stat.total_profit = 0
            stat.total_fees_paid = 0
            stat.rating = DEFAULT_RATING
            stat.current_streak = 0
            stat.best_streak = 0
            stat.updated_at = dt.datetime.utcnow()
        await self.session.flush()

    async def _apply_duel_stats(
        self,
        *,
        guild_id: int,
        winner_id: int,
        loser_id: int,
        amount: int,
        fee_amount: int,
        k_factor: int,
    ) -> None:
        winner = await self._get_or_create_stats(guild_id, winner_id)
        loser = await self._get_or_create_stats(guild_id, loser_id)

        expected_winner = self._expected_score(int(winner.rating), int(loser.rating))
        expected_loser = self._expected_score(int(loser.rating), int(winner.rating))
        winner.rating = self._next_rating(int(winner.rating), 1.0, expected_winner, k_factor)
        loser.rating = self._next_rating(int(loser.rating), 0.0, expected_loser, k_factor)

        winner.wins = int(winner.wins) + 1
        loser.losses = int(loser.losses) + 1

        winner.total_volume = int(winner.total_volume) + amount
        loser.total_volume = int(loser.total_volume) + amount

        winner_fee = fee_amount // 2
        loser_fee = fee_amount - winner_fee
        winner.total_fees_paid = int(winner.total_fees_paid) + winner_fee
        loser.total_fees_paid = int(loser.total_fees_paid) + loser_fee

        winner.total_profit = int(winner.total_profit) + (amount - winner_fee)
        loser.total_profit = int(loser.total_profit) - (amount + loser_fee)

        winner.current_streak = max(1, int(winner.current_streak) + 1)
        winner.best_streak = max(int(winner.best_streak), int(winner.current_streak))
        loser.current_streak = 0

        now = dt.datetime.utcnow()
        winner.updated_at = now
        loser.updated_at = now
        await self.session.flush()

    async def _get_or_create_stats(self, guild_id: int, user_id: int) -> PvpStats:
        result = await self.session.execute(
            select(PvpStats)
            .where((PvpStats.guild_id == guild_id) & (PvpStats.user_id == user_id))
            .with_for_update()
        )
        stats = result.scalars().first()
        if stats is not None:
            return stats
        stats = PvpStats(guild_id=guild_id, user_id=user_id, rating=DEFAULT_RATING)
        self.session.add(stats)
        await self.session.flush()
        return stats

    def _expected_score(self, rating_a: int, rating_b: int) -> float:
        return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0))

    def _next_rating(self, rating: int, score: float, expected: float, k_factor: int) -> int:
        if k_factor <= 0:
            k_factor = DEFAULT_K_FACTOR
        return max(100, int(round(rating + k_factor * (score - expected))))

    async def _ensure_user_has_no_active_duel(self, guild_id: int, user_id: int) -> None:
        result = await self.session.execute(
            select(PvpDuel.id)
            .where(
                (PvpDuel.guild_id == guild_id)
                & (PvpDuel.status.in_(ACTIVE_DUEL_STATUSES))
                & or_(PvpDuel.challenger_id == user_id, PvpDuel.opponent_id == user_id)
            )
            .limit(1)
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError("Пользователь уже участвует в активной PvP-дуэли.")

    async def _get_duel_for_update(self, guild_id: int, duel_id: int) -> PvpDuel:
        result = await self.session.execute(
            select(PvpDuel)
            .where((PvpDuel.id == duel_id) & (PvpDuel.guild_id == guild_id))
            .with_for_update()
        )
        duel = result.scalars().first()
        if duel is None:
            raise ValueError("Дуэль не найдена.")
        return duel
