from __future__ import annotations

import datetime as dt
import logging

from discord.ext import commands, tasks
from sqlalchemy import delete, update

from bot.analytics.monthly_reports import MonthlyAnalyticsReportService
from bot.community_goals import CommunityGoalService
from bot.database.models import EconomyLedger, ModLog, UserProfile

logger = logging.getLogger(__name__)


class SchedulerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.monthly_reports_service = MonthlyAnalyticsReportService(bot)
        self.daily_reset_task.start()
        self.cleanup_task.start()
        self.community_goals_task.start()
        self.monthly_reports_task.start()

    def cog_unload(self) -> None:
        self.daily_reset_task.cancel()
        self.cleanup_task.cancel()
        self.community_goals_task.cancel()
        self.monthly_reports_task.cancel()

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


    @tasks.loop(time=dt.time(hour=0, minute=10, tzinfo=dt.timezone.utc))
    async def monthly_reports_task(self) -> None:
        try:
            await self.monthly_reports_service.run_daily()
        except Exception:
            logger.exception("Monthly reports scheduler iteration failed")

    @daily_reset_task.before_loop
    @cleanup_task.before_loop
    @community_goals_task.before_loop
    @monthly_reports_task.before_loop
    async def before_tasks(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
