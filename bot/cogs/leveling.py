from __future__ import annotations

import datetime as dt
import json
import random

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from bot.cogs.utils import (
    base_reward,
    get_or_create_guild,
    get_or_create_level_settings,
    get_or_create_user,
    get_role_multiplier,
    xp_to_next,
)
from bot.database.models import LevelReward, UserProfile
from bot.database.operations import apply_balance_change


class LevelingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.voice_xp_task.start()

    def cog_unload(self) -> None:
        self.voice_xp_task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if message.content.startswith(("!", "/")):
            return
        async with self.bot.db.session() as session:
            async with session.begin():
                guild = await get_or_create_guild(session, message.guild.id, "Coins")
                settings = await get_or_create_level_settings(session, message.guild.id)
                if not settings.enabled:
                    return
                if len(message.content.strip()) < settings.min_message_length:
                    return
                blacklist = set(json.loads(settings.blacklisted_channels or "[]"))
                if message.channel.id in blacklist:
                    return
                user = await get_or_create_user(session, message.guild.id, message.author.id)
                now = dt.datetime.utcnow()
                if user.last_message_ts and (now - user.last_message_ts).total_seconds() < settings.cooldown_seconds:
                    return
                if user.last_message_content and user.last_message_content == message.content.strip():
                    return
                if user.last_xp_date and user.last_xp_date.date() != now.date():
                    user.daily_xp = 0
                if user.daily_xp >= settings.max_xp_per_day:
                    return
                gained = random.randint(5, 10)
                user.xp += gained
                user.daily_xp += gained
                user.last_xp_date = now
                user.last_message_ts = now
                user.last_message_content = message.content.strip()
                await self._process_level_up(session, message.author, guild, user, settings)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if not member.guild:
            return
        async with self.bot.db.session() as session:
            user = await get_or_create_user(session, member.guild.id, member.id)
            if after.channel and not before.channel:
                user.voice_join_ts = dt.datetime.utcnow()
            elif before.channel and not after.channel:
                user.voice_join_ts = None
            await session.commit()

    @tasks.loop(minutes=5)
    async def voice_xp_task(self) -> None:
        for guild in self.bot.guilds:
            async with self.bot.db.session() as session:
                async with session.begin():
                    guild_config = await get_or_create_guild(session, guild.id, "Coins")
                    settings = await get_or_create_level_settings(session, guild.id)
                    if not settings.enabled:
                        continue
                    for member in guild.members:
                        if member.bot:
                            continue
                        if not member.voice or not member.voice.channel:
                            continue
                        if member.voice.afk or member.voice.self_mute or member.voice.mute:
                            continue
                        if len(member.voice.channel.members) <= 1:
                            continue
                        user = await get_or_create_user(session, guild.id, member.id)
                        now = dt.datetime.utcnow()
                        if user.last_xp_date and user.last_xp_date.date() != now.date():
                            user.daily_xp = 0
                        if user.daily_xp >= settings.max_xp_per_day:
                            continue
                        user.xp += 2
                        user.daily_xp += 2
                        user.last_xp_date = now
                        await self._process_level_up(session, member, guild_config, user, settings)

    @voice_xp_task.before_loop
    async def before_voice_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _process_level_up(self, session, member: discord.Member, guild, user, settings) -> None:
        leveled_up = False
        while user.xp >= xp_to_next(user.level):
            user.xp -= xp_to_next(user.level)
            user.level += 1
            leveled_up = True
            if settings.rewards_currency:
                reward = base_reward(user.level)
                multiplier = get_role_multiplier(member)
                final_reward = int(reward * multiplier * guild.server_rate)
                await apply_balance_change(
                    session,
                    guild_id=guild.guild_id,
                    user_id=member.id,
                    amount=final_reward,
                    ledger_type="earn",
                    source="level_up",
                )
            rewards = await session.execute(
                select(LevelReward).where(
                    (LevelReward.guild_id == guild.guild_id)
                    & (LevelReward.level == user.level)
                )
            )
            for reward_row in rewards.scalars().all():
                if reward_row.role_id and settings.rewards_roles:
                    role = member.guild.get_role(reward_row.role_id)
                    if role:
                        await member.add_roles(role, reason="Level reward")
                if reward_row.reward_amount and settings.rewards_currency:
                    await apply_balance_change(
                        session,
                        guild_id=guild.guild_id,
                        user_id=member.id,
                        amount=reward_row.reward_amount,
                        ledger_type="earn",
                        source="level_reward",
                    )
        if leveled_up:
            channel = member.guild.system_channel
            if channel:
                await channel.send(f"🎉 {member.mention} достиг уровня {user.level}!")

    @app_commands.command(name="rank", description="Показать ваш уровень")
    async def rank(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            user = await get_or_create_user(session, interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(
            f"Уровень: {user.level} | XP: {user.xp}/{xp_to_next(user.level)}",
            ephemeral=True,
        )

    @app_commands.command(name="leaderboard", description="Топ уровней")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            users = await session.execute(
                select(
                    UserProfile
                ).where(UserProfile.guild_id == interaction.guild.id).order_by(
                    UserProfile.level.desc(), UserProfile.xp.desc()
                ).limit(10)
            )
            top_users = users.scalars().all()
        embed = discord.Embed(title="Топ 10 уровней", color=discord.Color.gold())
        for idx, user in enumerate(top_users, start=1):
            member = interaction.guild.get_member(user.user_id)
            name = member.display_name if member else f"User {user.user_id}"
            embed.add_field(name=f"#{idx} {name}", value=f"Lvl {user.level} XP {user.xp}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    level_group = app_commands.Group(name="level", description="Настройки левелинга")

    @level_group.command(name="enable", description="Включить левелинг")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def level_enable(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            async with session.begin():
                settings = await get_or_create_level_settings(session, interaction.guild.id)
                settings.enabled = True
        await interaction.response.send_message("Левелинг включен.", ephemeral=True)

    @level_group.command(name="disable", description="Выключить левелинг")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def level_disable(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            async with session.begin():
                settings = await get_or_create_level_settings(session, interaction.guild.id)
                settings.enabled = False
        await interaction.response.send_message("Левелинг выключен.", ephemeral=True)

    rewards_group = app_commands.Group(name="rewards", parent=level_group, description="Награды")

    @rewards_group.command(name="add", description="Добавить награду за уровень")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reward_add(
        self,
        interaction: discord.Interaction,
        level: int,
        role: discord.Role | None = None,
        reward_amount: int = 0,
    ) -> None:
        async with self.bot.db.session() as session:
            reward = LevelReward(
                guild_id=interaction.guild.id,
                level=level,
                role_id=role.id if role else None,
                reward_amount=reward_amount,
            )
            session.add(reward)
            await session.commit()
        await interaction.response.send_message("Награда добавлена.", ephemeral=True)

    @rewards_group.command(name="remove", description="Удалить награду")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reward_remove(self, interaction: discord.Interaction, level: int) -> None:
        async with self.bot.db.session() as session:
            rewards = await session.execute(
                select(LevelReward).where(
                    (LevelReward.guild_id == interaction.guild.id)
                    & (LevelReward.level == level)
                )
            )
            removed = 0
            for reward in rewards.scalars().all():
                await session.delete(reward)
                removed += 1
            await session.commit()
        await interaction.response.send_message(
            f"Удалено наград: {removed}", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LevelingCog(bot))
