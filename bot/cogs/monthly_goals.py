from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from bot.database.models import GuildConfig, GuildGoalTemplate, GuildMonthlyGoal, GuildMonthlyGoalContribution
from bot.goals.service import MonthlyCommunityGoalService
from bot.ui import ConfirmView, EmbedFactory, PaginationView


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
        embed = EmbedFactory.info("Цель месяца", "Прогресс сервера и условия участия.")
        EmbedFactory.add_kv(embed, "🎯 Тип", goal.goal_type)
        EmbedFactory.add_kv(embed, "📈 Прогресс", f"{goal.progress_value}/{goal.target_value}")
        EmbedFactory.add_kv(embed, "🏁 Выполнение", f"{max(0, min(100, percent)):.1f}%")
        EmbedFactory.add_kv(embed, "📌 Статус", goal.status)
        EmbedFactory.add_kv(embed, "🗓️ Дней осталось", str(left))
        EmbedFactory.add_kv(embed, "👥 Eligible", str(int(eligible or 0)))
        EmbedFactory.add_section(
            embed,
            "💡",
            "Как участвовать",
            [
                "Вносите вклад в метрику текущей цели.",
                "Порог eligibility проверяется автоматически.",
                "При успешном закрытии месяца роль награды ротируется на новых победителей.",
            ],
        )
        embed.set_footer(text=f"Месяц: {goal.month.isoformat()} • ⏳ Кнопки активны 60с • AniBot")
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
        if not rows:
            await interaction.response.send_message(embed=EmbedFactory.warn("Топ участников", "Пока нет данных по вкладам."), ephemeral=True)
            return

        pages: list[discord.Embed] = []
        for start in range(0, len(rows), 10):
            chunk = rows[start : start + 10]
            lines = [f"{start + idx + 1}. <@{r.user_id}> — {int(r.contribution_value)}" for idx, r in enumerate(chunk)]
            page = EmbedFactory.info("Топ участников цели", "Рейтинг по вкладу за текущий месяц")
            page.description = "\n".join(lines)
            page.set_footer(text=f"Страница {len(pages) + 1}/{((len(rows)-1)//10)+1} • ⏳ Кнопки активны 60с • AniBot")
            pages.append(page)

        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0])
            return

        view = PaginationView(author_id=interaction.user.id, pages=pages, timeout=60)
        await interaction.response.send_message(embed=pages[0], view=view)
        view.message = await interaction.original_response()

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
        async def _confirm(confirm_interaction: discord.Interaction) -> None:
            await confirm_interaction.response.defer(ephemeral=True)
            async with self.bot.db.session() as session:
                service = MonthlyCommunityGoalService(session)
                row = (await session.execute(select(GuildMonthlyGoal).where((GuildMonthlyGoal.guild_id == interaction.guild.id) & (GuildMonthlyGoal.closed_at.is_(None))).order_by(GuildMonthlyGoal.month.asc()))).scalars().first()
                if row is None:
                    await confirm_interaction.followup.send("Нет открытой цели для закрытия.", ephemeral=True)
                    return
                await service.recalc_progress(interaction.guild.id, int(row.id), row.started_at, row.ends_at)
                await service.recalc_contributions(interaction.guild.id, int(row.id), row.started_at, row.ends_at)
                result = await service.close_monthly_goal(interaction.guild, int(row.id), dt.datetime.utcnow())
                await session.commit()
            await confirm_interaction.followup.send(embed=EmbedFactory.success("Цель закрыта", f"Результат: `{result}`"), ephemeral=True)

        embed = EmbedFactory.warn("Принудительное закрытие цели", "Подтвердите закрытие открытой цели. Действие изменит роли победителей.")
        view = ConfirmView(author_id=interaction.user.id, on_confirm=_confirm, timeout=60)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MonthlyGoalsCog(bot))
