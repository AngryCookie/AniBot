from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands

from bot.monthly_goals import MonthlyGoalService


class MonthlyGoalsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="goal", description="Показать прогресс месячной цели сервера")
    async def goal(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        month = dt.datetime.utcnow().strftime("%Y-%m")
        async with self.bot.db.session() as session:
            service = MonthlyGoalService(session)
            goal = await service.get_active_goal(interaction.guild.id, month)
            if goal is None:
                await interaction.response.send_message(
                    "На этот месяц активная цель не настроена.", ephemeral=True
                )
                return

            progress = await service.calculate_progress(
                interaction.guild.id,
                goal.metric_type,
                goal.month,
            )

        target = float(goal.target_value)
        percent = min(100.0, (progress / target) * 100.0) if target > 0 else 0.0
        remaining = max(0.0, target - progress)

        metric_labels = {
            "voice_hours": "Голосовые часы",
            "messages": "Сообщения",
            "bets_volume": "Объём ставок",
        }

        reward_role_mention = f"<@&{goal.reward_role_id}>"

        embed = discord.Embed(
            title="🎯 Месячная цель сервера",
            color=discord.Color.blurple(),
            timestamp=dt.datetime.utcnow(),
        )
        embed.add_field(name="Метрика", value=metric_labels.get(goal.metric_type, goal.metric_type), inline=True)
        embed.add_field(name="Прогресс", value=f"{progress:.2f} / {target:.2f}", inline=True)
        embed.add_field(name="Выполнение", value=f"{percent:.1f}%", inline=True)
        embed.add_field(name="Осталось", value=f"{remaining:.2f}", inline=True)
        embed.add_field(name="Награда", value=reward_role_mention, inline=True)
        embed.set_footer(text=f"Период: {goal.month}")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MonthlyGoalsCog(bot))
