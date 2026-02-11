from __future__ import annotations

import datetime as dt
import logging

import discord
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import (
    CommunityGoal,
    CommunityGoalParticipant,
    EconomyLedger,
    UserProfile,
)

logger = logging.getLogger(__name__)


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

    async def _calculate_member_contribution(self, goal: CommunityGoal, user_id: int) -> int:
        if goal.metric_type == "voice_hours":
            result = await self.session.execute(
                select(func.coalesce(func.sum(EconomyLedger.amount), 0)).where(
                    and_(
                        EconomyLedger.guild_id == goal.guild_id,
                        EconomyLedger.user_id == user_id,
                        EconomyLedger.source == "voice_activity",
                        EconomyLedger.type == "earn",
                        EconomyLedger.timestamp >= goal.starts_at,
                        EconomyLedger.timestamp <= goal.ends_at,
                    )
                )
            )
            total_voice_seconds = int(result.scalar() or 0)
            return total_voice_seconds // 3600

        if goal.metric_type == "messages":
            result = await self.session.execute(
                select(func.count(UserProfile.id)).where(
                    and_(
                        UserProfile.guild_id == goal.guild_id,
                        UserProfile.user_id == user_id,
                        UserProfile.last_message_ts.is_not(None),
                        UserProfile.last_message_ts >= goal.starts_at,
                        UserProfile.last_message_ts <= goal.ends_at,
                    )
                )
            )
            return int(result.scalar() or 0)

        raise ValueError("Неподдерживаемый тип метрики цели сообщества.")

    async def distribute_rewards(self, bot: discord.Client, guild_id: int) -> int:
        goal_result = await self.session.execute(
            select(CommunityGoal)
            .where(
                and_(
                    CommunityGoal.guild_id == guild_id,
                    CommunityGoal.status == "completed",
                )
            )
            .order_by(CommunityGoal.ends_at.desc())
        )
        goal = goal_result.scalars().first()
        if goal is None:
            logger.info("No completed community goal found for reward distribution", extra={"guild_id": guild_id})
            return 0

        existing = await self.session.execute(
            select(func.count(CommunityGoalParticipant.id)).where(
                and_(
                    CommunityGoalParticipant.goal_id == goal.id,
                    CommunityGoalParticipant.rewarded.is_(True),
                )
            )
        )
        if int(existing.scalar() or 0) > 0:
            logger.info(
                "Rewards already distributed for community goal",
                extra={"guild_id": guild_id, "goal_id": goal.id},
            )
            return 0

        if goal.reward_role_id is None:
            logger.info(
                "Community goal has no reward role; skipping reward distribution",
                extra={"guild_id": guild_id, "goal_id": goal.id},
            )
            return 0

        guild = bot.get_guild(guild_id)
        if guild is None:
            logger.warning("Guild not found in bot cache", extra={"guild_id": guild_id})
            return 0

        role = guild.get_role(goal.reward_role_id)
        if role is None:
            logger.warning(
                "Reward role not found in guild",
                extra={"guild_id": guild_id, "goal_id": goal.id, "role_id": goal.reward_role_id},
            )
            return 0

        rewarded_count = 0
        for member in guild.members:
            contribution = await self._calculate_member_contribution(goal, member.id)
            if contribution < goal.min_participation_threshold:
                continue

            existing_participant_result = await self.session.execute(
                select(CommunityGoalParticipant).where(
                    and_(
                        CommunityGoalParticipant.goal_id == goal.id,
                        CommunityGoalParticipant.user_id == member.id,
                    )
                )
            )
            participant = existing_participant_result.scalars().first()
            if participant is None:
                participant = CommunityGoalParticipant(
                    goal_id=goal.id,
                    user_id=member.id,
                    contribution_value=contribution,
                    rewarded=False,
                )
                self.session.add(participant)

            participant.contribution_value = contribution

            if participant.rewarded:
                continue

            if role not in member.roles:
                await member.add_roles(role, reason=f"Community goal reward #{goal.id}")

            participant.rewarded = True
            rewarded_count += 1

            logger.info(
                "Community goal reward granted",
                extra={
                    "guild_id": guild_id,
                    "goal_id": goal.id,
                    "user_id": member.id,
                    "contribution": contribution,
                },
            )

        await self.session.flush()
        return rewarded_count

    async def remove_previous_goal_roles(self, bot: discord.Client, guild_id: int) -> int:
        goals_result = await self.session.execute(
            select(CommunityGoal)
            .where(
                and_(
                    CommunityGoal.guild_id == guild_id,
                    CommunityGoal.status == "completed",
                )
            )
            .order_by(CommunityGoal.ends_at.desc())
            .limit(2)
        )
        goals = goals_result.scalars().all()
        if len(goals) < 2:
            return 0

        previous_goal = goals[1]
        if previous_goal.reward_role_id is None:
            return 0

        guild = bot.get_guild(guild_id)
        if guild is None:
            logger.warning("Guild not found in bot cache", extra={"guild_id": guild_id})
            return 0

        role = guild.get_role(previous_goal.reward_role_id)
        if role is None:
            logger.warning(
                "Previous goal role not found in guild",
                extra={
                    "guild_id": guild_id,
                    "goal_id": previous_goal.id,
                    "role_id": previous_goal.reward_role_id,
                },
            )
            return 0

        participants_result = await self.session.execute(
            select(CommunityGoalParticipant).where(
                and_(
                    CommunityGoalParticipant.goal_id == previous_goal.id,
                    CommunityGoalParticipant.rewarded.is_(True),
                )
            )
        )
        participants = participants_result.scalars().all()

        removed_count = 0
        for participant in participants:
            member = guild.get_member(participant.user_id)
            if member is None or role not in member.roles:
                continue
            await member.remove_roles(role, reason=f"Community goal role cleanup #{previous_goal.id}")
            removed_count += 1

        logger.info(
            "Community goal previous role cleanup finished",
            extra={"guild_id": guild_id, "goal_id": previous_goal.id, "removed_count": removed_count},
        )
        return removed_count
