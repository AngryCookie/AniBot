from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import EconomyLedger, EconomyTransaction, UserProfile


class EconomyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_user_locked(self, guild_id: int, user_id: int) -> UserProfile:
        result = await self.session.execute(
            select(UserProfile)
            .where((UserProfile.guild_id == guild_id) & (UserProfile.user_id == user_id))
            .with_for_update()
        )
        user = result.scalars().first()
        if user is None:
            user = UserProfile(user_id=user_id, guild_id=guild_id)
            self.session.add(user)
            await self.session.flush()
            result = await self.session.execute(
                select(UserProfile)
                .where((UserProfile.guild_id == guild_id) & (UserProfile.user_id == user_id))
                .with_for_update()
            )
            user = result.scalars().first()
        return user

    async def change_balance(
        self,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
        transaction_type: str,
        source: str | None = None,
        reference_id: int | None = None,
        metadata: dict | None = None,
        created_at: dt.datetime | None = None,
    ) -> int:
        user = await self.get_or_create_user_locked(guild_id, user_id)
        balance_before = int(user.balance or 0)
        balance_after = balance_before + amount
        if balance_after < 0:
            raise ValueError("Недостаточно средств.")

        user.balance = balance_after
        timestamp = created_at or dt.datetime.utcnow()

        self.session.add(
            EconomyTransaction(
                guild_id=guild_id,
                user_id=user_id,
                type=transaction_type,
                amount=amount,
                balance_before=balance_before,
                balance_after=balance_after,
                source=source,
                reference_id=reference_id,
                metadata_json=metadata,
                created_at=timestamp,
            )
        )

        # Backward-compatible ledger for existing analytics/scheduled jobs.
        self.session.add(
            EconomyLedger(
                user_id=user_id,
                guild_id=guild_id,
                amount=amount,
                type=transaction_type,
                source=source or "unknown",
                timestamp=timestamp,
            )
        )
        return balance_after

    async def daily_reward(self, *, guild_id: int, user_id: int, amount: int) -> int:
        return await self.change_balance(
            guild_id=guild_id,
            user_id=user_id,
            amount=amount,
            transaction_type="daily_reward",
            source="daily",
        )

    async def place_bet(
        self,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
        source: str,
        reference_id: int | None = None,
        metadata: dict | None = None,
    ) -> int:
        return await self.change_balance(
            guild_id=guild_id,
            user_id=user_id,
            amount=-amount,
            transaction_type="bet_placement",
            source=source,
            reference_id=reference_id,
            metadata=metadata,
        )

    async def bet_win(
        self,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
        source: str,
        reference_id: int | None = None,
        metadata: dict | None = None,
    ) -> int:
        return await self.change_balance(
            guild_id=guild_id,
            user_id=user_id,
            amount=amount,
            transaction_type="bet_win",
            source=source,
            reference_id=reference_id,
            metadata=metadata,
        )

    async def shop_purchase(
        self,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
        source: str = "shop_purchase",
        reference_id: int | None = None,
        metadata: dict | None = None,
    ) -> int:
        return await self.change_balance(
            guild_id=guild_id,
            user_id=user_id,
            amount=-amount,
            transaction_type="shop_purchase",
            source=source,
            reference_id=reference_id,
            metadata=metadata,
        )

    async def admin_grant(
        self,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
        source: str = "admin_give",
        metadata: dict | None = None,
    ) -> int:
        return await self.change_balance(
            guild_id=guild_id,
            user_id=user_id,
            amount=amount,
            transaction_type="admin_grant",
            source=source,
            metadata=metadata,
        )

    async def admin_remove(
        self,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
        source: str = "admin_take",
        metadata: dict | None = None,
    ) -> int:
        return await self.change_balance(
            guild_id=guild_id,
            user_id=user_id,
            amount=-amount,
            transaction_type="admin_remove",
            source=source,
            metadata=metadata,
        )

    async def tax(
        self,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
        source: str,
        reference_id: int | None = None,
        metadata: dict | None = None,
    ) -> int:
        return await self.change_balance(
            guild_id=guild_id,
            user_id=user_id,
            amount=-amount,
            transaction_type="tax",
            source=source,
            reference_id=reference_id,
            metadata=metadata,
        )

    async def get_user_transactions(
        self,
        guild_id: int,
        user_id: int,
        limit: int = 50,
    ) -> list[EconomyTransaction]:
        result = await self.session.execute(
            select(EconomyTransaction)
            .where(
                (EconomyTransaction.guild_id == guild_id)
                & (EconomyTransaction.user_id == user_id)
            )
            .order_by(EconomyTransaction.created_at.desc(), EconomyTransaction.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_guild_transactions(
        self,
        guild_id: int,
        since: dt.datetime | None = None,
    ) -> list[EconomyTransaction]:
        stmt = select(EconomyTransaction).where(EconomyTransaction.guild_id == guild_id)
        if since is not None:
            stmt = stmt.where(EconomyTransaction.created_at >= since)
        result = await self.session.execute(
            stmt.order_by(EconomyTransaction.created_at.desc(), EconomyTransaction.id.desc())
        )
        return list(result.scalars().all())
