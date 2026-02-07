from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from bot.database.models import EconomyLedger, UserProfile


async def get_or_create_user_locked(session, guild_id: int, user_id: int) -> UserProfile:
    result = await session.execute(
        select(UserProfile)
        .where((UserProfile.guild_id == guild_id) & (UserProfile.user_id == user_id))
        .with_for_update()
    )
    user = result.scalars().first()
    if user is None:
        user = UserProfile(user_id=user_id, guild_id=guild_id)
        session.add(user)
        await session.flush()
        result = await session.execute(
            select(UserProfile)
            .where((UserProfile.guild_id == guild_id) & (UserProfile.user_id == user_id))
            .with_for_update()
        )
        user = result.scalars().first()
    return user


async def apply_balance_change(
    session,
    *,
    guild_id: int,
    user_id: int,
    amount: int,
    ledger_type: str,
    source: str,
) -> int:
    user = await get_or_create_user_locked(session, guild_id, user_id)
    new_balance = user.balance + amount
    if new_balance < 0:
        raise ValueError("Недостаточно средств.")
    user.balance = new_balance
    ledger = EconomyLedger(
        user_id=user_id,
        guild_id=guild_id,
        amount=amount,
        type=ledger_type,
        source=source,
        timestamp=dt.datetime.utcnow(),
    )
    session.add(ledger)
    return user.balance
