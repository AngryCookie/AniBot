from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from bot.database.models import ShadowPenaltyLog, UserProfile, UserTrustProfile
from bot.services.economy import EconomyService


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
    service = EconomyService(session)
    return await service.change_balance(
        guild_id=guild_id,
        user_id=user_id,
        amount=amount,
        transaction_type=ledger_type,
        source=source,
    )


async def apply_economy_sink(
    session,
    *,
    guild_id: int,
    user_id: int,
    amount: int,
    source: str,
) -> int:
    if amount >= 0:
        raise ValueError("Economy sink amount must be negative.")
    return await apply_balance_change(
        session,
        guild_id=guild_id,
        user_id=user_id,
        amount=amount,
        ledger_type="sink",
        source=source,
    )


async def record_shadow_penalty(
    session,
    *,
    guild_id: int,
    user_id: int,
    penalty_type: str,
    multiplier: float,
    reason: str = "",
    applied_by: int | None = None,
) -> ShadowPenaltyLog:
    penalty = ShadowPenaltyLog(
        guild_id=guild_id,
        user_id=user_id,
        penalty_type=penalty_type,
        multiplier=multiplier,
        reason=reason,
        applied_by=applied_by,
        created_at=dt.datetime.utcnow(),
    )
    session.add(penalty)
    return penalty


async def upsert_trust_profile(
    session,
    *,
    guild_id: int,
    user_id: int,
    account_age_days: int,
    activity_score: float,
    warnings_count: int,
    command_rate: float,
    abuse_count: int,
) -> UserTrustProfile:
    trust_score = max(
        0.0,
        min(
            1.0,
            0.4
            + (account_age_days / 365) * 0.2
            + (activity_score * 0.2)
            - (warnings_count * 0.05)
            - (abuse_count * 0.1)
            - (command_rate * 0.02),
        ),
    )
    result = await session.execute(
        select(UserTrustProfile)
        .where(
            (UserTrustProfile.guild_id == guild_id)
            & (UserTrustProfile.user_id == user_id)
        )
        .with_for_update()
    )
    profile = result.scalars().first()
    if profile is None:
        profile = UserTrustProfile(
            user_id=user_id,
            guild_id=guild_id,
            trust_score=trust_score,
            account_age_days=account_age_days,
            activity_score=activity_score,
            warnings_count=warnings_count,
            command_rate=command_rate,
            abuse_count=abuse_count,
            last_updated=dt.datetime.utcnow(),
        )
        session.add(profile)
        await session.flush()
        return profile
    profile.trust_score = trust_score
    profile.account_age_days = account_age_days
    profile.activity_score = activity_score
    profile.warnings_count = warnings_count
    profile.command_rate = command_rate
    profile.abuse_count = abuse_count
    profile.last_updated = dt.datetime.utcnow()
    return profile
