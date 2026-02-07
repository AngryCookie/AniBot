from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.utils import get_or_create_guild, get_or_create_user, get_role_multiplier


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
            user = await get_or_create_user(session, interaction.guild.id, interaction.user.id)
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
            user.balance += final_income
            user.daily_income = final_income
            user.last_daily_ts = now
            await session.commit()
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
            sender = await get_or_create_user(session, interaction.guild.id, interaction.user.id)
            recipient = await get_or_create_user(session, interaction.guild.id, member.id)
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            if sender.balance < amount:
                await interaction.response.send_message("Недостаточно средств.", ephemeral=True)
                return
            sender.balance -= amount
            recipient.balance += amount
            await session.commit()
        await interaction.response.send_message(
            f"Перевод выполнен: {amount} {guild.currency_name}", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCog(bot))
