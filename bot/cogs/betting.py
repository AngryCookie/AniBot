from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.betting import BettingService
from bot.betting.models import BettingMatch, BettingTeam
from bot.database.models import ModLog, UserProfile
from bot.services.feature_flags import is_feature_enabled
from bot.ui import ConfirmView, EmbedFactory, reply_error

BETTING_FLAG_NAME = "betting_enabled"


def _format_timedelta(delta: dt.timedelta) -> str:
    total_seconds = max(0, int(delta.total_seconds()))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts: list[str] = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    if not parts:
        parts.append(f"{seconds}с")
    return " ".join(parts)


async def _load_open_matches(session, guild_id: int) -> list[tuple[BettingMatch, BettingTeam, BettingTeam]]:
    now = dt.datetime.utcnow()
    rows = await session.execute(
        select(BettingMatch).where(
            (BettingMatch.guild_id == guild_id)
            & (BettingMatch.resolved_at.is_(None))
            & (BettingMatch.betting_close_at > now)
        )
    )
    matches = rows.scalars().all()
    items: list[tuple[BettingMatch, BettingTeam, BettingTeam]] = []
    for match in matches:
        team_a = await session.get(BettingTeam, match.team_a_id)
        team_b = await session.get(BettingTeam, match.team_b_id)
        if team_a and team_b:
            items.append((match, team_a, team_b))
    items.sort(key=lambda item: item[0].betting_close_at)
    return items


class BetAmountModal(discord.ui.Modal, title="💸 Сумма ставки"):
    amount = discord.ui.TextInput(label="Сумма", placeholder="Например: 250", max_length=12)

    def __init__(self, view: "BetMatchDetailView", team_key: str):
        super().__init__()
        self.view = view
        self.team_key = team_key

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.amount.value).strip()
        if not raw.isdigit():
            await reply_error(interaction, "⚠ Сумма должна быть целым числом", "Введите число без пробелов и символов.")
            return
        amount = int(raw)
        if amount <= 0:
            await reply_error(interaction, "⚠ Сумма должна быть больше 0")
            return
        await self.view.open_confirm(interaction, self.team_key, amount)


class BetMatchPicker(discord.ui.Select):
    def __init__(self, parent: "BetsListView", options: list[discord.SelectOption]):
        super().__init__(placeholder="Выберите матч", min_values=1, max_values=1, options=options)
        self.parent = parent

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.parent.pick_match(interaction, int(self.values[0]))


class BetsListView(discord.ui.View):
    def __init__(self, cog: "BettingCog", author_id: int, items: list[tuple[BettingMatch, BettingTeam, BettingTeam]]):
        super().__init__(timeout=60)
        self.cog = cog
        self.author_id = author_id
        self.items = items
        self.message: discord.Message | None = None
        self.add_item(BetMatchPicker(self, self._build_options()))

    def _build_options(self) -> list[discord.SelectOption]:
        now = dt.datetime.utcnow()
        options: list[discord.SelectOption] = []
        for match, team_a, team_b in self.items[:25]:
            left = _format_timedelta(match.betting_close_at - now)
            options.append(
                discord.SelectOption(
                    label=f"#{match.id} • {team_a.name} vs {team_b.name}",
                    description=f"До закрытия: {left}",
                    value=str(match.id),
                )
            )
        return options

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await reply_error(interaction, "Это окно ставок открыто для другого пользователя.", "Откройте /bets у себя.")
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

    async def pick_match(self, interaction: discord.Interaction, match_id: int) -> None:
        picked = next((item for item in self.items if item[0].id == match_id), None)
        if picked is None:
            await reply_error(interaction, "Матч не найден.")
            return
        match, team_a, team_b = picked
        detail_view = BetMatchDetailView(self.cog, self.author_id, match, team_a, team_b, self)
        await interaction.response.edit_message(embed=detail_view.build_embed(), view=detail_view)
        detail_view.message = interaction.message


