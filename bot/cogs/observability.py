from __future__ import annotations

import logging
import time

from discord.ext import commands

logger = logging.getLogger("anibot.commands")


class ObservabilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._start_times: dict[int, float] = {}

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        if ctx.command:
            self._start_times[ctx.message.id] = time.monotonic()

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        if ctx.command:
            start = self._start_times.pop(ctx.message.id, None)
            duration_ms = None if start is None else (time.monotonic() - start) * 1000
            logger.info(
                "command.completed",
                extra={
                    "command": ctx.command.qualified_name,
                    "guild_id": getattr(ctx.guild, "id", None),
                    "user_id": getattr(ctx.author, "id", None),
                    "duration_ms": duration_ms,
                },
            )

    @commands.Cog.listener()
    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        logger.error(
            "command.error",
            extra={
                "command": getattr(ctx.command, "qualified_name", None),
                "guild_id": getattr(ctx.guild, "id", None),
                "user_id": getattr(ctx.author, "id", None),
                "error": str(error),
            },
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ObservabilityCog(bot))
