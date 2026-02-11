from __future__ import annotations

import datetime as dt
import random

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import PvpDuel, UserProfile
from bot.services.economy import EconomyService


ACTIVE_DUEL_STATUSES = {"pending", "accepted"}


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

        challenger, opponent = await self._lock_duel_participants(
            guild_id=guild_id,
            challenger_id=challenger_id,
            opponent_id=opponent_id,
        )

        # Re-check active-duel invariants after participant rows are locked.
        await self._ensure_user_has_no_active_duel(guild_id, challenger_id)
        await self._ensure_user_has_no_active_duel(guild_id, opponent_id)

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

    async def expire_pending_duel(
        self,
        *,
        guild_id: int,
        duel_id: int,
    ) -> PvpDuel:
        duel = await self._get_duel_for_update(guild_id, duel_id)
        if duel.status != "pending":
            return duel
        duel.status = "expired"
        duel.resolved_at = dt.datetime.utcnow()
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
    ) -> PvpDuel:
        duel = await self._get_duel_for_update(guild_id, duel_id)
        if duel.status != "accepted":
            raise ValueError("Можно завершить только принятую дуэль.")

        participants = (int(duel.challenger_id), int(duel.opponent_id))
        if winner_id is None:
            winner_id = random.choice(participants)
        if winner_id not in participants:
            raise ValueError("Победитель должен быть участником дуэли.")

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

        duel.status = "resolved"
        duel.winner_id = winner_id
        duel.resolved_at = dt.datetime.utcnow()
        await self.session.flush()
        return duel

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

    async def _lock_duel_participants(
        self,
        *,
        guild_id: int,
        challenger_id: int,
        opponent_id: int,
    ) -> tuple[UserProfile, UserProfile]:
        ordered_user_ids = sorted((challenger_id, opponent_id))
        locked_users = {}
        for user_id in ordered_user_ids:
            locked_users[user_id] = await self.economy.get_or_create_user_locked(guild_id, user_id)
        return locked_users[challenger_id], locked_users[opponent_id]
