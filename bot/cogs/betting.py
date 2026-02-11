from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands

from bot.betting import BettingService, core
from bot.betting.models import BettingMatch, BettingTeam
from bot.database.models import UserProfile
from bot.services.feature_flags import is_feature_enabled


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



class BetConfirmView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        author_id: int,
        guild_id: int,
        match_id: int,
        team_id: int,
        team_name: str,
        opponent_name: str,
        amount: int,
        odds: float,
        betting_close_at: dt.datetime,
    ) -> None:
        super().__init__(timeout=60)
        self.bot = bot
        self.author_id = author_id
        self.guild_id = guild_id
        self.match_id = match_id
        self.team_id = team_id
        self.team_name = team_name
        self.opponent_name = opponent_name
        self.amount = amount
        self.odds = odds
        self.betting_close_at = betting_close_at
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Эта ставка принадлежит другому пользователю.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        self._disable_buttons()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                return

    def _disable_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    def _success_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Ставка принята",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Матч",
            value=f"#{self.match_id}: {self.team_name} vs {self.opponent_name}",
            inline=False,
        )
        embed.add_field(name="Команда", value=self.team_name, inline=True)
        embed.add_field(name="Ставка", value=str(self.amount), inline=True)
        embed.add_field(name="Коэффициент", value=f"{self.odds:.2f}", inline=True)
        embed.add_field(
            name="Потенциальная выплата",
            value=f"{self.amount * self.odds:.2f}",
            inline=False,
        )
        return embed

    @discord.ui.button(label="Подтвердить", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._disable_buttons()
        async with self.bot.db.session() as session:
            if not await is_feature_enabled(session, self.guild_id, BETTING_FLAG_NAME):
                await interaction.response.edit_message(
                    content="Ставки временно недоступны.", embed=None, view=None
                )
                return
            try:
                async with session.begin():
                    service = BettingService(session)
                    await service.place_bet(
                        guild_id=self.guild_id,
                        user_id=self.author_id,
                        match_id=self.match_id,
                        team_id=self.team_id,
                        amount=self.amount,
                    )
            except ValueError as exc:
                await interaction.response.edit_message(
                    content=f"Не удалось принять ставку: {exc}",
                    embed=None,
                    view=None,
                )
                return
        await interaction.response.edit_message(
            content=None,
            embed=self._success_embed(),
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._disable_buttons()
        await interaction.response.edit_message(
            content="Ставка отменена.", embed=None, view=None
        )
        self.stop()


class BettingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="bets", description="Показать активные матчи")
    async def bets(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return
        async with self.bot.db.session() as session:
            if not await is_feature_enabled(session, interaction.guild.id, BETTING_FLAG_NAME):
                await interaction.response.send_message(
                    "Ставки сейчас отключены. Попробуйте позже.", ephemeral=True
                )
                return
            service = BettingService(session)
            now = dt.datetime.utcnow()
            matches = await service.get_active_matches(now)
            if not matches:
                await interaction.response.send_message(
                    "Сейчас нет активных матчей для ставок. Загляните позже.",
                    ephemeral=True,
                )
                return
            embed = discord.Embed(
                title="Активные матчи",
                color=discord.Color.blurple(),
            )
            for match in matches:
                team_a = await session.get(BettingTeam, match.team_a_id)
                team_b = await session.get(BettingTeam, match.team_b_id)
                team_a_name = team_a.name if team_a else "Команда A"
                team_b_name = team_b.name if team_b else "Команда B"
                time_left = _format_timedelta(match.betting_close_at - now)
                embed.add_field(
                    name=f"Матч #{match.id}: {team_a_name} vs {team_b_name}",
                    value=(
                        f"Коэф. A: {match.odds_a:.2f} | Коэф. B: {match.odds_b:.2f}\n"
                        f"Осталось: {time_left}"
                    ),
                    inline=False,
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="bet", description="Сделать ставку на матч")
    @app_commands.choices(
        team=[
            app_commands.Choice(name="A", value="A"),
            app_commands.Choice(name="B", value="B"),
        ]
    )
    async def bet(
        self,
        interaction: discord.Interaction,
        match_id: int,
        team: app_commands.Choice[str],
        amount: int,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return
        if amount <= 0:
            await interaction.response.send_message(
                "Ставка должна быть больше 0.", ephemeral=True
            )
            return
        async with self.bot.db.session() as session:
            if not await is_feature_enabled(session, interaction.guild.id, BETTING_FLAG_NAME):
                await interaction.response.send_message(
                    "Ставки сейчас отключены. Попробуйте позже.", ephemeral=True
                )
                return
            match = await session.get(BettingMatch, match_id)
            if match is None:
                await interaction.response.send_message(
                    "Матч не найден.", ephemeral=True
                )
                return
            team_a = await session.get(BettingTeam, match.team_a_id)
            team_b = await session.get(BettingTeam, match.team_b_id)
            if team_a is None or team_b is None:
                await interaction.response.send_message(
                    "Команды матча недоступны.", ephemeral=True
                )
                return
            now = dt.datetime.utcnow()
            core_match = core.Match(
                match.id,
                core.Team(team_a.id, team_a.name, float(team_a.current_power)),
                core.Team(team_b.id, team_b.name, float(team_b.current_power)),
                match.betting_open_at,
                match.betting_close_at,
                match.resolved_at,
                match.odds_a,
                match.odds_b,
                None,
            )
            if not core.is_betting_open(core_match, now):
                await interaction.response.send_message(
                    "Окно ставок уже закрыто для этого матча.", ephemeral=True
                )
                return
            if team.value == "A":
                team_id = team_a.id
                team_name = team_a.name
                opponent_name = team_b.name
                odds = match.odds_a
            else:
                team_id = team_b.id
                team_name = team_b.name
                opponent_name = team_a.name
                odds = match.odds_b
            if odds is None:
                await interaction.response.send_message(
                    "Коэффициенты еще не готовы.", ephemeral=True
                )
                return
            result = await session.execute(
                select(UserProfile.balance).where(
                    (UserProfile.guild_id == interaction.guild.id)
                    & (UserProfile.user_id == interaction.user.id)
                )
            )
            balance = result.scalar() or 0
            if balance < amount:
                await interaction.response.send_message(
                    "Недостаточно средств для ставки.", ephemeral=True
                )
                return
        time_left = _format_timedelta(match.betting_close_at - now)
        embed = discord.Embed(
            title="Подтверждение ставки",
            description=f"Матч #{match.id}: {team_a.name} vs {team_b.name}",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Команда", value=team_name, inline=True)
        embed.add_field(name="Ставка", value=str(amount), inline=True)
        embed.add_field(name="Коэффициент", value=f"{odds:.2f}", inline=True)
        embed.add_field(
            name="Потенциальная выплата", value=f"{amount * odds:.2f}", inline=False
        )
        embed.add_field(name="Осталось времени", value=time_left, inline=False)
        view = BetConfirmView(
            self.bot,
            author_id=interaction.user.id,
            guild_id=interaction.guild.id,
            match_id=match.id,
            team_id=team_id,
            team_name=team_name,
            opponent_name=opponent_name,
            amount=amount,
            odds=odds,
            betting_close_at=match.betting_close_at,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BettingCog(bot))
