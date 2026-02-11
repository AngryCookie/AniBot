from __future__ import annotations

import datetime as dt
import importlib
import json
import math
import random
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import GuildConfig, PvpDuel, PvpStats, UserProfile
from bot.services.economy import EconomyService


ACTIVE_DUEL_STATUSES = {"pending", "accepted"}
DEFAULT_RATING = 1000
DEFAULT_K_FACTOR = 32
DEFAULT_PVP_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "min_bet": 50,
    "max_bet": 5000,
    "cooldown_seconds": 300,
    "max_active_duels_per_user": 1,
    "level_influence_percent": 10,
    "fee_percent": 5.0,
}


class PvpService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.economy = EconomyService(session)

    async def get_pvp_settings(self, guild_id: int) -> dict[str, Any]:
        config = await self.session.get(GuildConfig, guild_id)
        if config is None:
            return dict(DEFAULT_PVP_SETTINGS)
        try:
            settings_map = json.loads(config.settings or "{}")
        except json.JSONDecodeError:
            settings_map = {}
        raw_pvp = settings_map.get("pvp", {})
        if not isinstance(raw_pvp, dict):
            raw_pvp = {}
        merged = dict(DEFAULT_PVP_SETTINGS)
        merged.update(raw_pvp)
        return merged

    async def create_duel(
        self,
        *,
        guild_id: int,
        challenger_id: int,
        opponent_id: int,
        amount: int,
        fee_percent: float,
    ) -> PvpDuel:
        settings = await self.get_pvp_settings(guild_id)
        if not bool(settings.get("enabled", True)):
            raise ValueError("PvP-дуэли отключены на этом сервере.")
        if challenger_id == opponent_id:
            raise ValueError("Нельзя вызвать самого себя на дуэль.")
        min_bet = int(settings.get("min_bet", DEFAULT_PVP_SETTINGS["min_bet"]))
        max_bet = int(settings.get("max_bet", DEFAULT_PVP_SETTINGS["max_bet"]))
        if amount < min_bet:
            raise ValueError(f"Минимальная ставка для PvP: {min_bet}.")
        if amount > max_bet:
            raise ValueError(f"Максимальная ставка для PvP: {max_bet}.")
        if fee_percent < 0 or fee_percent > 100:
            raise ValueError("Комиссия должна быть в диапазоне 0..100%.")

        max_active_duels = int(
            settings.get("max_active_duels_per_user", DEFAULT_PVP_SETTINGS["max_active_duels_per_user"])
        )
        cooldown_seconds = int(settings.get("cooldown_seconds", DEFAULT_PVP_SETTINGS["cooldown_seconds"]))

        async def operation() -> PvpDuel:
            challenger = await self.economy.get_or_create_user_locked(guild_id, challenger_id)
            opponent = await self.economy.get_or_create_user_locked(guild_id, opponent_id)

            await self._ensure_active_duels_limit(guild_id, challenger_id, max_active_duels)
            await self._ensure_active_duels_limit(guild_id, opponent_id, max_active_duels)
            self._ensure_cooldown(challenger, cooldown_seconds)
            self._ensure_cooldown(opponent, cooldown_seconds)

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

        return await self._run_in_transaction(operation)

    async def accept_duel(
        self,
        *,
        guild_id: int,
        duel_id: int,
        actor_user_id: int,
    ) -> PvpDuel:
        async def operation() -> PvpDuel:
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

        return await self._run_in_transaction(operation)

    async def decline_duel(
        self,
        *,
        guild_id: int,
        duel_id: int,
        actor_user_id: int,
    ) -> PvpDuel:
        async def operation() -> PvpDuel:
            duel = await self._get_duel_for_update(guild_id, duel_id)
            if duel.status != "pending":
                raise ValueError("Дуэль уже обработана.")
            if duel.opponent_id != actor_user_id:
                raise ValueError("Отклонить дуэль может только оппонент.")
            duel.status = "declined"
            duel.resolved_at = dt.datetime.utcnow()
            await self.session.flush()
            return duel

        return await self._run_in_transaction(operation)

    async def resolve_duel(
        self,
        *,
        guild_id: int,
        duel_id: int,
        winner_id: int | None = None,
        k_factor: int = DEFAULT_K_FACTOR,
    ) -> PvpDuel:
        settings = await self.get_pvp_settings(guild_id)
        level_influence_percent = float(
            settings.get("level_influence_percent", DEFAULT_PVP_SETTINGS["level_influence_percent"])
        )

        async def operation() -> PvpDuel:
            duel = await self._get_duel_for_update(guild_id, duel_id)
            if duel.status != "accepted":
                raise ValueError("Можно завершить только принятую дуэль.")

            challenger = await self.economy.get_or_create_user_locked(guild_id, int(duel.challenger_id))
            opponent = await self.economy.get_or_create_user_locked(guild_id, int(duel.opponent_id))
            participants = (int(duel.challenger_id), int(duel.opponent_id))

            resolved_winner_id = winner_id
            if resolved_winner_id is None:
                challenger_level = int(challenger.level or 1)
                opponent_level = int(opponent.level or 1)
                chance_challenger = self._calculate_win_chance(
                    challenger_level,
                    opponent_level,
                    level_influence_percent,
                )
                resolved_winner_id = participants[0] if random.random() < chance_challenger else participants[1]
            if resolved_winner_id not in participants:
                raise ValueError("Победитель должен быть участником дуэли.")

            loser_id = participants[1] if resolved_winner_id == participants[0] else participants[0]
            loser_profile = challenger if loser_id == int(challenger.user_id) else opponent
            winner_profile = challenger if resolved_winner_id == int(challenger.user_id) else opponent

            pot_total = int(duel.amount) * 2
            fee_amount = int(pot_total * float(duel.fee_percent) / 100.0)
            payout = pot_total - fee_amount
            if payout < 0:
                raise ValueError("Некорректная сумма выплаты.")

            if payout > 0:
                await self.economy.credit(
                    guild_id,
                    resolved_winner_id,
                    payout,
                    "pvp_duel_payout",
                    {"duel_id": duel.id, "fee_amount": fee_amount},
                    ledger_type="pvp_win",
                )

            await self._apply_duel_stats(
                guild_id=guild_id,
                winner_id=resolved_winner_id,
                loser_id=loser_id,
                amount=int(duel.amount),
                fee_amount=fee_amount,
                k_factor=k_factor,
            )

            now = dt.datetime.utcnow()
            duel.status = "resolved"
            duel.winner_id = resolved_winner_id
            duel.resolved_at = now
            winner_profile.last_pvp_at = now
            loser_profile.last_pvp_at = now
            winner_profile.total_pvp_wins = int(winner_profile.total_pvp_wins or 0) + 1
            loser_profile.total_pvp_losses = int(loser_profile.total_pvp_losses or 0) + 1
            winner_profile.total_pvp_volume = int(winner_profile.total_pvp_volume or 0) + int(duel.amount)
            loser_profile.total_pvp_volume = int(loser_profile.total_pvp_volume or 0) + int(duel.amount)

            await self._emit_analytics_event(
                guild_id=guild_id,
                duel_id=int(duel.id),
                winner_id=resolved_winner_id,
                loser_id=loser_id,
                amount=int(duel.amount),
                fee_amount=fee_amount,
            )

            await self.session.flush()
            return duel

        return await self._run_in_transaction(operation)

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

    def _calculate_win_chance(self, challenger_level: int, opponent_level: int, level_influence_percent: float) -> float:
        level_diff = challenger_level - opponent_level
        modifier = level_diff * (level_influence_percent / 1000.0)
        modifier = max(-0.1, min(0.1, modifier))
        chance = 0.5 + modifier
        return max(0.4, min(0.6, chance))

    def _ensure_cooldown(self, profile: UserProfile, cooldown_seconds: int) -> None:
        if cooldown_seconds <= 0:
            return
        if profile.last_pvp_at is None:
            return
        elapsed = (dt.datetime.utcnow() - profile.last_pvp_at).total_seconds()
        if elapsed < cooldown_seconds:
            left_seconds = int(cooldown_seconds - elapsed)
            raise ValueError(f"PvP кулдаун ещё активен: подождите {left_seconds} сек.")

    async def _ensure_active_duels_limit(self, guild_id: int, user_id: int, max_active_duels: int) -> None:
        if max_active_duels <= 0:
            return
        result = await self.session.execute(
            select(func.count(PvpDuel.id)).where(
                (PvpDuel.guild_id == guild_id)
                & (PvpDuel.status.in_(ACTIVE_DUEL_STATUSES))
                & or_(PvpDuel.challenger_id == user_id, PvpDuel.opponent_id == user_id)
            )
        )
        active_count = int(result.scalar() or 0)
        if active_count >= max_active_duels:
            raise ValueError("Пользователь достиг лимита активных PvP-дуэлей.")

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

    async def _emit_analytics_event(self, **payload: Any) -> None:
        try:
            module = importlib.import_module("bot.analytics.events")
            emit_event = getattr(module, "emit_event", None)
            if callable(emit_event):
                result = emit_event("pvp_duel_resolved", payload)
                if hasattr(result, "__await__"):
                    await result
        except Exception:
            return

    async def _run_in_transaction(self, operation):
        if self.session.in_transaction():
            return await operation()
        async with self.session.begin():
            return await operation()
