from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands


class ErrorHandlerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logging.getLogger("anibot")

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("Недостаточно прав для выполнения команды.", delete_after=10)
            return
        self.logger.exception("Command error", exc_info=error)
        await ctx.reply("Произошла ошибка при выполнении команды.", delete_after=10)

    @commands.Cog.listener()
    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Недостаточно прав для выполнения команды.", ephemeral=True
            )
            return
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                "Команда на перезарядке, попробуйте позже.", ephemeral=True
            )
            return
        self.logger.exception("App command error", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send("Произошла ошибка при выполнении команды.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "Произошла ошибка при выполнении команды.", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ErrorHandlerCog(bot))
