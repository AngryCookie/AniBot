from __future__ import annotations

import datetime as dt
import json
import random

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.utils import get_or_create_gambling_settings
from bot.database.models import ModLog
from bot.database.operations import apply_balance_change, get_or_create_user_locked


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

    async def _prepare_bet(self, session, guild_id: int, user_id: int, amount: int):
        settings = await get_or_create_gambling_settings(session, guild_id)
        if not settings.enabled:
            raise ValueError("Азартные игры отключены.")
        user = await get_or_create_user_locked(session, guild_id, user_id)
        self._reset_daily_bets(user)
        stats = json.loads(user.gambling_stats or "{}")
        last_bet_ts = stats.get("last_bet_ts")
        now = dt.datetime.utcnow()
        if last_bet_ts:
            last_dt = dt.datetime.fromisoformat(last_bet_ts)
            if (now - last_dt).total_seconds() < settings.rate_limit_seconds:
                raise ValueError("Слишком быстро. Подождите немного.")
        if amount <= 0:
            raise ValueError("Ставка должна быть больше 0")
        if amount > settings.max_bet:
            raise ValueError("Ставка превышает максимальный лимит сервера")
        if user.daily_bet_amount + amount > settings.daily_limit:
            raise ValueError("Достигнут дневной лимит ставок")
        if user.balance < amount:
            raise ValueError("Недостаточно средств")
        stats["last_bet_ts"] = now.isoformat()
        user.gambling_stats = json.dumps(stats)
        return user, settings

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
                async with session.begin():
                    user, settings = await self._prepare_bet(
                        session, interaction.guild.id, interaction.user.id, amount
                    )
                    result = random.choice(["орел", "решка"])
                    win = result == choice
                    user.daily_bet_amount += amount
                    house_multiplier = 2.0 * (1 - settings.house_edge)
                    if win:
                        winnings = int(amount * house_multiplier)
                        tax = int(winnings * settings.tax_rate)
                        payout = winnings - tax
                        await apply_balance_change(
                            session,
                            guild_id=interaction.guild.id,
                            user_id=interaction.user.id,
                            amount=payout,
                            ledger_type="gamble",
                            source="coinflip_win",
                        )
                    else:
                        payout = -amount
                        await apply_balance_change(
                            session,
                            guild_id=interaction.guild.id,
                            user_id=interaction.user.id,
                            amount=-amount,
                            ledger_type="gamble",
                            source="coinflip_loss",
                        )
                    session.add(
                        ModLog(
                            guild_id=interaction.guild.id,
                            action="gamble_coinflip",
                            moderator_id=interaction.user.id,
                            user_id=interaction.user.id,
                            reason=str(payout),
                        )
                    )
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
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
                async with session.begin():
                    user, settings = await self._prepare_bet(
                        session, interaction.guild.id, interaction.user.id, amount
                    )
                    roll = random.randint(1, 6)
                    win = roll == guess
                    user.daily_bet_amount += amount
                    house_multiplier = 5.0 * (1 - settings.house_edge)
                    if win:
                        winnings = int(amount * house_multiplier)
                        tax = int(winnings * settings.tax_rate)
                        payout = winnings - tax
                        await apply_balance_change(
                            session,
                            guild_id=interaction.guild.id,
                            user_id=interaction.user.id,
                            amount=payout,
                            ledger_type="gamble",
                            source="dice_win",
                        )
                    else:
                        payout = -amount
                        await apply_balance_change(
                            session,
                            guild_id=interaction.guild.id,
                            user_id=interaction.user.id,
                            amount=-amount,
                            ledger_type="gamble",
                            source="dice_loss",
                        )
                    session.add(
                        ModLog(
                            guild_id=interaction.guild.id,
                            action="gamble_dice",
                            moderator_id=interaction.user.id,
                            user_id=interaction.user.id,
                            reason=str(payout),
                        )
                    )
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
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
                async with session.begin():
                    user, settings = await self._prepare_bet(
                        session, interaction.guild.id, interaction.user.id, amount
                    )
                    roll = random.randint(0, 36)
                    win = roll == guess
                    user.daily_bet_amount += amount
                    house_multiplier = 10.0 * (1 - settings.house_edge)
                    if win:
                        winnings = int(amount * house_multiplier)
                        tax = int(winnings * settings.tax_rate)
                        payout = winnings - tax
                        await apply_balance_change(
                            session,
                            guild_id=interaction.guild.id,
                            user_id=interaction.user.id,
                            amount=payout,
                            ledger_type="gamble",
                            source="roulette_win",
                        )
                    else:
                        payout = -amount
                        await apply_balance_change(
                            session,
                            guild_id=interaction.guild.id,
                            user_id=interaction.user.id,
                            amount=-amount,
                            ledger_type="gamble",
                            source="roulette_loss",
                        )
                    session.add(
                        ModLog(
                            guild_id=interaction.guild.id,
                            action="gamble_roulette",
                            moderator_id=interaction.user.id,
                            user_id=interaction.user.id,
                            reason=str(payout),
                        )
                    )
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(
            f"Рулетка: {roll}. {'Вы выиграли' if win else 'Вы проиграли'} {payout}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GamblingCog(bot))
