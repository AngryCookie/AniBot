from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable

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

    async def _run_in_transaction(self, operation: Callable[[], Awaitable[int]]) -> int:
        if self.session.in_transaction():
            return await operation()
        async with self.session.begin():
            return await operation()

    async def _apply_change(
        self,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
        source: str,
        metadata: dict | None = None,
        ledger_type: str | None = None,
        created_at: dt.datetime | None = None,
    ) -> int:
        user = await self.get_or_create_user_locked(guild_id, user_id)
        balance_before = int(user.balance or 0)
        balance_after = balance_before + amount
        if balance_after < 0:
            raise ValueError("Недостаточно средств.")

        user.balance = balance_after
        timestamp = created_at or dt.datetime.utcnow()

        transaction_source = ledger_type or source
        transaction_metadata = dict(metadata or {})
        if source != transaction_source:
            transaction_metadata.setdefault("origin_source", source)

        self.session.add(
            EconomyTransaction(
                guild_id=guild_id,
                user_id=user_id,
                amount=amount,
                balance_before=balance_before,
                balance_after=balance_after,
                source=transaction_source,
                metadata_json=transaction_metadata or None,
                created_at=timestamp,
            )
        )

        # Backward-compatible ledger for existing analytics/scheduled jobs.
        self.session.add(
            EconomyLedger(
                user_id=user_id,
                guild_id=guild_id,
                amount=amount,
                type=ledger_type or source,
                source=source,
                timestamp=timestamp,
            )
        )
        return balance_after

    async def credit(
        self,
        guild_id: int,
        user_id: int,
        amount: int,
        source: str,
        metadata: dict | None = None,
        *,
        ledger_type: str | None = None,
    ) -> int:
        if amount <= 0:
            raise ValueError("Amount must be greater than zero.")

        async def operation() -> int:
            return await self._apply_change(
                guild_id=guild_id,
                user_id=user_id,
                amount=amount,
                source=source,
                metadata=metadata,
                ledger_type=ledger_type,
            )

        return await self._run_in_transaction(operation)

    async def debit(
        self,
        guild_id: int,
        user_id: int,
        amount: int,
        source: str,
        metadata: dict | None = None,
        *,
        ledger_type: str | None = None,
    ) -> int:
        if amount <= 0:
            raise ValueError("Amount must be greater than zero.")

        async def operation() -> int:
            return await self._apply_change(
                guild_id=guild_id,
                user_id=user_id,
                amount=-amount,
                source=source,
                metadata=metadata,
                ledger_type=ledger_type,
            )

        return await self._run_in_transaction(operation)

    async def transfer(
        self,
        guild_id: int,
        from_user_id: int,
        to_user_id: int,
        amount: int,
        source: str,
    ) -> tuple[int, int]:
        if amount <= 0:
            raise ValueError("Amount must be greater than zero.")
        if from_user_id == to_user_id:
            raise ValueError("Cannot transfer to the same user.")

        async def operation() -> tuple[int, int]:
            ordered_user_ids = sorted((from_user_id, to_user_id))
            for locked_user_id in ordered_user_ids:
                await self.get_or_create_user_locked(guild_id, locked_user_id)

            sender_balance = await self._apply_change(
                guild_id=guild_id,
                user_id=from_user_id,
                amount=-amount,
                source=f"{source}_out",
                metadata={"counterparty_user_id": to_user_id},
                ledger_type="spend",
            )
            recipient_balance = await self._apply_change(
                guild_id=guild_id,
                user_id=to_user_id,
                amount=amount,
                source=f"{source}_in",
                metadata={"counterparty_user_id": from_user_id},
                ledger_type="earn",
            )
            return sender_balance, recipient_balance

        if self.session.in_transaction():
            return await operation()
        async with self.session.begin():
            return await operation()

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
        payload = dict(metadata or {})
        if reference_id is not None:
            payload.setdefault("reference_id", reference_id)
        payload.setdefault("transaction_type", transaction_type)
        transaction_source = source or transaction_type
        if amount >= 0:
            return await self.credit(
                guild_id,
                user_id,
                amount,
                transaction_source,
                payload,
                ledger_type=transaction_type,
            )
        return await self.debit(
            guild_id,
            user_id,
            -amount,
            transaction_source,
            payload,
            ledger_type=transaction_type,
        )

    async def daily_reward(self, *, guild_id: int, user_id: int, amount: int) -> int:
        return await self.credit(guild_id, user_id, amount, "daily", ledger_type="daily_reward")

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
        payload = dict(metadata or {})
        if reference_id is not None:
            payload["reference_id"] = reference_id
        return await self.debit(
            guild_id,
            user_id,
            amount,
            source,
            payload,
            ledger_type="bet_placement",
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
        payload = dict(metadata or {})
        if reference_id is not None:
            payload["reference_id"] = reference_id
        return await self.credit(
            guild_id,
            user_id,
            amount,
            source,
            payload,
            ledger_type="bet_win",
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
        payload = dict(metadata or {})
        if reference_id is not None:
            payload["reference_id"] = reference_id
        return await self.debit(
            guild_id,
            user_id,
            amount,
            source,
            payload,
            ledger_type="shop_purchase",
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
        return await self.credit(
            guild_id,
            user_id,
            amount,
            source,
            metadata,
            ledger_type="admin_grant",
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
        return await self.debit(
            guild_id,
            user_id,
            amount,
            source,
            metadata,
            ledger_type="admin_remove",
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
        payload = dict(metadata or {})
        if reference_id is not None:
            payload["reference_id"] = reference_id
        return await self.debit(
            guild_id,
            user_id,
            amount,
            source,
            payload,
            ledger_type="tax",
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
