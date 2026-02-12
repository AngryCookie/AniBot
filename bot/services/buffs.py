from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import UserBuff


class BuffService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def deactivate_expired_buffs(self, *, now: dt.datetime | None = None) -> int:
        moment = now or dt.datetime.utcnow()
        result = await self.session.execute(
            update(UserBuff)
            .where(UserBuff.active.is_(True), UserBuff.ends_at <= moment)
            .values(active=False)
        )
        return int(result.rowcount or 0)

    async def get_active_buffs(self, guild_id: int, user_id: int) -> dict[str, float]:
        now = dt.datetime.utcnow()
        await self.deactivate_expired_buffs(now=now)

        rows = (
            await self.session.execute(
                select(UserBuff.buff_type, func.max(UserBuff.value_percent))
                .where(
                    UserBuff.guild_id == guild_id,
                    UserBuff.user_id == user_id,
                    UserBuff.active.is_(True),
                    UserBuff.ends_at > now,
                )
                .group_by(UserBuff.buff_type)
            )
        ).all()
        return {str(buff_type): float(value or 0.0) for buff_type, value in rows}

    async def list_active_buffs(self, guild_id: int, user_id: int) -> list[UserBuff]:
        now = dt.datetime.utcnow()
        await self.deactivate_expired_buffs(now=now)
        result = await self.session.execute(
            select(UserBuff)
            .where(
                UserBuff.guild_id == guild_id,
                UserBuff.user_id == user_id,
                UserBuff.active.is_(True),
                UserBuff.ends_at > now,
            )
            .order_by(UserBuff.ends_at.asc(), UserBuff.id.asc())
        )
        return list(result.scalars().all())
