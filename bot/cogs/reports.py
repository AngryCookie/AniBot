from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.database.models import GuildConfig
from bot.reports.monthly import build_monthly_embed
from bot.reports.service import DEFAULT_REPORTS_SETTINGS, MonthlyWrappedService
from bot.reports.yearly import build_yearly_embed


class ReportsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = MonthlyWrappedService(bot)

    async def _guild_reports_settings(self, guild_id: int) -> dict:
        async with self.bot.db.session() as session:
            result = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
            config = result.scalars().first()
        if config is None:
            return DEFAULT_REPORTS_SETTINGS
        return self.service._load_reports_settings(config.settings)

    @app_commands.command(name="monthly_wrapped_preview", description="Предпросмотр Monthly Wrapped")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def monthly_wrapped_preview(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        settings = await self._guild_reports_settings(interaction.guild.id)
        payload = await self.service.preview_last_month(
            guild_id=interaction.guild.id,
            include_sections=settings["monthly"]["include_sections"],
            tz_name=settings.get("timezone", "UTC"),
        )
        embed = build_monthly_embed(payload)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="monthly_wrapped_post", description="Опубликовать Monthly Wrapped сейчас")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def monthly_wrapped_post(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        settings = await self._guild_reports_settings(interaction.guild.id)
        channel_id = interaction.channel_id
        report = await self.service.post_now(
            guild=interaction.guild,
            channel_id=channel_id,
            include_sections=settings["monthly"]["include_sections"],
            tz_name=settings.get("timezone", "UTC"),
        )
        if report and report.status == "posted":
            await interaction.response.send_message("✅ Monthly Wrapped опубликован.", ephemeral=True)
            return
        await interaction.response.send_message("⚠️ Не удалось опубликовать Monthly Wrapped.", ephemeral=True)

    @app_commands.command(name="yearly_wrapped_preview", description="Предпросмотр Yearly Wrapped")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yearly_wrapped_preview(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        settings = await self._guild_reports_settings(interaction.guild.id)
        payload = await self.service.preview_last_year(
            guild_id=interaction.guild.id,
            include_sections=settings["yearly"]["include_sections"],
            tz_name=settings.get("timezone", "UTC"),
        )
        embed = build_yearly_embed(payload)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="yearly_wrapped_post", description="Опубликовать Yearly Wrapped сейчас")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yearly_wrapped_post(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        settings = await self._guild_reports_settings(interaction.guild.id)
        channel_id = settings["yearly"].get("channel_id") or interaction.channel_id
        report = await self.service.post_yearly_now(
            guild=interaction.guild,
            channel_id=int(channel_id),
            include_sections=settings["yearly"]["include_sections"],
            tz_name=settings.get("timezone", "UTC"),
        )
        if report and report.status == "posted":
            await interaction.response.send_message("✅ Yearly Wrapped опубликован.", ephemeral=True)
            return
        await interaction.response.send_message("⚠️ Не удалось опубликовать Yearly Wrapped.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReportsCog(bot))
