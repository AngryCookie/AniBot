from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.betting import BettingService, core
from bot.betting.models import BettingMatch, BettingTeam
from bot.database.models import ModLog, UserProfile
from bot.services.feature_flags import is_feature_enabled
from bot.ui import AmountModal, ConfirmView, EmbedFactory, reply_error

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


class BetAmountModal(AmountModal):
    def __init__(self, view: "BetTeamView", team_key: str):
        super().__init__(min_amount=1)
        self.view = view
        self.team_key = team_key

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await super().on_submit(interaction)
        if self.value is None:
            return
        await self.view.confirm_bet(interaction, self.team_key, self.value)


class BetTeamView(discord.ui.View):
    def __init__(self, cog: "BettingCog", author_id: int, match: BettingMatch, team_a: BettingTeam, team_b: BettingTeam):
        super().__init__(timeout=60)
        self.cog = cog
        self.author_id = author_id
        self.match = match
        self.team_a = team_a
        self.team_b = team_b
        self.message: discord.Message | None = None

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

    @discord.ui.button(label="Ставка на A", style=discord.ButtonStyle.primary)
    async def pick_a(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(BetAmountModal(self, "A"))

    @discord.ui.button(label="Ставка на B", style=discord.ButtonStyle.primary)
    async def pick_b(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(BetAmountModal(self, "B"))

    async def confirm_bet(self, interaction: discord.Interaction, team_key: str, amount: int) -> None:
        team = self.team_a if team_key == "A" else self.team_b
        odds = self.match.odds_a if team_key == "A" else self.match.odds_b
        opponent = self.team_b.name if team_key == "A" else self.team_a.name
        if odds is None:
            await reply_error(interaction, "Коэффициенты еще не готовы.", "Подождите обновления матча.")
            return
        async with self.cog.bot.db.session() as session:
            result = await session.execute(select(UserProfile.balance).where((UserProfile.guild_id == interaction.guild.id) & (UserProfile.user_id == interaction.user.id)))
            balance = result.scalar() or 0
        if balance < amount:
            await reply_error(interaction, "Недостаточно средств для ставки.", "Уменьшите сумму ставки.")
            return
        potential = amount * float(odds)
        time_left = _format_timedelta(self.match.betting_close_at - dt.datetime.utcnow())
        embed = EmbedFactory.warn("Подтверждение ставки", f"Матч #{self.match.id}: {team.name} vs {opponent}")
        EmbedFactory.add_kv(embed, "🎯 Команда", team.name)
        EmbedFactory.add_kv(embed, "💰 Сумма", str(amount))
        EmbedFactory.add_kv(embed, "📈 Коэф", f"{odds:.2f}")
        EmbedFactory.add_kv(embed, "🏁 Потенциальная выплата", f"{potential:.2f}", inline=False)
        EmbedFactory.add_section(embed, "⏱️", "Окно ставок", [f"Закроется через {time_left}."])

        async def _confirm(i: discord.Interaction) -> None:
            async with self.cog.bot.db.session() as session:
                async with session.begin():
                    service = BettingService(session)
                    await service.place_bet(interaction.guild.id, interaction.user.id, self.match.id, team.id, amount)
                    session.add(ModLog(guild_id=interaction.guild.id, action="bet_place", moderator_id=interaction.user.id, user_id=interaction.user.id, reason=f"match={self.match.id};team={team.id};amount={amount}"))
            done = EmbedFactory.success("Ставка принята", f"{team.name} на сумму {amount}")
            await i.response.edit_message(embed=done, view=None)

        view = ConfirmView(author_id=self.author_id, on_confirm=_confirm)
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        view.message = msg


class BettingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="bets", description="Показать активные матчи")
    async def bets(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            if not await is_feature_enabled(session, interaction.guild.id, BETTING_FLAG_NAME):
                await reply_error(interaction, "Ставки сейчас отключены.", "Попробуйте позже.")
                return
            now = dt.datetime.utcnow()
            rows = await session.execute(select(BettingMatch).where((BettingMatch.guild_id == interaction.guild.id) & (BettingMatch.resolved_at.is_(None))))
            matches = rows.scalars().all()
            if not matches:
                await reply_error(interaction, "Сейчас нет активных матчей.")
                return
            embed = EmbedFactory.info("Активные матчи", "Выберите матч через /bet или кнопки ниже.")
            first_open = None
            for match in matches:
                ta = await session.get(BettingTeam, match.team_a_id)
                tb = await session.get(BettingTeam, match.team_b_id)
                if not ta or not tb:
                    continue
                left = _format_timedelta(match.betting_close_at - now)
                EmbedFactory.add_kv(embed, f"🎮 Матч #{match.id}: {ta.name} vs {tb.name}", f"Коэф: {match.odds_a:.2f}/{match.odds_b:.2f} • {left}", inline=False)
                if first_open is None and match.betting_close_at > now:
                    first_open = (match, ta, tb)
        if first_open:
            view = BetTeamView(self, interaction.user.id, first_open[0], first_open[1], first_open[2])
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.message = await interaction.original_response()
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="bet", description="Сделать ставку на матч")
    @app_commands.choices(team=[app_commands.Choice(name="A", value="A"), app_commands.Choice(name="B", value="B")])
    async def bet(self, interaction: discord.Interaction, match_id: int, team: app_commands.Choice[str], amount: int) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        if amount <= 0:
            await reply_error(interaction, "Ставка должна быть больше 0.")
            return
        async with self.bot.db.session() as session:
            if not await is_feature_enabled(session, interaction.guild.id, BETTING_FLAG_NAME):
                await reply_error(interaction, "Ставки сейчас отключены.", "Попробуйте позже.")
                return
            match = await session.get(BettingMatch, match_id)
            if match is None:
                await reply_error(interaction, "Матч не найден.")
                return
            team_a = await session.get(BettingTeam, match.team_a_id)
            team_b = await session.get(BettingTeam, match.team_b_id)
            if team_a is None or team_b is None:
                await reply_error(interaction, "Команды матча недоступны.")
                return
            now = dt.datetime.utcnow()
            if not core.is_betting_open(core.Match(match.id, core.Team(team_a.id, team_a.name, float(team_a.current_power)), core.Team(team_b.id, team_b.name, float(team_b.current_power)), match.betting_open_at, match.betting_close_at, match.resolved_at, match.odds_a, match.odds_b, None), now):
                await reply_error(interaction, "Окно ставок уже закрыто для этого матча.")
                return
        view = BetTeamView(self, interaction.user.id, match, team_a, team_b)
        await view.confirm_bet(interaction, team.value, amount)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BettingCog(bot))
