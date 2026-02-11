from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import CommunityGoal, EconomyLedger, UserProfile


class CommunityGoalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_goal(self, guild_id: int) -> CommunityGoal | None:
        result = await self.session.execute(
            select(CommunityGoal).where(
                and_(CommunityGoal.guild_id == guild_id, CommunityGoal.status == "active")
            )
        )
        return result.scalars().first()

    async def create_goal(
        self,
        *,
        guild_id: int,
        metric_type: str,
        target_value: int,
        starts_at: dt.datetime,
        ends_at: dt.datetime,
        reward_role_id: int | None,
        min_participation_threshold: int,
    ) -> CommunityGoal:
        existing = await self.session.execute(
            select(CommunityGoal).where(
                and_(
                    CommunityGoal.guild_id == guild_id,
                    CommunityGoal.starts_at <= ends_at,
                    CommunityGoal.ends_at >= starts_at,
                )
            )
        )
        if existing.scalars().first() is not None:
            raise ValueError("Период цели пересекается с существующей целью.")

        active = await self.get_active_goal(guild_id)
        if active is not None:
            raise ValueError("У сервера уже есть активная цель сообщества.")

        goal = CommunityGoal(
            guild_id=guild_id,
            metric_type=metric_type,
            target_value=target_value,
            starts_at=starts_at,
            ends_at=ends_at,
            reward_role_id=reward_role_id,
            min_participation_threshold=min_participation_threshold,
            status="active",
        )
        self.session.add(goal)
        await self.session.flush()
        await self.update_goal_progress(guild_id)
        return goal

    async def update_goal_progress(self, guild_id: int) -> CommunityGoal | None:
        goal = await self.get_active_goal(guild_id)
        if goal is None:
            return None

        if goal.metric_type == "voice_hours":
            result = await self.session.execute(
                select(func.coalesce(func.sum(EconomyLedger.amount), 0)).where(
                    and_(
                        EconomyLedger.guild_id == guild_id,
                        EconomyLedger.source == "voice_activity",
                        EconomyLedger.type == "earn",
                        EconomyLedger.timestamp >= goal.starts_at,
                        EconomyLedger.timestamp <= goal.ends_at,
                    )
                )
            )
            total_voice_seconds = int(result.scalar() or 0)
            value = total_voice_seconds // 3600
        elif goal.metric_type == "messages":
            result = await self.session.execute(
                select(func.coalesce(func.count(UserProfile.id), 0)).where(
                    and_(
                        UserProfile.guild_id == guild_id,
                        UserProfile.last_message_ts.is_not(None),
                        UserProfile.last_message_ts >= goal.starts_at,
                        UserProfile.last_message_ts <= goal.ends_at,
                    )
                )
            )
            value = int(result.scalar() or 0)
        else:
            raise ValueError("Неподдерживаемый тип метрики цели сообщества.")

        goal.current_value = min(value, goal.target_value)
        goal.updated_at = dt.datetime.utcnow()
        await self.session.flush()
        return goal

    async def evaluate_goal(self, guild_id: int) -> CommunityGoal | None:
        goal = await self.get_active_goal(guild_id)
        if goal is None:
            return None

        await self.update_goal_progress(guild_id)
        now = dt.datetime.utcnow()
        if now < goal.ends_at:
            return goal

        goal.status = "completed" if goal.current_value >= goal.target_value else "failed"
        goal.updated_at = now
        await self.session.flush()
        return goal
