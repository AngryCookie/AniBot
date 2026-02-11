from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ReferralUsage


async def get_referral_metrics(session: AsyncSession, guild_id: int, period_days: int) -> dict:
    now = dt.datetime.utcnow()
    since = now - dt.timedelta(days=period_days)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    monthly_referral_volume = await session.scalar(
        select(func.count()).select_from(ReferralUsage).where(
            ReferralUsage.guild_id == guild_id,
            ReferralUsage.created_at >= month_start,
        )
    )
    total_referral_payout = await session.scalar(
        select(func.coalesce(func.sum(ReferralUsage.reward_amount * 2), 0)).where(
            ReferralUsage.guild_id == guild_id,
        )
    )

    ranking_result = await session.execute(
        select(
            ReferralUsage.inviter_user_id,
            func.count(ReferralUsage.id).label("invites"),
            func.coalesce(func.sum(ReferralUsage.reward_amount), 0).label("earned"),
        )
        .where(
            ReferralUsage.guild_id == guild_id,
            ReferralUsage.created_at >= since,
        )
        .group_by(ReferralUsage.inviter_user_id)
        .order_by(func.count(ReferralUsage.id).desc(), func.sum(ReferralUsage.reward_amount).desc())
        .limit(10)
    )
    top_inviters = [
        {
            "user_id": int(row.inviter_user_id),
            "invites": int(row.invites or 0),
            "earned": int(row.earned or 0),
        }
        for row in ranking_result
    ]

    return {
        "monthly_referral_volume": int(monthly_referral_volume or 0),
        "total_referral_payout": int(total_referral_payout or 0),
        "top_inviters": top_inviters,
    }
