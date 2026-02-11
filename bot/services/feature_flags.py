from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import FeatureFlag, GuildFeatureFlag


async def is_feature_enabled(session: AsyncSession, guild_id: int, flag_name: str) -> bool:
    result = await session.execute(
        select(GuildFeatureFlag.enabled).where(
            (GuildFeatureFlag.guild_id == guild_id)
            & (GuildFeatureFlag.flag_name == flag_name)
        )
    )
    guild_flag = result.scalar()
    if guild_flag is not None:
        return bool(guild_flag)

    result = await session.execute(
        select(FeatureFlag.enabled).where(FeatureFlag.name == flag_name)
    )
    global_flag = result.scalar()
    return bool(global_flag)
