from __future__ import annotations

import datetime as dt
import json
import random

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from bot.cogs.utils import base_reward, get_or_create_guild, get_or_create_user, get_role_multiplier, parse_settings, xp_to_next
from bot.database.models import LevelReward, UserProfile


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
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, message.guild.id, "Coins")
            settings = parse_settings(guild.settings)
            if not settings.get("leveling_enabled", True):
                return
            user = await get_or_create_user(session, message.guild.id, message.author.id)
            now = dt.datetime.utcnow()
            if user.last_message_ts and (now - user.last_message_ts).total_seconds() < 60:
                return
            gained = random.randint(5, 10)
            user.xp += gained
            user.last_message_ts = now
            await self._process_level_up(session, message.author, guild, user)
            await session.commit()

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

    @tasks.loop(minutes=1)
    async def voice_xp_task(self) -> None:
        for guild in self.bot.guilds:
            async with self.bot.db.session() as session:
                guild_config = await get_or_create_guild(session, guild.id, "Coins")
                settings = parse_settings(guild_config.settings)
                if not settings.get("leveling_enabled", True):
                    continue
                for member in guild.members:
                    if member.bot:
                        continue
                    if member.voice and member.voice.channel:
                        user = await get_or_create_user(session, guild.id, member.id)
                        user.xp += 2
                        await self._process_level_up(session, member, guild_config, user)
                await session.commit()

    @voice_xp_task.before_loop
    async def before_voice_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _process_level_up(self, session, member: discord.Member, guild, user) -> None:
        leveled_up = False
        while user.xp >= xp_to_next(user.level):
            user.xp -= xp_to_next(user.level)
            user.level += 1
            leveled_up = True
            reward = base_reward(user.level)
            multiplier = get_role_multiplier(member)
            final_reward = int(reward * multiplier * guild.server_rate)
            user.balance += final_reward
            rewards = await session.execute(
                select(LevelReward).where(
                    (LevelReward.guild_id == guild.guild_id)
                    & (LevelReward.level == user.level)
                )
            )
            for reward_row in rewards.scalars().all():
                if reward_row.role_id:
                    role = member.guild.get_role(reward_row.role_id)
                    if role:
                        await member.add_roles(role, reason="Level reward")
                if reward_row.reward_amount:
                    user.balance += reward_row.reward_amount
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
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            settings = parse_settings(guild.settings)
            settings["leveling_enabled"] = True
            guild.settings = json.dumps(settings)
            await session.commit()
        await interaction.response.send_message("Левелинг включен.", ephemeral=True)

    @level_group.command(name="disable", description="Выключить левелинг")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def level_disable(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            settings = parse_settings(guild.settings)
            settings["leveling_enabled"] = False
            guild.settings = json.dumps(settings)
            await session.commit()
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
