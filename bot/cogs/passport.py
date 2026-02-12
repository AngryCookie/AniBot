from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import case, func, select

from bot.cogs.utils import parse_settings
from bot.database.models import ActivityEvent, EconomyTransaction, GuildConfig, PvpStats, UserProfile
from bot.ui import EmbedFactory, reply_error

_CACHE_TTL_SECONDS = 300


@dataclass
class PassportData:
    guild_id: int
    user_id: int
    username: str
    avatar_url: str | None
    level: int | None
    xp: int | None
    balance: int | None
    pvp_rating: int | None
    pvp_wins: int | None
    pvp_losses: int | None
    pvp_streak: int | None
    betting_volume: int | None
    betting_profit: int | None
    betting_best_win: int | None
    betting_total_bets: int | None
    messages: int | None
    voice_minutes: int | None


class PassportView(discord.ui.View):
    def __init__(self, *, cog: "PassportCog", author_id: int, data: PassportData) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.author_id = author_id
        self.data = data
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Навигация доступна только автору команды.\n💡 Используйте `/passport` от своего аккаунта.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def _show(self, interaction: discord.Interaction, section: str) -> None:
        for child in self.children:
            child.disabled = False
        embed = self.cog.build_embed(section, self.data)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🏠 Обзор", style=discord.ButtonStyle.primary)
    async def overview(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show(interaction, "overview")

    @discord.ui.button(label="💰 Экономика", style=discord.ButtonStyle.secondary)
    async def economy(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show(interaction, "economy")

    @discord.ui.button(label="⚔ PvP", style=discord.ButtonStyle.secondary)
    async def pvp(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show(interaction, "pvp")

    @discord.ui.button(label="🎲 Ставки", style=discord.ButtonStyle.secondary)
    async def bets(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show(interaction, "bets")

    @discord.ui.button(label="💬 Активность", style=discord.ButtonStyle.secondary)
    async def activity(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show(interaction, "activity")


class PassportCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._cache: dict[tuple[int, int], tuple[dt.datetime, PassportData]] = {}

    def _get_cached(self, guild_id: int, user_id: int) -> PassportData | None:
        entry = self._cache.get((guild_id, user_id))
        if not entry:
            return None
        saved_at, data = entry
        if (dt.datetime.utcnow() - saved_at).total_seconds() > _CACHE_TTL_SECONDS:
            self._cache.pop((guild_id, user_id), None)
            return None
        return data

    def _put_cache(self, data: PassportData) -> None:
        self._cache[(data.guild_id, data.user_id)] = (dt.datetime.utcnow(), data)

    def _build_footer(self, embed: discord.Embed) -> None:
        embed.set_footer(text="⏳ Кнопки активны 60с • AniBot")

    def _format_main_balance(self, data: PassportData) -> str:
        return "Нет данных" if data.balance is None else f"**{data.balance}**"

    def build_embed(self, section: str, data: PassportData) -> discord.Embed:
        embed = EmbedFactory.info("🎮 Профиль игрока", f"Паспорт участника: **{data.username}**")
        if data.avatar_url:
            embed.set_thumbnail(url=data.avatar_url)

        if section == "overview":
            EmbedFactory.add_kv(embed, "👤 Пользователь", data.username)
            if data.level is not None and data.xp is not None:
                EmbedFactory.add_kv(embed, "📈 Прогресс", f"Уровень {data.level} • XP {data.xp}")
            EmbedFactory.add_kv(embed, "💰 Экономика", self._format_main_balance(data))
            if data.pvp_rating is not None:
                EmbedFactory.add_kv(
                    embed,
                    "⚔ PvP",
                    f"R{data.pvp_rating} • W/L {data.pvp_wins}/{data.pvp_losses} • Стрик {data.pvp_streak}",
                )
            else:
                EmbedFactory.add_kv(embed, "⚔ PvP", "Нет данных")
            if data.betting_volume is not None:
                EmbedFactory.add_kv(embed, "🎲 Ставки", f"Оборот {data.betting_volume} • Профит {data.betting_profit}")
            else:
                EmbedFactory.add_kv(embed, "🎲 Ставки", "Нет данных за период")
            if data.messages is not None or data.voice_minutes is not None:
                EmbedFactory.add_kv(
                    embed,
                    "💬 Активность",
                    f"Сообщения {data.messages or 0} • Войс {data.voice_minutes or 0} мин",
                )
            else:
                EmbedFactory.add_kv(embed, "💬 Активность", "Нет данных за период")

        if section == "economy":
            EmbedFactory.add_section(embed, "💰", "Экономика", [f"Текущий баланс: {self._format_main_balance(data)}"])

        if section == "pvp":
            if data.pvp_rating is None:
                EmbedFactory.add_section(embed, "⚔", "PvP", ["Нет данных за период"])
            else:
                EmbedFactory.add_section(
                    embed,
                    "⚔",
                    "PvP",
                    [
                        f"Рейтинг: **{data.pvp_rating}**",
                        f"Победы/Поражения: **{data.pvp_wins}/{data.pvp_losses}**",
                        f"Текущий стрик: **{data.pvp_streak}**",
                    ],
                )

        if section == "bets":
            if data.betting_volume is None:
                EmbedFactory.add_section(embed, "🎲", "Ставки", ["Нет данных за период"])
            else:
                EmbedFactory.add_section(
                    embed,
                    "🎲",
                    "Ставки",
                    [
                        f"Оборот ставок: **{data.betting_volume}**",
                        f"Профит: **{data.betting_profit}**",
                        f"Лучшая выплата: **{data.betting_best_win or 0}**",
                        f"Количество ставок: **{data.betting_total_bets or 0}**",
                    ],
                )

        if section == "activity":
            if data.messages is None and data.voice_minutes is None:
                EmbedFactory.add_section(embed, "💬", "Активность", ["Нет данных за период"])
            else:
                EmbedFactory.add_section(
                    embed,
                    "💬",
                    "Активность",
                    [
                        f"Сообщения: **{data.messages or 0}**",
                        f"Войс-минуты: **{data.voice_minutes or 0}**",
                    ],
                )

        self._build_footer(embed)
        return embed

    async def _load_data(self, guild: discord.Guild, user: discord.abc.User) -> tuple[PassportData, bool, bool]:
        cached = self._get_cached(guild.id, user.id)

        async with self.bot.db.session() as session:
            profile_result = await session.execute(
                select(GuildConfig.settings, UserProfile, PvpStats)
                .select_from(GuildConfig)
                .outerjoin(UserProfile, (UserProfile.guild_id == GuildConfig.guild_id) & (UserProfile.user_id == user.id))
                .outerjoin(PvpStats, (PvpStats.guild_id == GuildConfig.guild_id) & (PvpStats.user_id == user.id))
                .where(GuildConfig.guild_id == guild.id)
            )
            row = profile_result.first()
            settings_raw = row[0] if row else "{}"
            profile = row[1] if row else None
            pvp = row[2] if row else None
            settings_map = parse_settings(settings_raw or "{}")
            passport_settings = settings_map.get("passport", {}) if isinstance(settings_map, dict) else {}
            enabled = bool(passport_settings.get("enabled", True))
            hide_balance = bool(passport_settings.get("hide_balance_for_others", True))

            if cached:
                return cached, enabled, hide_balance

            bet_result = await session.execute(
                select(
                    func.coalesce(func.sum(case((EconomyTransaction.source.in_(["betting_bet", "coinflip_bet", "dice_bet", "roulette_bet"]), func.abs(EconomyTransaction.amount)), else_=0)), 0).label("volume"),
                    func.coalesce(func.sum(case((EconomyTransaction.source.in_(["betting_win", "coinflip_win", "dice_win", "roulette_win"]), EconomyTransaction.amount), else_=0)), 0)
                    - func.coalesce(func.sum(case((EconomyTransaction.source.in_(["betting_bet", "coinflip_bet", "dice_bet", "roulette_bet"]), func.abs(EconomyTransaction.amount)), else_=0)), 0),
                    func.coalesce(func.max(case((EconomyTransaction.source.in_(["betting_win", "coinflip_win", "dice_win", "roulette_win"]), EconomyTransaction.amount), else_=0)), 0),
                    func.coalesce(func.sum(case((EconomyTransaction.source.in_(["betting_bet", "coinflip_bet", "dice_bet", "roulette_bet"]), 1), else_=0)), 0),
                ).where((EconomyTransaction.guild_id == guild.id) & (EconomyTransaction.user_id == user.id))
            )
            betting_row = bet_result.one()

            activity_result = await session.execute(
                select(
                    func.coalesce(func.sum(case((ActivityEvent.event_type == "message", ActivityEvent.value), else_=0)), 0),
                    func.coalesce(func.sum(case((ActivityEvent.event_type == "voice_minutes", ActivityEvent.value), else_=0)), 0),
                ).where((ActivityEvent.guild_id == guild.id) & (ActivityEvent.user_id == user.id))
            )
            activity_row = activity_result.one()

        data = PassportData(
            guild_id=guild.id,
            user_id=user.id,
            username=user.display_name,
            avatar_url=user.display_avatar.url if user.display_avatar else None,
            level=int(profile.level) if profile else None,
            xp=int(profile.xp) if profile else None,
            balance=int(profile.balance) if profile else None,
            pvp_rating=int(pvp.rating) if pvp else None,
            pvp_wins=int(pvp.wins) if pvp else None,
            pvp_losses=int(pvp.losses) if pvp else None,
            pvp_streak=int(pvp.current_streak) if pvp else None,
            betting_volume=int(betting_row[0]) if betting_row and int(betting_row[3] or 0) > 0 else None,
            betting_profit=int(betting_row[1]) if betting_row and int(betting_row[3] or 0) > 0 else None,
            betting_best_win=int(betting_row[2]) if betting_row and int(betting_row[3] or 0) > 0 else None,
            betting_total_bets=int(betting_row[3]) if betting_row else None,
            messages=int(activity_row[0]) if activity_row and (int(activity_row[0]) > 0 or int(activity_row[1]) > 0) else None,
            voice_minutes=int(activity_row[1]) if activity_row and (int(activity_row[0]) > 0 or int(activity_row[1]) > 0) else None,
        )
        self._put_cache(data)
        return data, enabled, hide_balance

    @app_commands.command(name="passport", description="Показать паспорт игрока")
    async def passport(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return

        target = user or interaction.user
        data, enabled, hide_balance = await self._load_data(interaction.guild, target)
        if not enabled:
            await reply_error(interaction, "Команда /passport отключена настройками сервера.")
            return

        view_data = data
        if hide_balance and target.id != interaction.user.id:
            view_data = replace(data, balance=None)

        view = PassportView(cog=self, author_id=interaction.user.id, data=view_data)
        embed = self.build_embed("overview", view_data)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PassportCog(bot))