class BetMatchDetailView(discord.ui.View):
    def __init__(
        self,
        cog: "BettingCog",
        author_id: int,
        match: BettingMatch,
        team_a: BettingTeam,
        team_b: BettingTeam,
        list_view: BetsListView | None,
    ):
        super().__init__(timeout=60)
        self.cog = cog
        self.author_id = author_id
        self.match = match
        self.team_a = team_a
        self.team_b = team_b
        self.list_view = list_view
        self.message: discord.Message | None = None
        self.pick_a.label = f"🅰 Ставка на {team_a.name}"
        self.pick_b.label = f"🅱 Ставка на {team_b.name}"

    def build_embed(self) -> discord.Embed:
        now = dt.datetime.utcnow()
        left = _format_timedelta(self.match.betting_close_at - now)
        embed = EmbedFactory.info(f"🎲 Матч #{self.match.id}", f"{self.team_a.name} vs {self.team_b.name}")
        EmbedFactory.add_kv(embed, "📈 Коэффициент A", f"{self.team_a.name}: {self.match.odds_a:.2f}")
        EmbedFactory.add_kv(embed, "📈 Коэффициент B", f"{self.team_b.name}: {self.match.odds_b:.2f}")
        EmbedFactory.add_kv(embed, "⏱ До закрытия", left)
        EmbedFactory.add_kv(embed, "💰 Лимиты", f"Мин: {self.match.min_bet} • Макс: {self.match.max_bet}", inline=False)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await reply_error(interaction, "Это окно ставок открыто для другого пользователя.", "Откройте /bets у себя.")
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

    @discord.ui.button(label="🅰 Ставка на A", style=discord.ButtonStyle.primary)
    async def pick_a(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(BetAmountModal(self, "A"))

    @discord.ui.button(label="🅱 Ставка на B", style=discord.ButtonStyle.primary)
    async def pick_b(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(BetAmountModal(self, "B"))

    @discord.ui.button(label="⬅ Назад к списку", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.list_view is None:
            await reply_error(interaction, "Список матчей недоступен.", "Запустите /bets для выбора другого матча.")
            return
        await interaction.response.edit_message(embed=self.cog.build_bets_embed(self.list_view.items), view=self.list_view)
        self.list_view.message = interaction.message

    async def open_confirm(self, interaction: discord.Interaction, team_key: str, amount: int) -> None:
        now = dt.datetime.utcnow()
        if now >= self.match.betting_close_at:
            await reply_error(interaction, "⛔ Окно ставок закрыто")
            return
        if amount < self.match.min_bet:
            await reply_error(interaction, f"⚠ Минимальная ставка: {self.match.min_bet}")
            return
        if amount > self.match.max_bet:
            await reply_error(interaction, f"⚠ Максимальная ставка: {self.match.max_bet}")
            return
        guild = interaction.guild
        if guild is None:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return

        async with self.cog.bot.db.session() as session:
            result = await session.execute(
                select(UserProfile.balance).where(
                    (UserProfile.guild_id == guild.id) & (UserProfile.user_id == interaction.user.id)
                )
            )
            balance = int(result.scalar() or 0)
        if balance < amount:
            await reply_error(interaction, "❌ Недостаточно средств")
            return

        team = self.team_a if team_key == "A" else self.team_b
        odds = self.match.odds_a if team_key == "A" else self.match.odds_b
        potential = amount * float(odds)
        left = _format_timedelta(self.match.betting_close_at - now)

        embed = EmbedFactory.warn("✅ Подтверждение ставки", f"Матч #{self.match.id}: {self.team_a.name} vs {self.team_b.name}")
        EmbedFactory.add_kv(embed, "🎯 Выбор", team.name)
        EmbedFactory.add_kv(embed, "📈 Коэффициент", f"{odds:.2f}")
        EmbedFactory.add_kv(embed, "💰 Сумма", str(amount))
        EmbedFactory.add_kv(embed, "🏁 Потенциальная выплата", f"{potential:.2f}", inline=False)
        EmbedFactory.add_section(embed, "⏱", "Важно", [f"Окно ставок закроется через {left}."])

        async def _confirm(i: discord.Interaction) -> None:
            if i.guild is None:
                await reply_error(i, "Команда доступна только на сервере.")
                return
            try:
                async with self.cog.bot.db.session() as session:
                    async with session.begin():
                        service = BettingService(session)
                        await service.place_bet(i.guild.id, i.user.id, self.match.id, team.id, amount)
                        session.add(
                            ModLog(
                                guild_id=i.guild.id,
                                action="bet_place",
                                moderator_id=i.user.id,
                                user_id=i.user.id,
                                reason=f"match={self.match.id};team={team.id};amount={amount}",
                            )
                        )
            except ValueError as exc:
                await reply_error(i, str(exc))
                return
            done = EmbedFactory.success("🎉 Ставка принята", f"{team.name} на сумму {amount}")
            await i.response.edit_message(embed=done, view=view)

        async def _cancel(i: discord.Interaction) -> None:
            cancelled = EmbedFactory.warn("Ставка отменена", "Вы можете выбрать другой матч через /bets.")
            await i.response.edit_message(embed=cancelled, view=view)

        view = ConfirmView(author_id=self.author_id, on_confirm=_confirm, on_cancel=_cancel, timeout=60)
        view.confirm.label = "✅ Подтвердить"
        view.cancel.label = "❌ Отмена"
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            msg = await interaction.original_response()
        view.message = msg


class BettingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def build_bets_embed(self, items: list[tuple[BettingMatch, BettingTeam, BettingTeam]]) -> discord.Embed:
        now = dt.datetime.utcnow()
        embed = EmbedFactory.info("🎲 Ставки: активные матчи", "Выберите матч в меню ниже.")
        for match, team_a, team_b in items[:10]:
            left = _format_timedelta(match.betting_close_at - now)
            EmbedFactory.add_kv(
                embed,
                f"🎮 Матч #{match.id}",
                f"{team_a.name} vs {team_b.name}\nКоэф: {match.odds_a:.2f}/{match.odds_b:.2f} • {left}",
                inline=False,
            )
        EmbedFactory.add_section(embed, "💡", "Подсказка", ["Для быстрого ввода используйте /bet <match_id> <team> <amount>."])
        return embed

    async def _open_match_detail(self, interaction: discord.Interaction, match_id: int) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            if not await is_feature_enabled(session, interaction.guild.id, BETTING_FLAG_NAME):
                await reply_error(interaction, "Ставки сейчас отключены.", "Попробуйте позже.")
                return
            match = await session.get(BettingMatch, match_id)
            if match is None or match.guild_id != interaction.guild.id:
                await reply_error(interaction, "Матч не найден.")
                return
            team_a = await session.get(BettingTeam, match.team_a_id)
            team_b = await session.get(BettingTeam, match.team_b_id)
            if team_a is None or team_b is None:
                await reply_error(interaction, "Команды матча недоступны.")
                return
            if dt.datetime.utcnow() >= match.betting_close_at or match.resolved_at is not None:
                await reply_error(interaction, "⛔ Окно ставок закрыто")
                return
        view = BetMatchDetailView(self, interaction.user.id, match, team_a, team_b, list_view=None)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="bets", description="Показать активные матчи")
    async def bets(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            if not await is_feature_enabled(session, interaction.guild.id, BETTING_FLAG_NAME):
                await reply_error(interaction, "Ставки сейчас отключены.", "Попробуйте позже.")
                return
            items = await _load_open_matches(session, interaction.guild.id)
        if not items:
            embed = EmbedFactory.info("🎲 Ставки", "Сейчас нет активных матчей.")
            EmbedFactory.add_section(embed, "💡", "Подсказка", ["Загляни позже"])
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        view = BetsListView(self, interaction.user.id, items)
        await interaction.response.send_message(embed=self.build_bets_embed(items), view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="bet", description="Сделать ставку на матч")
    @app_commands.choices(team=[app_commands.Choice(name="A", value="A"), app_commands.Choice(name="B", value="B")])
    async def bet(
        self,
        interaction: discord.Interaction,
        match_id: int,
        team: app_commands.Choice[str],
        amount: app_commands.Range[int, 0] = 0,
    ) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        if amount <= 0:
            await self._open_match_detail(interaction, match_id)
            return
        async with self.bot.db.session() as session:
            if not await is_feature_enabled(session, interaction.guild.id, BETTING_FLAG_NAME):
                await reply_error(interaction, "Ставки сейчас отключены.", "Попробуйте позже.")
                return
            match = await session.get(BettingMatch, match_id)
            if match is None or match.guild_id != interaction.guild.id:
                await reply_error(interaction, "Матч не найден.")
                return
            team_a = await session.get(BettingTeam, match.team_a_id)
            team_b = await session.get(BettingTeam, match.team_b_id)
            if team_a is None or team_b is None:
                await reply_error(interaction, "Команды матча недоступны.")
                return
        view = BetMatchDetailView(self, interaction.user.id, match, team_a, team_b, list_view=None)
        await view.open_confirm(interaction, team.value, amount)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BettingCog(bot))
