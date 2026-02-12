from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands


class ErrorHandlerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logging.getLogger("anibot")

    @staticmethod
    def _user_message(error: Exception) -> str:
        if isinstance(error, (commands.MissingPermissions, app_commands.MissingPermissions)):
            return "Недостаточно прав. Проверьте роль и попробуйте снова."
        if isinstance(error, app_commands.CommandOnCooldown):
            return "Команда на перезарядке. Подождите немного и повторите."
        if isinstance(error, (commands.BadArgument, app_commands.CommandInvokeError, ValueError)):
            return "Некорректные параметры команды. Проверьте сумму/ID/диапазон и повторите."
        return "Не удалось выполнить команду. Попробуйте позже или проверьте настройки в веб-панели."

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        self.logger.exception("Command error", exc_info=error)
        await ctx.reply(self._user_message(error), delete_after=10)

    @commands.Cog.listener()
    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        self.logger.exception("App command error", exc_info=error)
        message = self._user_message(error)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ErrorHandlerCog(bot))
