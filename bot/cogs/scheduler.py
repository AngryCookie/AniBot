from __future__ import annotations

import datetime as dt

from discord.ext import commands, tasks
from sqlalchemy import delete, update

from bot.database.models import EconomyLedger, ModLog, UserProfile


class SchedulerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.daily_reset_task.start()
        self.cleanup_task.start()

    def cog_unload(self) -> None:
        self.daily_reset_task.cancel()
        self.cleanup_task.cancel()

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

    @daily_reset_task.before_loop
    @cleanup_task.before_loop
    async def before_tasks(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
