from __future__ import annotations

import datetime as dt
import json

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.utils import get_or_create_guild, get_or_create_user, get_role_multiplier, parse_settings
from bot.database.models import ModLog
from bot.database.operations import get_or_create_user_locked
from bot.services.economy import EconomyService


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="balance", description="Показать баланс")
    async def balance(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        target = member or interaction.user
        async with self.bot.db.session() as session:
            user = await get_or_create_user(session, interaction.guild.id, target.id)
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
        await interaction.response.send_message(
            f"Баланс {target.mention}: {user.balance} {guild.currency_name}",
            ephemeral=True,
        )

    @app_commands.command(name="daily", description="Получить ежедневный доход")
    async def daily(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            async with session.begin():
                user = await get_or_create_user_locked(
                    session, interaction.guild.id, interaction.user.id
                )
                guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
                now = dt.datetime.utcnow()
                if user.last_daily_ts and (now - user.last_daily_ts).total_seconds() < 86400:
                    remaining = 86400 - int((now - user.last_daily_ts).total_seconds())
                    hours = remaining // 3600
                    minutes = (remaining % 3600) // 60
                    await interaction.response.send_message(
                        f"До следующего /daily осталось {hours}ч {minutes}м.",
                        ephemeral=True,
                    )
                    return
                base_income = int(user.level * 500 * guild.server_rate)
                multiplier = get_role_multiplier(interaction.user)
                final_income = int(base_income * multiplier)
                if user.voice_join_ts and (now - user.voice_join_ts).total_seconds() >= 10800:
                    final_income = int(final_income * 0.7)
                user.daily_income = final_income
                user.last_daily_ts = now
                await EconomyService(session).daily_reward(
                    guild_id=interaction.guild.id,
                    user_id=interaction.user.id,
                    amount=final_income,
                )
                session.add(
                    ModLog(
                        guild_id=interaction.guild.id,
                        action="economy_daily",
                        moderator_id=interaction.user.id,
                        user_id=interaction.user.id,
                        reason=f"+{final_income}",
                    )
                )
        await interaction.response.send_message(
            f"Вы получили {final_income} {guild.currency_name}.", ephemeral=True
        )

    @app_commands.command(name="transfer", description="Перевести валюту")
    async def transfer(
        self, interaction: discord.Interaction, member: discord.Member, amount: int
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        if amount <= 0:
            await interaction.response.send_message("Сумма должна быть больше 0.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            async with session.begin():
                sender = await get_or_create_user_locked(
                    session, interaction.guild.id, interaction.user.id
                )
                await get_or_create_user_locked(session, interaction.guild.id, member.id)
                guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
                settings = parse_settings(guild.settings)
                fee_percent = float(settings.get("transfer_fee_percent", 0.02))
                max_transfer = int(settings.get("transfer_max", 100000))
                if amount > max_transfer:
                    await interaction.response.send_message(
                        "Сумма превышает лимит перевода.", ephemeral=True
                    )
                    return
                fee = int(amount * fee_percent)
                total = amount + fee
                if sender.balance < total:
                    await interaction.response.send_message("Недостаточно средств.", ephemeral=True)
                    return
                economy = EconomyService(session)
                await economy.transfer(
                    guild_id=interaction.guild.id,
                    from_user_id=interaction.user.id,
                    to_user_id=member.id,
                    amount=amount,
                    source="transfer",
                )
                if fee > 0:
                    await economy.debit(
                        interaction.guild.id,
                        interaction.user.id,
                        fee,
                        "transfer_fee",
                        {"recipient_user_id": member.id},
                        ledger_type="spend",
                    )
                session.add(
                    ModLog(
                        guild_id=interaction.guild.id,
                        action="economy_transfer",
                        moderator_id=interaction.user.id,
                        user_id=member.id,
                        reason=f"{amount}",
                    )
                )
        await interaction.response.send_message(
            f"Перевод выполнен: {amount} {guild.currency_name} (комиссия {fee}).",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCog(bot))
