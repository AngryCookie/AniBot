from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from bot.database.models import GuildConfig, GuildGoalTemplate, GuildMonthlyGoal, GuildMonthlyGoalContribution
from bot.goals.service import MonthlyCommunityGoalService


class MonthlyGoalsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="goal", description="Показать прогресс текущей цели месяца")
    async def goal(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        async with self.bot.db.session() as session:
            goal = (
                await session.execute(
                    select(GuildMonthlyGoal)
                    .where(GuildMonthlyGoal.guild_id == interaction.guild.id)
                    .order_by(GuildMonthlyGoal.month.desc())
                )
            ).scalars().first()
            if goal is None:
                await interaction.response.send_message("Цель месяца ещё не создана.", ephemeral=True)
                return
            eligible = await session.scalar(
                select(func.count())
                .select_from(GuildMonthlyGoalContribution)
                .where((GuildMonthlyGoalContribution.goal_id == goal.id) & (GuildMonthlyGoalContribution.eligible.is_(True)))
            )

        percent = (float(goal.progress_value) / float(goal.target_value) * 100.0) if goal.target_value > 0 else 0.0
        left = max(0, int((goal.ends_at - dt.datetime.utcnow()).total_seconds() // 86400))
        embed = discord.Embed(title="🎯 Цель месяца", color=discord.Color.blurple(), timestamp=dt.datetime.utcnow())
        embed.add_field(name="Тип", value=goal.goal_type, inline=True)
        embed.add_field(name="Прогресс", value=f"{goal.progress_value}/{goal.target_value}", inline=True)
        embed.add_field(name="Выполнение", value=f"{max(0,min(100,percent)):.1f}%", inline=True)
        embed.add_field(name="Статус", value=goal.status, inline=True)
        embed.add_field(name="Дней осталось", value=str(left), inline=True)
        embed.add_field(name="Подходящих участников", value=str(int(eligible or 0)), inline=True)
        embed.set_footer(text=f"Месяц: {goal.month.isoformat()}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="goal_top", description="Топ участников цели месяца")
    async def goal_top(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            goal = (await session.execute(select(GuildMonthlyGoal).where(GuildMonthlyGoal.guild_id == interaction.guild.id).order_by(GuildMonthlyGoal.month.desc()))).scalars().first()
            if goal is None:
                await interaction.response.send_message("Нет активной цели.", ephemeral=True)
                return
            rows = (await session.execute(select(GuildMonthlyGoalContribution).where(GuildMonthlyGoalContribution.goal_id == goal.id).order_by(GuildMonthlyGoalContribution.contribution_value.desc()).limit(20))).scalars().all()
        lines = [f"{idx+1}. <@{r.user_id}> — {r.contribution_value}" for idx, r in enumerate(rows)] or ["—"]
        await interaction.response.send_message(embed=discord.Embed(title="🏆 Топ участников цели", description="\n".join(lines), color=discord.Color.gold()))

    @app_commands.command(name="goal_set_template", description="Выбрать шаблон цели для текущего месяца")
    @app_commands.describe(template_id="ID шаблона")
    @app_commands.default_permissions(manage_guild=True)
    async def goal_set_template(self, interaction: discord.Interaction, template_id: int) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            cfg = (await session.execute(select(GuildConfig).where(GuildConfig.guild_id == interaction.guild.id))).scalars().first()
            if cfg is None:
                cfg = GuildConfig(guild_id=interaction.guild.id)
                session.add(cfg)
                await session.flush()
            service = MonthlyCommunityGoalService(session)
            settings = service.parse_settings(cfg.settings)
            tmpl = (await session.execute(select(GuildGoalTemplate).where((GuildGoalTemplate.guild_id == interaction.guild.id) & (GuildGoalTemplate.id == template_id)))).scalars().first()
            if tmpl is None:
                await interaction.response.send_message("Шаблон не найден.", ephemeral=True)
                return
            settings["default_template_id"] = int(template_id)
            cfg.settings = service.save_settings(cfg.settings, settings)
            await session.commit()
        await interaction.response.send_message("✅ Шаблон установлен для автогенерации.", ephemeral=True)

    @app_commands.command(name="goal_force_close", description="Принудительно закрыть прошлый месяц")
    @app_commands.default_permissions(manage_guild=True)
    async def goal_force_close(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db.session() as session:
            service = MonthlyCommunityGoalService(session)
            row = (await session.execute(select(GuildMonthlyGoal).where((GuildMonthlyGoal.guild_id == interaction.guild.id) & (GuildMonthlyGoal.closed_at.is_(None))).order_by(GuildMonthlyGoal.month.asc()))).scalars().first()
            if row is None:
                await interaction.followup.send("Нет открытой цели для закрытия.", ephemeral=True)
                return
            await service.recalc_progress(interaction.guild.id, int(row.id), row.started_at, row.ends_at)
            await service.recalc_contributions(interaction.guild.id, int(row.id), row.started_at, row.ends_at)
            result = await service.close_monthly_goal(interaction.guild, int(row.id), dt.datetime.utcnow())
            await session.commit()
        await interaction.followup.send(f"Готово: {result}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MonthlyGoalsCog(bot))
