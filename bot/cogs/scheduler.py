from __future__ import annotations

import datetime as dt
import logging

from discord.ext import commands, tasks
from sqlalchemy import and_, delete, select, update

from bot.reports.service import MonthlyWrappedService
from bot.community_goals import CommunityGoalService
from bot.database.models import EconomyLedger, GuildConfig, ModLog, ServerMonthlyGoal, UserProfile
from bot.monthly_goals import MonthlyGoalService
from bot.pvp.seasons import PvpSeasonService
from bot.goals.service import MonthlyCommunityGoalService

logger = logging.getLogger(__name__)


class SchedulerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.monthly_reports_service = MonthlyWrappedService(bot)
        self.daily_reset_task.start()
        self.cleanup_task.start()
        self.community_goals_task.start()
        self.monthly_goals_task.start()
        self.monthly_reports_task.start()
        self.monthly_community_goals_v2_task.start()
        self.pvp_seasons_task.start()

    def cog_unload(self) -> None:
        self.daily_reset_task.cancel()
        self.cleanup_task.cancel()
        self.community_goals_task.cancel()
        self.monthly_goals_task.cancel()
        self.monthly_reports_task.cancel()
        self.monthly_community_goals_v2_task.cancel()
        self.pvp_seasons_task.cancel()

    @tasks.loop(hours=24)
    async def daily_reset_task(self) -> None:
        async with self.bot.db.session() as session:
            async with session.begin():
                await session.execute(update(UserProfile).values(daily_bet_amount=0, daily_xp=0))

    @tasks.loop(hours=12)
    async def cleanup_task(self) -> None:
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=90)
        async with self.bot.db.session() as session:
            async with session.begin():
                await session.execute(delete(EconomyLedger).where(EconomyLedger.timestamp < cutoff))
                await session.execute(delete(ModLog).where(ModLog.created_at < cutoff))

    @tasks.loop(minutes=10)
    async def community_goals_task(self) -> None:
        for guild in self.bot.guilds:
            try:
                async with self.bot.db.session() as session:
                    async with session.begin():
                        service = CommunityGoalService(session)
                        goal = await service.get_active_goal(guild.id)
                        if goal is None:
                            continue

                        now = dt.datetime.utcnow()
                        if goal.status != "active" or now < goal.ends_at:
                            continue

                        evaluated_goal = await service.evaluate_goal(guild.id)
                        if evaluated_goal is None:
                            continue

                        if evaluated_goal.status == "completed":
                            removed_count = await service.remove_previous_goal_roles(self.bot, guild.id)
                            rewarded_count = await service.distribute_rewards(self.bot, guild.id)
                            logger.info(
                                "Community goal completed and rewards processed",
                                extra={
                                    "guild_id": guild.id,
                                    "goal_id": evaluated_goal.id,
                                    "removed_previous_roles": removed_count,
                                    "rewarded_members": rewarded_count,
                                },
                            )
                        else:
                            logger.info(
                                "Community goal finished with failed status",
                                extra={"guild_id": guild.id, "goal_id": evaluated_goal.id},
                            )
            except Exception:
                logger.exception(
                    "Community goal scheduler iteration failed",
                    extra={"guild_id": guild.id},
                )

    @tasks.loop(hours=24)
    async def monthly_goals_task(self) -> None:
        current_month = dt.datetime.utcnow().strftime("%Y-%m")
        previous_month_date = dt.datetime.utcnow().replace(day=1) - dt.timedelta(days=1)
        previous_month = previous_month_date.strftime("%Y-%m")

        async with self.bot.db.session() as session:
            async with session.begin():
                service = MonthlyGoalService(session)

                # Auto-deactivate previous month goals on month rollover.
                await session.execute(
                    update(ServerMonthlyGoal)
                    .where(
                        and_(
                            ServerMonthlyGoal.month == previous_month,
                            ServerMonthlyGoal.is_active.is_(True),
                        )
                    )
                    .values(is_active=False)
                )

                result = await session.execute(
                    select(ServerMonthlyGoal).where(ServerMonthlyGoal.is_active.is_(True))
                )
                active_goals = result.scalars().all()

                for goal in active_goals:
                    completion = await service.check_and_complete_goal(goal.guild_id, goal.month)
                    if completion is None or not completion.completed:
                        continue

                    eligible_users = await service.get_eligible_users(
                        goal.guild_id,
                        goal.metric_type,
                        goal.month,
                        goal.min_user_contribution,
                    )

                    assigned_count = await service.assign_reward_role(
                        bot=self.bot,
                        guild_id=goal.guild_id,
                        reward_role_id=goal.reward_role_id,
                        user_ids=eligible_users,
                        reason=f"Monthly goal reward {goal.month}",
                    )

                    logger.info(
                        "Monthly goal completed and rewards assigned",
                        extra={
                            "guild_id": goal.guild_id,
                            "goal_id": goal.id,
                            "month": goal.month,
                            "metric_type": goal.metric_type,
                            "progress": completion.progress,
                            "target": goal.target_value,
                            "eligible_count": len(eligible_users),
                            "assigned_count": assigned_count,
                        },
                    )

                previous_result = await session.execute(
                    select(ServerMonthlyGoal).where(
                        and_(
                            ServerMonthlyGoal.month == previous_month,
                            ServerMonthlyGoal.completed_at.is_not(None),
                            ServerMonthlyGoal.reward_role_id.is_not(None),
                        )
                    )
                )
                for old_goal in previous_result.scalars().all():
                    old_users = await service.get_eligible_users(
                        old_goal.guild_id,
                        old_goal.metric_type,
                        old_goal.month,
                        old_goal.min_user_contribution,
                    )
                    removed_count = await service.remove_reward_role(
                        bot=self.bot,
                        guild_id=old_goal.guild_id,
                        reward_role_id=old_goal.reward_role_id,
                        user_ids=old_users,
                        reason=f"Monthly goal cleanup {old_goal.month}",
                    )
                    if removed_count:
                        logger.info(
                            "Monthly goal previous month role cleanup completed",
                            extra={
                                "guild_id": old_goal.guild_id,
                                "goal_id": old_goal.id,
                                "month": old_goal.month,
                                "removed_count": removed_count,
                            },
                        )


    @tasks.loop(minutes=15)
    async def pvp_seasons_task(self) -> None:
        now = dt.datetime.utcnow()
        async with self.bot.db.session() as session:
            async with session.begin():
                result = await session.execute(select(GuildConfig))
                for config in result.scalars().all():
                    try:
                        service = PvpSeasonService(session, self.bot)
                        await service.process_rotation_for_guild(int(config.guild_id), now)
                    except Exception:
                        logger.exception(
                            "PvP season scheduler iteration failed",
                            extra={"guild_id": int(config.guild_id)},
                        )

    @tasks.loop(minutes=10)
    async def monthly_reports_task(self) -> None:
        try:
            await self.monthly_reports_service.run_scheduler_tick()
        except Exception:
            logger.exception("Monthly reports scheduler iteration failed")

    @tasks.loop(minutes=20)
    async def monthly_community_goals_v2_task(self) -> None:
        try:
            async with self.bot.db.session() as session:
                async with session.begin():
                    service = MonthlyCommunityGoalService(session)
                    await service.scheduler_tick(self.bot)
        except Exception:
            logger.exception("Monthly community goals v2 scheduler iteration failed")


    @daily_reset_task.before_loop
    @cleanup_task.before_loop
    @community_goals_task.before_loop
    @monthly_goals_task.before_loop
    @monthly_reports_task.before_loop
    @pvp_seasons_task.before_loop
    @monthly_community_goals_v2_task.before_loop
    async def before_tasks(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
