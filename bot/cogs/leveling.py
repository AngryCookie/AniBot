from __future__ import annotations

import datetime as dt
import json
import random
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from bot.cogs.utils import (
    base_reward,
    get_or_create_guild,
    get_or_create_level_settings,
    get_role_multiplier,
    merge_leveling_settings,
    parse_settings,
    xp_to_next,
)
from bot.database.models import ActivityEvent, LevelReward, UserProfile
from bot.database.operations import apply_balance_change, get_or_create_user_locked


def is_on_cooldown(last_ts: dt.datetime | None, now: dt.datetime, cooldown_seconds: int) -> bool:
    if last_ts is None:
        return False
    return (now - last_ts).total_seconds() < max(0, cooldown_seconds)


def merge_voice_session_minutes(last_join_ts: dt.datetime | None, now: dt.datetime) -> int:
    if last_join_ts is None:
        return 0
    return max(0, int((now - last_join_ts).total_seconds() // 60))


class LevelingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.voice_xp_task.start()

    def cog_unload(self) -> None:
        self.voice_xp_task.cancel()

    async def _resolve_leveling_config(self, session, guild_id: int) -> dict[str, Any]:
        legacy = await get_or_create_level_settings(session, guild_id)
        guild_cfg = await get_or_create_guild(session, guild_id, "Coins")
        parsed = parse_settings(guild_cfg.settings)
        merged = merge_leveling_settings(parsed.get("leveling") if isinstance(parsed, dict) else None)

        msg_cfg = merged["message_xp"]
        if "cooldown_seconds" not in msg_cfg:
            msg_cfg["cooldown_seconds"] = int(legacy.cooldown_seconds)
        if "min_length" not in msg_cfg:
            msg_cfg["min_length"] = int(legacy.min_message_length)
        if "ignore_channels" not in msg_cfg:
            msg_cfg["ignore_channels"] = []

        merged["enabled"] = bool(merged.get("enabled", legacy.enabled))
        merged["max_xp_per_day"] = int(merged.get("max_xp_per_day", legacy.max_xp_per_day))
        merged["role_rewards"]["enabled"] = bool(merged["role_rewards"].get("enabled", legacy.rewards_roles))
        return merged

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        async with self.bot.db.session() as session:
            async with session.begin():
                guild = await get_or_create_guild(session, message.guild.id, "Coins")
                config = await self._resolve_leveling_config(session, message.guild.id)
                if not config.get("enabled", True):
                    return

                msg_cfg = config.get("message_xp", {})
                if not msg_cfg.get("enabled", True):
                    return
                if msg_cfg.get("ignore_commands", True) and message.content.startswith(("!", "/")):
                    return
                content = message.content.strip()
                if len(content) < int(msg_cfg.get("min_length", 6)):
                    return

                ignored_channels = {int(c) for c in msg_cfg.get("ignore_channels", [])}
                if message.channel.id in ignored_channels:
                    return

                user = await get_or_create_user_locked(session, message.guild.id, message.author.id)
                now = dt.datetime.utcnow()
                cooldown = int(msg_cfg.get("cooldown_seconds", 45))
                if is_on_cooldown(user.last_message_ts, now, cooldown):
                    return
                if user.last_message_content and user.last_message_content == content:
                    return
                if user.last_xp_date and user.last_xp_date.date() != now.date():
                    user.daily_xp = 0
                if user.daily_xp >= int(config.get("max_xp_per_day", 500)):
                    return

                xp_min = int(msg_cfg.get("xp_min", 5))
                xp_max = int(msg_cfg.get("xp_max", max(xp_min, 10)))
                gained = random.randint(min(xp_min, xp_max), max(xp_min, xp_max))

                user.xp += gained
                user.daily_xp += gained
                user.last_xp_date = now
                user.last_message_ts = now
                user.last_message_content = content
                session.add(
                    ActivityEvent(
                        guild_id=message.guild.id,
                        user_id=message.author.id,
                        event_type="message",
                        value=1,
                        metadata_json={"xp": gained},
                    )
                )
                await self._process_level_up(session, message.author, guild, user, config)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if member.bot or not member.guild:
            return

        async with self.bot.db.session() as session:
            async with session.begin():
                config = await self._resolve_leveling_config(session, member.guild.id)
                if not config.get("enabled", True):
                    return
                voice_cfg = config.get("voice_xp", {})
                if not voice_cfg.get("enabled", True):
                    return

                user = await get_or_create_user_locked(session, member.guild.id, member.id)
                now = dt.datetime.utcnow()
                if after.channel and not before.channel:
                    user.voice_join_ts = now
                    return

                if before.channel and after.channel and before.channel.id != after.channel.id:
                    user.voice_join_ts = now
                    return

                if before.channel and not after.channel:
                    if user.voice_join_ts is None:
                        return
                    elapsed_minutes = merge_voice_session_minutes(user.voice_join_ts, now)
                    if elapsed_minutes > 0:
                        session.add(
                            ActivityEvent(
                                guild_id=member.guild.id,
                                user_id=member.id,
                                event_type="voice_minutes",
                                value=elapsed_minutes,
                            )
                        )
                    user.voice_join_ts = None

    @tasks.loop(minutes=1)
    async def voice_xp_task(self) -> None:
        now = dt.datetime.utcnow()
        for guild in self.bot.guilds:
            async with self.bot.db.session() as session:
                async with session.begin():
                    guild_config = await get_or_create_guild(session, guild.id, "Coins")
                    config = await self._resolve_leveling_config(session, guild.id)
                    if not config.get("enabled", True):
                        continue
                    voice_cfg = config.get("voice_xp", {})
                    if not voice_cfg.get("enabled", True):
                        continue

                    ignored_channels = {int(c) for c in voice_cfg.get("ignore_channels", [])}
                    xp_per_minute = max(0, int(voice_cfg.get("xp_per_minute", 1)))
                    if xp_per_minute == 0:
                        continue

                    for member in guild.members:
                        if member.bot or not member.voice or not member.voice.channel:
                            continue
                        if member.voice.channel.id in ignored_channels:
                            continue
                        if voice_cfg.get("ignore_self_deaf", True) and member.voice.self_deaf:
                            continue
                        if voice_cfg.get("ignore_self_mute", False) and member.voice.self_mute:
                            continue
                        if member.voice.afk:
                            continue
                        if voice_cfg.get("require_multiple_users", True) and len(member.voice.channel.members) <= 1:
                            continue

                        user = await get_or_create_user_locked(session, guild.id, member.id)
                        if user.voice_join_ts is None:
                            user.voice_join_ts = now
                            continue

                        elapsed_minutes = merge_voice_session_minutes(user.voice_join_ts, now)
                        if elapsed_minutes < 1:
                            continue

                        if user.last_xp_date and user.last_xp_date.date() != now.date():
                            user.daily_xp = 0
                        max_daily = int(config.get("max_xp_per_day", 500))
                        if user.daily_xp >= max_daily:
                            user.voice_join_ts = now
                            continue

                        grant_minutes = max(0, elapsed_minutes)
                        gain = grant_minutes * xp_per_minute
                        if user.daily_xp + gain > max_daily:
                            gain = max(0, max_daily - user.daily_xp)
                            grant_minutes = gain // xp_per_minute if xp_per_minute else 0
                        user.voice_join_ts = now
                        if gain <= 0:
                            continue

                        user.xp += gain
                        user.daily_xp += gain
                        user.last_xp_date = now
                        session.add(
                            ActivityEvent(
                                guild_id=guild.id,
                                user_id=member.id,
                                event_type="voice_minutes",
                                value=grant_minutes,
                                metadata_json={"xp": gain},
                            )
                        )
                        await self._process_level_up(session, member, guild_config, user, config)

    @voice_xp_task.before_loop
    async def before_voice_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _process_level_up(self, session, member: discord.Member, guild, user, config: dict[str, Any]) -> None:
        curve = config.get("level_curve", {})
        levels_before = user.level
        while user.xp >= xp_to_next(user.level, curve):
            user.xp -= xp_to_next(user.level, curve)
            user.level += 1

        if user.level == levels_before:
            return

        reward = base_reward(user.level)
        multiplier = get_role_multiplier(member)
        final_reward = int(reward * multiplier * guild.server_rate)
        if final_reward > 0:
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
        role_rewards_enabled = bool((config.get("role_rewards") or {}).get("enabled", True))
        for reward_row in rewards.scalars().all():
            if reward_row.role_id and role_rewards_enabled:
                role = member.guild.get_role(reward_row.role_id)
                if role:
                    await member.add_roles(role, reason="Level reward")
            if reward_row.reward_amount:
                await apply_balance_change(
                    session,
                    guild_id=guild.guild_id,
                    user_id=member.id,
                    amount=reward_row.reward_amount,
                    ledger_type="earn",
                    source="level_reward",
                )

        if not config.get("announce_level_up", True):
            return
        now = dt.datetime.utcnow()
        announce_cooldown = int(config.get("announce_cooldown_seconds", 60))
        if user.last_level_up_announce_at and (now - user.last_level_up_announce_at).total_seconds() < announce_cooldown:
            return

        channel = None
        channel_id = config.get("level_up_channel_id")
        if channel_id:
            channel = member.guild.get_channel(int(channel_id))
            if channel and isinstance(channel, discord.abc.GuildChannel):
                perms = channel.permissions_for(member.guild.me)
                if not (perms.send_messages and perms.view_channel):
                    channel = None
        if channel is None:
            channel = member.guild.system_channel
        if channel:
            await channel.send(f"🎉 {member.mention} достиг уровня {user.level}!")
            user.last_level_up_announce_at = now

    @app_commands.command(name="rank", description="Показать ваш уровень")
    async def rank(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            user = await get_or_create_user_locked(session, interaction.guild.id, interaction.user.id)
            config = await self._resolve_leveling_config(session, interaction.guild.id)
            curve = config.get("level_curve", {})
            await session.commit()
        await interaction.response.send_message(
            f"Уровень: {user.level} | XP: {user.xp}/{xp_to_next(user.level, curve)}",
            ephemeral=True,
        )

    @app_commands.command(name="leaderboard", description="Топ уровней")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            users = await session.execute(
                select(UserProfile).where(UserProfile.guild_id == interaction.guild.id).order_by(
                    UserProfile.level.desc(), UserProfile.xp.desc(), UserProfile.updated_at.desc()
                ).limit(10)
            )
            top_users = users.scalars().all()
        members = {m.id: m for m in interaction.guild.members}
        embed = discord.Embed(title="Топ 10 уровней", color=discord.Color.gold())
        for idx, user in enumerate(top_users, start=1):
            member = members.get(user.user_id)
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
                guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
                payload = parse_settings(guild.settings)
                leveling = payload.get("leveling", {}) if isinstance(payload.get("leveling"), dict) else {}
                leveling["enabled"] = True
                payload["leveling"] = leveling
                guild.settings = json.dumps(payload, ensure_ascii=False)
        await interaction.response.send_message("Левелинг включен.", ephemeral=True)

    @level_group.command(name="disable", description="Выключить левелинг")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def level_disable(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            async with session.begin():
                settings = await get_or_create_level_settings(session, interaction.guild.id)
                settings.enabled = False
                guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
                payload = parse_settings(guild.settings)
                leveling = payload.get("leveling", {}) if isinstance(payload.get("leveling"), dict) else {}
                leveling["enabled"] = False
                payload["leveling"] = leveling
                guild.settings = json.dumps(payload, ensure_ascii=False)
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
