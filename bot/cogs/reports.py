from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.reports.monthly import build_monthly_embed
from bot.reports.service import DEFAULT_REPORTS_SETTINGS, MonthlyWrappedService


class ReportsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = MonthlyWrappedService(bot)

    @app_commands.command(name="monthly_wrapped_preview", description="Предпросмотр Monthly Wrapped")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def monthly_wrapped_preview(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        payload = await self.service.preview_last_month(
            guild_id=interaction.guild.id,
            include_sections=DEFAULT_REPORTS_SETTINGS["monthly"]["include_sections"],
            tz_name="UTC",
        )
        embed = build_monthly_embed(payload)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="monthly_wrapped_post", description="Опубликовать Monthly Wrapped сейчас")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def monthly_wrapped_post(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        channel_id = interaction.channel_id
        report = await self.service.post_now(
            guild=interaction.guild,
            channel_id=channel_id,
            include_sections=DEFAULT_REPORTS_SETTINGS["monthly"]["include_sections"],
            tz_name="UTC",
        )
        if report and report.status == "posted":
            await interaction.response.send_message("✅ Monthly Wrapped опубликован.", ephemeral=True)
            return
        await interaction.response.send_message("⚠️ Не удалось опубликовать Monthly Wrapped.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReportsCog(bot))
