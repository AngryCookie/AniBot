from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.analytics.economy import build_economy_analytics
from bot.cogs.utils import get_or_create_guild
from bot.database.models import CustomCommand, ModLog, Tag
from bot.database.operations import get_or_create_user_locked
from bot.services.economy import EconomyService


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    economy_group = app_commands.Group(name="economy", description="Управление экономикой")

    rate_group = app_commands.Group(name="rate", parent=economy_group, description="Курс валюты")

    @rate_group.command(name="set", description="Установить курс")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rate_set(self, interaction: discord.Interaction, rate: float) -> None:
        if rate < 0.5 or rate > 3.0:
            await interaction.response.send_message("Курс должен быть 0.5-3.0.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            async with session.begin():
                guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
                guild.server_rate = rate
        await interaction.response.send_message("Курс обновлен.", ephemeral=True)

    @rate_group.command(name="info", description="Посмотреть курс")
    async def rate_info(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
        await interaction.response.send_message(
            f"Текущий курс: {guild.server_rate}", ephemeral=True
        )

    @rate_group.command(name="reset", description="Сбросить курс")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rate_reset(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            async with session.begin():
                guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
                guild.server_rate = 1.0
        await interaction.response.send_message("Курс сброшен.", ephemeral=True)

    @economy_group.command(name="give", description="Выдать валюту")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def economy_give(
        self, interaction: discord.Interaction, member: discord.Member, amount: int
    ) -> None:
        async with self.bot.db.session() as session:
            async with session.begin():
                await get_or_create_user_locked(session, interaction.guild.id, member.id)
                await EconomyService(session).admin_grant(
                    guild_id=interaction.guild.id,
                    user_id=member.id,
                    amount=amount,
                    source="admin_give",
                    metadata={"moderator_id": interaction.user.id},
                )
                log = ModLog(
                    guild_id=interaction.guild.id,
                    action="economy_give",
                    moderator_id=interaction.user.id,
                    user_id=member.id,
                    reason=f"+{amount}",
                )
                session.add(log)
        await interaction.response.send_message("Баланс обновлен.", ephemeral=True)

    @economy_group.command(name="take", description="Снять валюту")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def economy_take(
        self, interaction: discord.Interaction, member: discord.Member, amount: int
    ) -> None:
        async with self.bot.db.session() as session:
            async with session.begin():
                user = await get_or_create_user_locked(session, interaction.guild.id, member.id)
                delta = -min(amount, user.balance)
                if delta:
                    await EconomyService(session).admin_remove(
                        guild_id=interaction.guild.id,
                        user_id=member.id,
                        amount=abs(delta),
                        source="admin_take",
                        metadata={"moderator_id": interaction.user.id},
                    )
                log = ModLog(
                    guild_id=interaction.guild.id,
                    action="economy_take",
                    moderator_id=interaction.user.id,
                    user_id=member.id,
                    reason=f"{delta}",
                )
                session.add(log)
        await interaction.response.send_message("Баланс обновлен.", ephemeral=True)

    @economy_group.command(name="reset", description="Сбросить пользователя")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def economy_reset(self, interaction: discord.Interaction, member: discord.Member) -> None:
        async with self.bot.db.session() as session:
            async with session.begin():
                user = await get_or_create_user_locked(session, interaction.guild.id, member.id)
                if user.balance > 0:
                    await EconomyService(session).admin_remove(
                        guild_id=interaction.guild.id,
                        user_id=member.id,
                        amount=user.balance,
                        source="admin_reset",
                        metadata={"moderator_id": interaction.user.id},
                    )
                user.xp = 0
                user.level = 1
                log = ModLog(
                    guild_id=interaction.guild.id,
                    action="economy_reset",
                    moderator_id=interaction.user.id,
                    user_id=member.id,
                    reason="reset",
                )
                session.add(log)
        await interaction.response.send_message("Профиль сброшен.", ephemeral=True)

    @economy_group.command(name="log", description="Лог экономических операций")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def economy_log(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            logs = await session.execute(
                select(ModLog)
                .where(ModLog.guild_id == interaction.guild.id)
                .where(ModLog.action.like("economy%"))
                .order_by(ModLog.created_at.desc())
                .limit(10)
            )
            logs = logs.scalars().all()
        if not logs:
            await interaction.response.send_message("Лог пуст.", ephemeral=True)
            return
        description = "\n".join(
            [f"{log.created_at.date()} {log.action} {log.user_id} {log.reason}" for log in logs]
        )
        embed = discord.Embed(title="Economy log", description=description)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @economy_group.command(name="analytics", description="Экономическая аналитика")
    @app_commands.describe(period="Период аналитики в днях")
    @app_commands.choices(
        period=[
            app_commands.Choice(name="7 дней", value=7),
            app_commands.Choice(name="30 дней", value=30),
            app_commands.Choice(name="90 дней", value=90),
        ]
    )
    async def economy_analytics(
        self, interaction: discord.Interaction, period: app_commands.Choice[int]
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        await interaction.response.defer(ephemeral=True)

        analytics = await build_economy_analytics(
            database=self.bot.db,
            guild_id=interaction.guild.id,
            period_days=period.value,
        )

        distribution = analytics["distribution"]
        activity = analytics["activity"]
        health = analytics["health"]

        embed = discord.Embed(
            title="Экономическая аналитика",
            description=f"Период: {analytics['period_days']} дней",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Поток валюты",
            value=(
                f"Начислено: {analytics['created']:.0f}\n"
                f"Списано: {analytics['spent']:.0f}\n"
                f"Чистый поток: {analytics['net_flow']}\n"
                "ℹ️ Приток и отток валюты за период."
            ),
            inline=False,
        )
        embed.add_field(
            name="Распределение",
            value=(
                f"Средний баланс: {distribution['average_balance']:.2f}\n"
                f"Медианный баланс: {distribution['median_balance']:.2f}\n"
                f"Доля топ-10%: {distribution['top_10_percent_share'] * 100:.1f}%\n"
                "ℹ️ Показывает концентрацию валюты."
            ),
            inline=False,
        )
        embed.add_field(
            name="Активность",
            value=(
                f"Активные пользователи: {activity['active_users']}\n"
                f"Доля активных: {activity['active_users_percent'] * 100:.1f}%\n"
                "ℹ️ Доля участников с операциями."
            ),
            inline=False,
        )
        embed.add_field(
            name="Здоровье экономики",
            value=(
                f"Sink-коэффициент: {health['sink_ratio']:.2f}\n"
                f"Флаг инфляции: {'Да' if health['inflation_flag'] else 'Нет'}\n"
                "ℹ️ Баланс начислений и списаний."
            ),
            inline=False,
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    cc_group = app_commands.Group(name="cc", description="Кастомные команды")

    @cc_group.command(name="create", description="Создать кастомную команду")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cc_create(self, interaction: discord.Interaction, name: str, response: str) -> None:
        async with self.bot.db.session() as session:
            cc = CustomCommand(guild_id=interaction.guild.id, name=name, response=response)
            session.add(cc)
            await session.commit()
        await interaction.response.send_message("Команда создана.", ephemeral=True)

    @cc_group.command(name="edit", description="Изменить кастомную команду")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cc_edit(self, interaction: discord.Interaction, name: str, response: str) -> None:
        async with self.bot.db.session() as session:
            result = await session.execute(
                select(CustomCommand).where(
                    (CustomCommand.guild_id == interaction.guild.id)
                    & (CustomCommand.name == name)
                )
            )
            cc = result.scalars().first()
            if not cc:
                await interaction.response.send_message("Команда не найдена.", ephemeral=True)
                return
            cc.response = response
            await session.commit()
        await interaction.response.send_message("Команда обновлена.", ephemeral=True)

    @cc_group.command(name="delete", description="Удалить кастомную команду")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cc_delete(self, interaction: discord.Interaction, name: str) -> None:
        async with self.bot.db.session() as session:
            result = await session.execute(
                select(CustomCommand).where(
                    (CustomCommand.guild_id == interaction.guild.id)
                    & (CustomCommand.name == name)
                )
            )
            cc = result.scalars().first()
            if cc:
                await session.delete(cc)
                await session.commit()
        await interaction.response.send_message("Команда удалена.", ephemeral=True)

    @cc_group.command(name="list", description="Список кастомных команд")
    async def cc_list(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            result = await session.execute(
                select(CustomCommand).where(CustomCommand.guild_id == interaction.guild.id)
            )
            commands_list = result.scalars().all()
        if not commands_list:
            await interaction.response.send_message("Список пуст.", ephemeral=True)
            return
        names = ", ".join(cmd.name for cmd in commands_list)
        await interaction.response.send_message(f"Команды: {names}", ephemeral=True)

    tag_group = app_commands.Group(name="tag", description="Теги")

    @tag_group.command(name="create", description="Создать тег")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def tag_create(self, interaction: discord.Interaction, name: str, content: str) -> None:
        async with self.bot.db.session() as session:
            tag = Tag(guild_id=interaction.guild.id, name=name, content=content)
            session.add(tag)
            await session.commit()
        await interaction.response.send_message("Тег создан.", ephemeral=True)

    @tag_group.command(name="delete", description="Удалить тег")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def tag_delete(self, interaction: discord.Interaction, name: str) -> None:
        async with self.bot.db.session() as session:
            result = await session.execute(
                select(Tag).where((Tag.guild_id == interaction.guild.id) & (Tag.name == name))
            )
            tag = result.scalars().first()
            if tag:
                await session.delete(tag)
                await session.commit()
        await interaction.response.send_message("Тег удален.", ephemeral=True)

    @tag_group.command(name="list", description="Список тегов")
    async def tag_list(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            result = await session.execute(select(Tag).where(Tag.guild_id == interaction.guild.id))
            tags = result.scalars().all()
        if not tags:
            await interaction.response.send_message("Теги не найдены.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Теги: " + ", ".join(tag.name for tag in tags), ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if not message.content.startswith("!"):
            return
        command_name = message.content[1:].split()[0]
        async with self.bot.db.session() as session:
            result = await session.execute(
                select(CustomCommand).where(
                    (CustomCommand.guild_id == message.guild.id)
                    & (CustomCommand.name == command_name)
                )
            )
            cc = result.scalars().first()
        if cc:
            await message.channel.send(cc.response)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
