from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import discord
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import EconomyLedger, EconomyTransaction, ServerMonthlyGoal, UserProfile

logger = logging.getLogger(__name__)

SUPPORTED_GOAL_METRICS = {"voice_hours", "messages", "bets_volume"}


@dataclass(slots=True)
class GoalCompletionResult:
    goal: ServerMonthlyGoal
    progress: float
    completed: bool


class MonthlyGoalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def month_bounds(month: str) -> tuple[dt.datetime, dt.datetime]:
        start = dt.datetime.strptime(f"{month}-01", "%Y-%m-%d")
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end

    async def get_active_goal(self, guild_id: int, month: str) -> ServerMonthlyGoal | None:
        result = await self.session.execute(
            select(ServerMonthlyGoal).where(
                and_(
                    ServerMonthlyGoal.guild_id == guild_id,
                    ServerMonthlyGoal.month == month,
                    ServerMonthlyGoal.is_active.is_(True),
                )
            )
        )
        return result.scalars().first()

    async def calculate_progress(self, guild_id: int, metric_type: str, month: str) -> float:
        if metric_type not in SUPPORTED_GOAL_METRICS:
            raise ValueError("Неподдерживаемый тип метрики месячной цели.")

        starts_at, ends_at = self.month_bounds(month)
        if metric_type == "voice_hours":
            result = await self.session.execute(
                select(func.coalesce(func.sum(EconomyLedger.amount), 0)).where(
                    and_(
                        EconomyLedger.guild_id == guild_id,
                        EconomyLedger.source == "voice_activity",
                        EconomyLedger.type == "earn",
                        EconomyLedger.timestamp >= starts_at,
                        EconomyLedger.timestamp < ends_at,
                    )
                )
            )
            total_voice_seconds = float(result.scalar() or 0)
            return total_voice_seconds / 3600.0

        if metric_type == "messages":
            # Current analytics relies on message timestamps in UserProfile,
            # therefore this count follows the same aggregation strategy.
            result = await self.session.execute(
                select(func.coalesce(func.count(UserProfile.id), 0)).where(
                    and_(
                        UserProfile.guild_id == guild_id,
                        UserProfile.last_message_ts.is_not(None),
                        UserProfile.last_message_ts >= starts_at,
                        UserProfile.last_message_ts < ends_at,
                    )
                )
            )
            return float(result.scalar() or 0)

        result = await self.session.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (EconomyTransaction.source == "bet_placement")
                                & (EconomyTransaction.amount < 0),
                                -EconomyTransaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                )
            ).where(
                and_(
                    EconomyTransaction.guild_id == guild_id,
                    EconomyTransaction.created_at >= starts_at,
                    EconomyTransaction.created_at < ends_at,
                )
            )
        )
        return float(result.scalar() or 0)

    async def check_and_complete_goal(self, guild_id: int, month: str) -> GoalCompletionResult | None:
        goal = await self.get_active_goal(guild_id, month)
        if goal is None:
            return None

        progress = await self.calculate_progress(guild_id, goal.metric_type, month)
        completed = progress >= goal.target_value
        if completed and goal.completed_at is None:
            goal.completed_at = dt.datetime.utcnow()
            goal.is_active = False
            await self.session.flush()

        return GoalCompletionResult(goal=goal, progress=progress, completed=completed)

    async def get_eligible_users(
        self,
        guild_id: int,
        metric_type: str,
        month: str,
        min_user_contribution: float,
    ) -> list[int]:
        starts_at, ends_at = self.month_bounds(month)
        if metric_type == "voice_hours":
            result = await self.session.execute(
                select(
                    EconomyLedger.user_id,
                    (func.coalesce(func.sum(EconomyLedger.amount), 0) / 3600.0).label("contribution"),
                )
                .where(
                    and_(
                        EconomyLedger.guild_id == guild_id,
                        EconomyLedger.source == "voice_activity",
                        EconomyLedger.type == "earn",
                        EconomyLedger.timestamp >= starts_at,
                        EconomyLedger.timestamp < ends_at,
                    )
                )
                .group_by(EconomyLedger.user_id)
                .having((func.coalesce(func.sum(EconomyLedger.amount), 0) / 3600.0) >= min_user_contribution)
            )
            return [int(row.user_id) for row in result]

        if metric_type == "messages":
            result = await self.session.execute(
                select(UserProfile.user_id)
                .where(
                    and_(
                        UserProfile.guild_id == guild_id,
                        UserProfile.last_message_ts.is_not(None),
                        UserProfile.last_message_ts >= starts_at,
                        UserProfile.last_message_ts < ends_at,
                    )
                )
                .group_by(UserProfile.user_id)
                .having(func.count(UserProfile.id) >= min_user_contribution)
            )
            return [int(row.user_id) for row in result]

        if metric_type == "bets_volume":
            result = await self.session.execute(
                select(
                    EconomyTransaction.user_id,
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (EconomyTransaction.source == "bet_placement")
                                    & (EconomyTransaction.amount < 0),
                                    -EconomyTransaction.amount,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("contribution"),
                )
                .where(
                    and_(
                        EconomyTransaction.guild_id == guild_id,
                        EconomyTransaction.created_at >= starts_at,
                        EconomyTransaction.created_at < ends_at,
                    )
                )
                .group_by(EconomyTransaction.user_id)
                .having(
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (EconomyTransaction.source == "bet_placement")
                                    & (EconomyTransaction.amount < 0),
                                    -EconomyTransaction.amount,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    )
                    >= min_user_contribution
                )
            )
            return [int(row.user_id) for row in result]

        raise ValueError("Неподдерживаемый тип метрики месячной цели.")

    async def assign_reward_role(
        self,
        *,
        bot: discord.Client,
        guild_id: int,
        reward_role_id: int,
        user_ids: list[int],
        reason: str,
    ) -> int:
        guild = bot.get_guild(guild_id)
        if guild is None:
            logger.warning("Guild not found in bot cache", extra={"guild_id": guild_id})
            return 0

        role = guild.get_role(reward_role_id)
        if role is None:
            logger.warning(
                "Reward role not found in guild",
                extra={"guild_id": guild_id, "role_id": reward_role_id},
            )
            return 0

        assigned = 0
        for user_id in user_ids:
            member = guild.get_member(user_id)
            if member is None:
                continue
            if role in member.roles:
                continue
            await member.add_roles(role, reason=reason)
            assigned += 1
        return assigned

    async def remove_reward_role(
        self,
        *,
        bot: discord.Client,
        guild_id: int,
        reward_role_id: int,
        user_ids: list[int],
        reason: str,
    ) -> int:
        guild = bot.get_guild(guild_id)
        if guild is None:
            return 0
        role = guild.get_role(reward_role_id)
        if role is None:
            return 0

        removed = 0
        for user_id in user_ids:
            member = guild.get_member(user_id)
            if member is None or role not in member.roles:
                continue
            await member.remove_roles(role, reason=reason)
            removed += 1
        return removed
