from __future__ import annotations

import datetime as dt
import random

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.database.models import JobDefinition, JobRun, UserJobCooldown
from bot.services.buffs import BuffService
from bot.services.economy import EconomyService
from bot.ui import EmbedFactory, reply_error


class WorkSelect(discord.ui.Select):
    def __init__(self, cog: "JobsCog", jobs: list[JobDefinition]) -> None:
        options = [
            discord.SelectOption(
                label=job.name[:100],
                value=str(job.id),
                description=(job.description or f"Награда {job.reward_min}-{job.reward_max}")[:100],
            )
            for job in jobs[:25]
        ]
        super().__init__(placeholder="Выберите работу", min_values=1, max_values=1, options=options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.execute_job(interaction, int(self.values[0]))


class WorkSelectView(discord.ui.View):
    def __init__(self, cog: "JobsCog", jobs: list[JobDefinition], author_id: int) -> None:
        super().__init__(timeout=60)
        self.author_id = author_id
        self.add_item(WorkSelect(cog, jobs))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Это меню не для вас.", ephemeral=True)
            return False
        return True


class JobsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="work", description="Выполнить работу и получить награду")
    async def work(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            rows = await session.execute(
                select(JobDefinition)
                .where(JobDefinition.guild_id == interaction.guild.id, JobDefinition.enabled.is_(True))
                .order_by(JobDefinition.weight.desc(), JobDefinition.id.asc())
            )
            jobs = rows.scalars().all()
        if not jobs:
            await reply_error(interaction, "Список работ пуст.", "Администратор должен добавить хотя бы одну работу в Web Admin.")
            return

        embed = EmbedFactory.info("Выбор работы", "Выберите доступную работу из списка ниже.")
        EmbedFactory.add_section(embed, "💼", "Доступные работы", [f"Всего: {len(jobs)}"])
        await interaction.response.send_message(embed=embed, ephemeral=True, view=WorkSelectView(self, jobs, interaction.user.id))

    async def execute_job(self, interaction: discord.Interaction, job_id: int) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return

        now = dt.datetime.utcnow()
        async with self.bot.db.session() as session:
            async with session.begin():
                job_result = await session.execute(
                    select(JobDefinition).where(JobDefinition.guild_id == interaction.guild.id, JobDefinition.id == job_id, JobDefinition.enabled.is_(True))
                )
                job = job_result.scalars().first()
                if not job:
                    await interaction.response.edit_message(embed=EmbedFactory.error("Работа недоступна", "Попробуйте выбрать другую работу."), view=None)
                    return

                cooldown_result = await session.execute(
                    select(UserJobCooldown).where(
                        UserJobCooldown.guild_id == interaction.guild.id,
                        UserJobCooldown.user_id == interaction.user.id,
                        UserJobCooldown.job_id == job.id,
                    )
                )
                cooldown = cooldown_result.scalars().first()
                if cooldown and cooldown.next_available_at > now:
                    left = cooldown.next_available_at - now
                    minutes = int(left.total_seconds() // 60)
                    await interaction.response.edit_message(
                        embed=EmbedFactory.warn("Кулдаун", f"Эта работа снова будет доступна через {minutes} мин."),
                        view=None,
                    )
                    return

                is_fail = random.random() < float(job.fail_chance)
                base_amount = random.randint(job.penalty_min, job.penalty_max) if is_fail else random.randint(job.reward_min, job.reward_max)
                applied_bonus_percent = 0.0
                final_delta = -int(base_amount) if is_fail else int(base_amount)

                if not is_fail:
                    buffs = await BuffService(session).get_active_buffs(interaction.guild.id, interaction.user.id)
                    applied_bonus_percent = float(buffs.get("jobs_bonus", 0.0))
                    final_delta = int(round(base_amount * (1 + applied_bonus_percent / 100.0)))

                economy = EconomyService(session)
                metadata = {
                    "job_id": job.id,
                    "job_name": job.name,
                    "base_amount": int(base_amount),
                    "jobs_bonus_percent": applied_bonus_percent,
                    "final_amount": int(final_delta),
                }
                if final_delta >= 0:
                    await economy.credit(interaction.guild.id, interaction.user.id, final_delta, "work_job", metadata, ledger_type="earn")
                    outcome = "success"
                else:
                    await economy.debit(interaction.guild.id, interaction.user.id, abs(final_delta), "work_job_fail", metadata, ledger_type="spend")
                    outcome = "fail"

                session.add(
                    JobRun(
                        guild_id=interaction.guild.id,
                        user_id=interaction.user.id,
                        job_id=job.id,
                        ran_at=now,
                        outcome=outcome,
                        amount_delta=int(final_delta),
                        metadata_json=metadata,
                    )
                )

                next_available_at = now + dt.timedelta(seconds=int(job.cooldown_seconds or 0))
                if cooldown:
                    cooldown.next_available_at = next_available_at
                else:
                    session.add(
                        UserJobCooldown(
                            guild_id=interaction.guild.id,
                            user_id=interaction.user.id,
                            job_id=job.id,
                            next_available_at=next_available_at,
                        )
                    )

        if final_delta >= 0:
            embed = EmbedFactory.success("Работа выполнена", f"{job.name}: +{final_delta}")
            EmbedFactory.add_kv(embed, "База", str(base_amount))
            EmbedFactory.add_kv(embed, "jobs_bonus", f"+{applied_bonus_percent:.1f}%")
        else:
            embed = EmbedFactory.warn("Неудача", f"{job.name}: {final_delta}")
            EmbedFactory.add_kv(embed, "Штраф", str(abs(final_delta)))

        await interaction.response.edit_message(embed=embed, view=None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(JobsCog(bot))
