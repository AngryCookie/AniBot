from __future__ import annotations

import datetime as dt
import json
import random

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.utils import get_or_create_guild, get_or_create_user


class GamblingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _reset_daily_bets(self, user) -> None:
        stats = json.loads(user.gambling_stats or "{}")
        last_date = stats.get("last_bet_date")
        today = dt.date.today().isoformat()
        if last_date != today:
            user.daily_bet_amount = 0
            stats["last_bet_date"] = today
            user.gambling_stats = json.dumps(stats)

    def _can_bet(self, user, amount: int) -> bool:
        return user.daily_bet_amount + amount <= user.level * 1000

    async def _apply_bet(self, session, user, amount: int, win: bool, multiplier: float) -> int:
        user.daily_bet_amount += amount
        if win:
            winnings = int(amount * multiplier)
            tax = int(winnings * 0.1)
            user.balance += winnings - tax
            await session.commit()
            return winnings - tax
        user.balance -= amount
        await session.commit()
        return -amount

    async def _prepare_bet(self, session, guild_id: int, user_id: int, amount: int):
        user = await get_or_create_user(session, guild_id, user_id)
        self._reset_daily_bets(user)
        if amount <= 0:
            raise ValueError("Ставка должна быть больше 0")
        if amount > user.level * 100:
            raise ValueError("Ставка превышает лимит уровня")
        if not self._can_bet(user, amount):
            raise ValueError("Достигнут дневной лимит ставок")
        if user.balance < amount:
            raise ValueError("Недостаточно средств")
        return user

    @app_commands.command(name="coinflip", description="Игра орел/решка")
    async def coinflip(
        self, interaction: discord.Interaction, choice: str, amount: int
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        choice = choice.lower()
        if choice not in {"орел", "решка"}:
            await interaction.response.send_message("Выберите: орел или решка.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            try:
                user = await self._prepare_bet(session, interaction.guild.id, interaction.user.id, amount)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            result = random.choice(["орел", "решка"])
            win = result == choice
            payout = await self._apply_bet(session, user, amount, win, 2.0)
        await interaction.response.send_message(
            f"Выпало: {result}. {'Вы выиграли' if win else 'Вы проиграли'} {payout}.",
            ephemeral=True,
        )

    @app_commands.command(name="dice", description="Бросить кубик")
    async def dice(self, interaction: discord.Interaction, guess: int, amount: int) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        if guess < 1 or guess > 6:
            await interaction.response.send_message("Укажите число от 1 до 6.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            try:
                user = await self._prepare_bet(session, interaction.guild.id, interaction.user.id, amount)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            roll = random.randint(1, 6)
            win = roll == guess
            payout = await self._apply_bet(session, user, amount, win, 5.0)
        await interaction.response.send_message(
            f"Кубик: {roll}. {'Вы выиграли' if win else 'Вы проиграли'} {payout}.",
            ephemeral=True,
        )

    @app_commands.command(name="roulette", description="Рулетка 0-36")
    async def roulette(self, interaction: discord.Interaction, guess: int, amount: int) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        if guess < 0 or guess > 36:
            await interaction.response.send_message("Укажите число от 0 до 36.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            try:
                user = await self._prepare_bet(session, interaction.guild.id, interaction.user.id, amount)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            roll = random.randint(0, 36)
            win = roll == guess
            payout = await self._apply_bet(session, user, amount, win, 10.0)
        await interaction.response.send_message(
            f"Рулетка: {roll}. {'Вы выиграли' if win else 'Вы проиграли'} {payout}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GamblingCog(bot))
