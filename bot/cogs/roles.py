from __future__ import annotations

import json

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.cogs.utils import get_or_create_guild, parse_settings
from bot.database.models import ReactionRole


class RolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _update_setting(self, guild: discord.Guild, key: str, value) -> None:
        async with self.bot.db.session() as session:
            config = await get_or_create_guild(session, guild.id, "Coins")
            settings = parse_settings(config.settings)
            settings[key] = value
            config.settings = json.dumps(settings, ensure_ascii=False)
            await session.commit()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        async with self.bot.db.session() as session:
            config = await get_or_create_guild(session, member.guild.id, "Coins")
            settings = parse_settings(config.settings)
        welcome_channel_id = settings.get("welcome_channel_id")
        welcome_message = settings.get("welcome_message")
        autorole_id = settings.get("autorole_id")
        if welcome_channel_id and welcome_message:
            channel = member.guild.get_channel(welcome_channel_id)
            if channel:
                await channel.send(welcome_message.replace("{member}", member.mention))
        if autorole_id:
            role = member.guild.get_role(autorole_id)
            if role:
                await member.add_roles(role, reason="Autorole")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        async with self.bot.db.session() as session:
            config = await get_or_create_guild(session, member.guild.id, "Coins")
            settings = parse_settings(config.settings)
        goodbye_channel_id = settings.get("goodbye_channel_id")
        goodbye_message = settings.get("goodbye_message")
        if goodbye_channel_id and goodbye_message:
            channel = member.guild.get_channel(goodbye_channel_id)
            if channel:
                await channel.send(goodbye_message.replace("{member}", member.name))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or payload.member.bot:
            return
        async with self.bot.db.session() as session:
            config = await get_or_create_guild(session, payload.guild_id, "Coins")
            settings = parse_settings(config.settings)
            result = await session.execute(
                select(ReactionRole).where(
                    (ReactionRole.guild_id == payload.guild_id)
                    & (ReactionRole.message_id == payload.message_id)
                    & (ReactionRole.emoji == str(payload.emoji))
                )
            )
            reaction_role = result.scalars().first()
        if reaction_role:
            guild = self.bot.get_guild(payload.guild_id)
            role = guild.get_role(reaction_role.role_id) if guild else None
            member = guild.get_member(payload.user_id) if guild else None
            if role and member:
                await member.add_roles(role, reason="Reaction role")
        verify_channel_id = settings.get("verify_channel_id")
        verify_role_id = settings.get("verify_role_id")
        if (
            verify_channel_id
            and verify_role_id
            and payload.channel_id == verify_channel_id
            and str(payload.emoji) == "✅"
        ):
            guild = self.bot.get_guild(payload.guild_id)
            member = guild.get_member(payload.user_id) if guild else None
            role = guild.get_role(verify_role_id) if guild else None
            if member and role:
                await member.add_roles(role, reason="Verification")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None:
            return
        async with self.bot.db.session() as session:
            result = await session.execute(
                select(ReactionRole).where(
                    (ReactionRole.guild_id == payload.guild_id)
                    & (ReactionRole.message_id == payload.message_id)
                    & (ReactionRole.emoji == str(payload.emoji))
                )
            )
            reaction_role = result.scalars().first()
        if reaction_role:
            guild = self.bot.get_guild(payload.guild_id)
            role = guild.get_role(reaction_role.role_id) if guild else None
            member = guild.get_member(payload.user_id) if guild else None
            if role and member:
                await member.remove_roles(role, reason="Reaction role")

    welcome_group = app_commands.Group(name="welcome", description="Приветствие")

    @welcome_group.command(name="set", description="Установить приветствие")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_set(
        self, interaction: discord.Interaction, channel: discord.TextChannel, message: str
    ) -> None:
        await self._update_setting(interaction.guild, "welcome_channel_id", channel.id)
        await self._update_setting(interaction.guild, "welcome_message", message)
        await interaction.response.send_message("Приветствие установлено.", ephemeral=True)

    @welcome_group.command(name="disable", description="Выключить приветствие")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_disable(self, interaction: discord.Interaction) -> None:
        await self._update_setting(interaction.guild, "welcome_channel_id", None)
        await self._update_setting(interaction.guild, "welcome_message", None)
        await interaction.response.send_message("Приветствие отключено.", ephemeral=True)

    goodbye_group = app_commands.Group(name="goodbye", description="Прощание")

    @goodbye_group.command(name="set", description="Установить прощание")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_set(
        self, interaction: discord.Interaction, channel: discord.TextChannel, message: str
    ) -> None:
        await self._update_setting(interaction.guild, "goodbye_channel_id", channel.id)
        await self._update_setting(interaction.guild, "goodbye_message", message)
        await interaction.response.send_message("Прощание установлено.", ephemeral=True)

    autorole_group = app_commands.Group(name="autorole", description="Автовыдача роли")

    @autorole_group.command(name="set", description="Установить автроль")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autorole_set(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await self._update_setting(interaction.guild, "autorole_id", role.id)
        await interaction.response.send_message("Автроль установлена.", ephemeral=True)

    role_group = app_commands.Group(name="role", description="Управление ролями")

    @role_group.command(name="add", description="Добавить роль участнику")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role) -> None:
        await member.add_roles(role, reason="Role manage")
        await interaction.response.send_message("Роль добавлена.", ephemeral=True)

    @role_group.command(name="remove", description="Снять роль участнику")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_remove(
        self, interaction: discord.Interaction, member: discord.Member, role: discord.Role
    ) -> None:
        await member.remove_roles(role, reason="Role manage")
        await interaction.response.send_message("Роль снята.", ephemeral=True)

    reactionrole_group = app_commands.Group(name="reactionrole", description="Реакционные роли")

    @reactionrole_group.command(name="create", description="Создать реакционную роль")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def reactionrole_create(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message_id: int,
        emoji: str,
        role: discord.Role,
    ) -> None:
        async with self.bot.db.session() as session:
            rr = ReactionRole(
                guild_id=interaction.guild.id,
                channel_id=channel.id,
                message_id=message_id,
                emoji=emoji,
                role_id=role.id,
            )
            session.add(rr)
            await session.commit()
        await interaction.response.send_message("Реакционная роль создана.", ephemeral=True)

    @reactionrole_group.command(name="delete", description="Удалить реакционную роль")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def reactionrole_delete(
        self, interaction: discord.Interaction, message_id: int, emoji: str
    ) -> None:
        async with self.bot.db.session() as session:
            result = await session.execute(
                select(ReactionRole).where(
                    (ReactionRole.guild_id == interaction.guild.id)
                    & (ReactionRole.message_id == message_id)
                    & (ReactionRole.emoji == emoji)
                )
            )
            rr = result.scalars().first()
            if rr:
                await session.delete(rr)
                await session.commit()
        await interaction.response.send_message("Реакционная роль удалена.", ephemeral=True)

    verify_group = app_commands.Group(name="verify", description="Верификация")

    @verify_group.command(name="setup", description="Настроить верификацию")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_setup(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        role = discord.utils.get(interaction.guild.roles, name="Verified")
        if role is None:
            role = await interaction.guild.create_role(name="Verified")
        await self._update_setting(interaction.guild, "verify_role_id", role.id)
        await self._update_setting(interaction.guild, "verify_channel_id", channel.id)
        await channel.send("Нажмите ✅ чтобы получить роль Verified.")
        await interaction.response.send_message("Верификация настроена.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RolesCog(bot))
