from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.cogs.utils import get_or_create_guild, get_or_create_user
from bot.database.models import ModLog, Warning


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _log_action(
        self,
        guild_id: int,
        action: str,
        moderator_id: int,
        user_id: int | None = None,
        reason: str = "",
    ) -> None:
        async with self.bot.db.session() as session:
            log = ModLog(
                guild_id=guild_id,
                action=action,
                moderator_id=moderator_id,
                user_id=user_id,
                reason=reason,
            )
            session.add(log)
            await session.commit()

    @app_commands.command(name="warn", description="Выдать предупреждение")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        async with self.bot.db.session() as session:
            warn = Warning(
                guild_id=interaction.guild.id,
                user_id=member.id,
                moderator_id=interaction.user.id,
                reason=reason,
            )
            session.add(warn)
            await session.commit()
        await self._log_action(interaction.guild.id, "warn", interaction.user.id, member.id, reason)
        await interaction.response.send_message(
            f"Предупреждение выдано {member.mention}.", ephemeral=True
        )

    @app_commands.command(name="warnings", description="Посмотреть предупреждения")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        async with self.bot.db.session() as session:
            warnings = await session.execute(
                select(Warning).where(
                    (Warning.guild_id == interaction.guild.id) & (Warning.user_id == member.id)
                )
            )
            warnings = warnings.scalars().all()
        if not warnings:
            await interaction.response.send_message("Предупреждений нет.", ephemeral=True)
            return
        description = "\n".join(
            [f"#{w.id} {w.reason} ({w.created_at.date()})" for w in warnings]
        )
        embed = discord.Embed(
            title=f"Предупреждения {member.display_name}", description=description
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarns", description="Очистить предупреждения")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member) -> None:
        async with self.bot.db.session() as session:
            warnings = await session.execute(
                select(Warning).where(
                    (Warning.guild_id == interaction.guild.id) & (Warning.user_id == member.id)
                )
            )
            count = 0
            for warn in warnings.scalars().all():
                await session.delete(warn)
                count += 1
            await session.commit()
        await self._log_action(interaction.guild.id, "clearwarns", interaction.user.id, member.id)
        await interaction.response.send_message(
            f"Удалено предупреждений: {count}", ephemeral=True
        )

    @app_commands.command(name="mute", description="Замьютить пользователя")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute(self, interaction: discord.Interaction, member: discord.Member, reason: str = "") -> None:
        muted_role = discord.utils.get(interaction.guild.roles, name="Muted")
        if muted_role is None:
            muted_role = await interaction.guild.create_role(name="Muted")
            for channel in interaction.guild.channels:
                await channel.set_permissions(muted_role, send_messages=False, speak=False)
        await member.add_roles(muted_role, reason=reason or "Muted")
        await self._log_action(interaction.guild.id, "mute", interaction.user.id, member.id, reason)
        await interaction.response.send_message("Пользователь замьючен.", ephemeral=True)

    @app_commands.command(name="unmute", description="Размьютить пользователя")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member) -> None:
        muted_role = discord.utils.get(interaction.guild.roles, name="Muted")
        if muted_role:
            await member.remove_roles(muted_role)
        await self._log_action(interaction.guild.id, "unmute", interaction.user.id, member.id)
        await interaction.response.send_message("Пользователь размьючен.", ephemeral=True)

    @app_commands.command(name="kick", description="Кикнуть пользователя")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "") -> None:
        await member.kick(reason=reason)
        await self._log_action(interaction.guild.id, "kick", interaction.user.id, member.id, reason)
        await interaction.response.send_message("Пользователь кикнут.", ephemeral=True)

    @app_commands.command(name="ban", description="Забанить пользователя")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "") -> None:
        await member.ban(reason=reason)
        await self._log_action(interaction.guild.id, "ban", interaction.user.id, member.id, reason)
        await interaction.response.send_message("Пользователь забанен.", ephemeral=True)

    @app_commands.command(name="unban", description="Разбанить пользователя")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user: discord.User) -> None:
        await interaction.guild.unban(user)
        await self._log_action(interaction.guild.id, "unban", interaction.user.id, user.id)
        await interaction.response.send_message("Пользователь разбанен.", ephemeral=True)

    @app_commands.command(name="purge", description="Очистить сообщения")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, limit: int) -> None:
        await interaction.channel.purge(limit=limit)
        await self._log_action(interaction.guild.id, "purge", interaction.user.id)
        await interaction.response.send_message("Сообщения удалены.", ephemeral=True)

    @app_commands.command(name="slowmode", description="Установить слоумод")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: int) -> None:
        await interaction.channel.edit(slowmode_delay=seconds)
        await self._log_action(interaction.guild.id, "slowmode", interaction.user.id)
        await interaction.response.send_message("Слоумод обновлен.", ephemeral=True)

    @app_commands.command(name="lock", description="Закрыть канал")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction) -> None:
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
        await self._log_action(interaction.guild.id, "lock", interaction.user.id)
        await interaction.response.send_message("Канал закрыт.", ephemeral=True)

    @app_commands.command(name="unlock", description="Открыть канал")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction) -> None:
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
        await self._log_action(interaction.guild.id, "unlock", interaction.user.id)
        await interaction.response.send_message("Канал открыт.", ephemeral=True)

    @app_commands.command(name="modlog", description="Показать лог модерации")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def modlog(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            logs = await session.execute(
                select(ModLog)
                .where(ModLog.guild_id == interaction.guild.id)
                .order_by(ModLog.created_at.desc())
                .limit(10)
            )
            logs = logs.scalars().all()
        if not logs:
            await interaction.response.send_message("Лог пуст.", ephemeral=True)
            return
        description = "\n".join(
            [
                f"{log.created_at.date()} {log.action} {log.user_id or ''} {log.reason}"
                for log in logs
            ]
        )
        embed = discord.Embed(title="ModLog", description=description)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
