from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.cogs.utils import get_or_create_guild
from bot.database.models import CustomCommand, ModLog, Tag
from bot.database.operations import apply_balance_change, get_or_create_user_locked


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
                await apply_balance_change(
                    session,
                    guild_id=interaction.guild.id,
                    user_id=member.id,
                    amount=amount,
                    ledger_type="admin",
                    source="admin_give",
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
                    await apply_balance_change(
                        session,
                        guild_id=interaction.guild.id,
                        user_id=member.id,
                        amount=delta,
                        ledger_type="admin",
                        source="admin_take",
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
                    await apply_balance_change(
                        session,
                        guild_id=interaction.guild.id,
                        user_id=member.id,
                        amount=-user.balance,
                        ledger_type="admin",
                        source="admin_reset",
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
