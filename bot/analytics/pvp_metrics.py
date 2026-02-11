from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.pvp import PvpService


async def get_pvp_metrics(session: AsyncSession, guild_id: int) -> dict:
    service = PvpService(session)
    return await service.get_guild_analytics(guild_id)
