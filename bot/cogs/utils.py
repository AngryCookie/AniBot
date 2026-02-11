from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from sqlalchemy import select

from bot.database.models import (
    GuildConfig,
    GuildGamblingSettings,
    GuildLevelSettings,
    GuildLogSettings,
    UserProfile,
)


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
        await session.flush()
    return guild


async def get_or_create_user(session, guild_id: int, user_id: int) -> UserProfile:
    result = await session.execute(
        select(UserProfile).where(
            (UserProfile.guild_id == guild_id) & (UserProfile.user_id == user_id)
        )
    )
    user = result.scalars().first()
    if user is None:
        user = UserProfile(user_id=user_id, guild_id=guild_id)
        session.add(user)
        await session.flush()
    return user


async def get_or_create_level_settings(session, guild_id: int) -> GuildLevelSettings:
    settings = await session.get(GuildLevelSettings, guild_id)
    if settings is None:
        settings = GuildLevelSettings(guild_id=guild_id)
        session.add(settings)
        await session.flush()
    return settings


async def get_or_create_gambling_settings(session, guild_id: int) -> GuildGamblingSettings:
    settings = await session.get(GuildGamblingSettings, guild_id)
    if settings is None:
        settings = GuildGamblingSettings(guild_id=guild_id)
        session.add(settings)
        await session.flush()
    return settings


async def get_or_create_log_settings(session, guild_id: int) -> GuildLogSettings:
    settings = await session.get(GuildLogSettings, guild_id)
    if settings is None:
        settings = GuildLogSettings(guild_id=guild_id)
        session.add(settings)
        await session.flush()
    return settings


class HelpView(discord.ui.View):
    def __init__(self, cog: "UtilityCog", *, admin: bool, web_url: str | None = None):
        super().__init__(timeout=60)
        self.cog = cog
        self.admin = admin
        self.web_url = web_url
        if admin and web_url:
            self.add_item(discord.ui.Button(label="Открыть панель", style=discord.ButtonStyle.link, url=web_url))

    async def _send_section(self, interaction: discord.Interaction, section: str) -> None:
        await self.cog._send_help_section(interaction, section, as_followup=True)

    @discord.ui.button(label="Модерация", style=discord.ButtonStyle.secondary)
    async def moderation(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        embed = discord.Embed(title="🛡️ Модерация", description="/warn /mute /kick /ban /purge", color=discord.Color.orange())
        embed.set_footer(text="Срок действия кнопок: 60с")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Экономика", style=discord.ButtonStyle.secondary)
    async def economy(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._send_section(interaction, "economy")

    @discord.ui.button(label="PvP", style=discord.ButtonStyle.secondary)
    async def pvp(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._send_section(interaction, "pvp")

    @discord.ui.button(label="Ставки", style=discord.ButtonStyle.secondary)
    async def bets(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._send_section(interaction, "bets")


class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Список команд бота")
    async def help_command(self, interaction: discord.Interaction, section: str | None = None) -> None:
        section = (section or "").lower().strip()
        if section in {"economy", "pvp", "bets", "shop", "leveling"}:
            await self._send_help_section(interaction, section)
            return
        is_admin = isinstance(interaction.user, discord.Member) and (
            interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.moderate_members
        )
        embed = discord.Embed(
            title="📘 AniBot — помощь",
            description="Выберите раздел кнопками ниже или используйте `/help <раздел>`.",
            color=discord.Color.blurple(),
        )
        if is_admin:
            web_url = os.getenv("WEB_BASE_URL", "https://example.com/admin")
            embed.add_field(name="🛡️ Админ-команды", value="/warn /mute /kick /ban /purge /settings", inline=False)
            embed.add_field(name="⚙️ Системные", value="/help /ping /about /announce /topic", inline=False)
            embed.add_field(name="🌐 Веб-панель", value=web_url, inline=False)
            view = HelpView(self, admin=True, web_url=web_url)
            embed.set_footer(text="Срок действия кнопок: 60с")
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return
        embed.add_field(name="👤 Пользователь", value="/balance /daily /transfer /shop /bets /pvp /rank", inline=False)
        embed.add_field(name="💡 Быстрые действия", value="Получить daily, проверить магазин, поставить ставку, дуэль PvP", inline=False)
        embed.set_footer(text="Срок действия кнопок: 60с")
        view = HelpView(self, admin=False)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _send_help_section(self, interaction: discord.Interaction, section: str, as_followup: bool = False) -> None:
        mapping = {
            "economy": ("💰 Экономика", "/balance /daily /transfer", "Начните с /balance, затем /daily и /shop list."),
            "pvp": ("⚔️ PvP", "/pvp /pvp-top /pvp-stats /pvp_season", "Вызовите игрока через /pvp и дождитесь подтверждения."),
            "bets": ("🎯 Ставки", "/bets /bet", "Выберите матч, команду и подтвердите ставку."),
            "shop": ("🛒 Магазин", "/shop list /shop info /shop buy", "Используйте кнопки в /shop list для покупки."),
            "leveling": ("📈 Левелинг", "/rank /leaderboard /level", "Общайтесь в чате, чтобы получать опыт."),
        }
        title, cmds, hint = mapping[section]
        embed = discord.Embed(title=title, color=discord.Color.blurple())
        embed.add_field(name="Команды", value=cmds, inline=False)
        embed.add_field(name="Что дальше", value=hint, inline=False)
        embed.set_footer(text="Срок действия кнопок: 60с")
        if as_followup:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
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
