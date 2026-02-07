from __future__ import annotations

import datetime as dt
import json
from typing import Any, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.database.models import GuildConfig, UserProfile


ROLE_MULTIPLIERS = {
    "VIP": 1.25,
    "Premium": 1.5,
    "Newbie": 0.8,
    "Muted": 0.0,
}


def xp_to_next(level: int) -> int:
    return int(100 * (level**1.5))


def base_reward(level: int) -> int:
    return level * 10


def get_role_multiplier(member: discord.Member) -> float:
    multiplier = 1.0
    for role in member.roles:
        if role.name in ROLE_MULTIPLIERS:
            multiplier = max(multiplier, ROLE_MULTIPLIERS[role.name])
    if any(role.name == "Muted" for role in member.roles):
        return 0.0
    return multiplier


def parse_settings(settings_raw: str) -> Dict[str, Any]:
    try:
        return json.loads(settings_raw or "{}")
    except json.JSONDecodeError:
        return {}


def dump_settings(settings: Dict[str, Any]) -> str:
    return json.dumps(settings, ensure_ascii=False)


async def get_or_create_guild(session, guild_id: int, currency_name: str) -> GuildConfig:
    guild = await session.get(GuildConfig, guild_id)
    if guild is None:
        guild = GuildConfig(guild_id=guild_id, currency_name=currency_name)
        session.add(guild)
        await session.commit()
    return guild


async def get_or_create_user(session, guild_id: int, user_id: int) -> UserProfile:
    result = await session.execute(
        UserProfile.__table__.select().where(
            (UserProfile.guild_id == guild_id) & (UserProfile.user_id == user_id)
        )
    )
    row = result.first()
    if row is None:
        user = UserProfile(user_id=user_id, guild_id=guild_id)
        session.add(user)
        await session.commit()
        return user
    return await session.get(UserProfile, row.id)


class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Список команд бота")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="AniBot — помощь",
            description="Полный список команд доступен по категориям в README.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Базовые", value="/help /ping /about /settings", inline=False)
        embed.add_field(name="Модерация", value="/warn /mute /kick /ban /purge и др.", inline=False)
        embed.add_field(name="Экономика", value="/balance /daily /transfer /economy", inline=False)
        embed.add_field(name="Левелинг", value="/rank /leaderboard /level", inline=False)
        embed.add_field(name="Магазин", value="/shop", inline=False)
        embed.add_field(name="Гемблинг", value="/coinflip /dice /roulette", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ping", description="Проверка задержки")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"🏓 Pong! {int(self.bot.latency * 1000)}ms", ephemeral=True
        )

    @app_commands.command(name="about", description="О боте")
    async def about(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "AniBot — модульный Discord-бот с экономикой, модерацией и левелингом.",
            ephemeral=True,
        )

    @app_commands.command(name="settings", description="Показать настройки сервера")
    async def settings(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            settings = parse_settings(guild.settings)
        embed = discord.Embed(title="Настройки сервера", color=discord.Color.green())
        embed.add_field(name="Курс валюты", value=str(guild.server_rate), inline=False)
        embed.add_field(name="Валюта", value=guild.currency_name, inline=False)
        embed.add_field(
            name="Левелинг",
            value="Включен" if settings.get("leveling_enabled", True) else "Выключен",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="announce", description="Отправить объявление")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def announce(self, interaction: discord.Interaction, message: str) -> None:
        await interaction.channel.send(f"📢 {message}")
        await interaction.response.send_message("Объявление отправлено.", ephemeral=True)

    @app_commands.command(name="poll", description="Создать опрос")
    async def poll(self, interaction: discord.Interaction, question: str) -> None:
        embed = discord.Embed(title="Опрос", description=question, color=discord.Color.orange())
        msg = await interaction.channel.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")
        await interaction.response.send_message("Опрос создан.", ephemeral=True)

    @app_commands.command(name="topic", description="Установить тему канала")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def topic_set(self, interaction: discord.Interaction, topic: str) -> None:
        await interaction.channel.edit(topic=topic)
        await interaction.response.send_message("Тема канала обновлена.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
