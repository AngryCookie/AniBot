from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.utils import get_or_create_guild, get_or_create_user, get_role_multiplier, parse_settings
from bot.database.models import ModLog
from bot.database.operations import get_or_create_user_locked
from bot.services.economy import EconomyService
from bot.ui import AmountModal, ConfirmView, EmbedFactory, reply_error, reply_success


class TransferAmountModal(AmountModal):
    def __init__(self, cog: "EconomyCog", interaction: discord.Interaction, member: discord.Member) -> None:
        super().__init__(min_amount=1)
        self.cog = cog
        self.base_interaction = interaction
        self.member = member

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await super().on_submit(interaction)
        if self.value is None:
            return
        await self.cog._run_transfer(self.base_interaction, self.member, self.value)


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="balance", description="Показать баланс")
    async def balance(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        target = member or interaction.user
        async with self.bot.db.session() as session:
            user = await get_or_create_user(session, interaction.guild.id, target.id)
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
        embed = EmbedFactory.info("Баланс", f"{target.mention}: **{user.balance} {guild.currency_name}**")
        EmbedFactory.add_section(embed, "💡", "Быстрые действия", ["Нажмите кнопку ниже или используйте slash-команду."])
        view = discord.ui.View(timeout=60)
        view.add_item(discord.ui.Button(label="daily", style=discord.ButtonStyle.secondary, custom_id="eco:daily"))
        view.add_item(discord.ui.Button(label="transfer", style=discord.ButtonStyle.secondary, custom_id="eco:transfer"))
        view.add_item(discord.ui.Button(label="shop", style=discord.ButtonStyle.secondary, custom_id="eco:shop"))
        await interaction.response.send_message(embed=embed, ephemeral=True, view=view)

    @app_commands.command(name="daily", description="Получить ежедневный доход")
    async def daily(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return

        async def _confirm(i: discord.Interaction) -> None:
            async with self.bot.db.session() as session:
                async with session.begin():
                    user = await get_or_create_user_locked(session, interaction.guild.id, interaction.user.id)
                    guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
                    now = dt.datetime.utcnow()
                    if user.last_daily_ts and (now - user.last_daily_ts).total_seconds() < 86400:
                        remaining = 86400 - int((now - user.last_daily_ts).total_seconds())
                        hours = remaining // 3600
                        minutes = (remaining % 3600) // 60
                        await i.response.edit_message(
                            content=f"❌ До следующего /daily осталось {hours}ч {minutes}м.\n💡 Попробуйте позже.",
                            embed=None,
                            view=None,
                        )
                        return
                    base_income = int(user.level * 500 * guild.server_rate)
                    multiplier = get_role_multiplier(interaction.user)
                    final_income = int(base_income * multiplier)
                    if user.voice_join_ts and (now - user.voice_join_ts).total_seconds() >= 10800:
                        final_income = int(final_income * 0.7)
                    user.daily_income = final_income
                    user.last_daily_ts = now
                    await EconomyService(session).daily_reward(interaction.guild.id, interaction.user.id, final_income)
                    session.add(ModLog(guild_id=interaction.guild.id, action="economy_daily", moderator_id=interaction.user.id, user_id=interaction.user.id, reason=f"+{final_income}"))
            await i.response.edit_message(content=f"✅ Вы получили {final_income} {guild.currency_name}.", embed=None, view=None)

        view = ConfirmView(author_id=interaction.user.id, on_confirm=_confirm)
        embed = EmbedFactory.warn("Подтверждение daily", "Получить ежедневную награду сейчас?")
        EmbedFactory.add_section(embed, "💡", "Что дальше", ["Нажмите «Подтвердить» для начисления."])
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="transfer", description="Перевести валюту")
    async def transfer(self, interaction: discord.Interaction, member: discord.Member, amount: int | None = None) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        if amount is None:
            await interaction.response.send_modal(TransferAmountModal(self, interaction, member))
            return
        await self._run_transfer(interaction, member, amount)

    async def _run_transfer(self, interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        if amount <= 0:
            await reply_error(interaction, "Сумма должна быть больше 0.", "Укажите положительное число.")
            return
        async with self.bot.db.session() as session:
            async with session.begin():
                sender = await get_or_create_user_locked(session, interaction.guild.id, interaction.user.id)
                await get_or_create_user_locked(session, interaction.guild.id, member.id)
                guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
                settings = parse_settings(guild.settings)
                fee_percent = float(settings.get("transfer_fee_percent", 0.02))
                max_transfer = int(settings.get("transfer_max", 100000))
                confirm_threshold = int(settings.get("transfer_confirm_threshold", 10000))
                if amount > max_transfer:
                    await reply_error(interaction, "Сумма превышает лимит перевода.", "Уменьшите сумму и попробуйте снова.")
                    return
                fee = int(amount * fee_percent)
                total = amount + fee
                if sender.balance < total:
                    await reply_error(interaction, f"Недостаточно средств: нужно {total}, доступно {sender.balance}.")
                    return

        async def _execute_transfer(i: discord.Interaction) -> None:
            async with self.bot.db.session() as session:
                async with session.begin():
                    economy = EconomyService(session)
                    await economy.transfer(interaction.guild.id, interaction.user.id, member.id, amount, source="transfer")
                    if fee > 0:
                        await economy.debit(interaction.guild.id, interaction.user.id, fee, "transfer_fee", {"recipient_user_id": member.id}, ledger_type="spend")
                    session.add(ModLog(guild_id=interaction.guild.id, action="economy_transfer", moderator_id=interaction.user.id, user_id=member.id, reason=f"{amount}"))
            await i.response.edit_message(content=f"✅ Перевод: {amount} {guild.currency_name}. Комиссия: {fee}. Итого списано: {total}.", embed=None, view=None)

        if amount >= confirm_threshold:
            embed = EmbedFactory.warn("Подтверждение перевода", f"Получатель: {member.mention}")
            EmbedFactory.add_kv(embed, "💸 Сумма", f"{amount} {guild.currency_name}")
            EmbedFactory.add_kv(embed, "🧾 Комиссия", str(fee))
            EmbedFactory.add_kv(embed, "📉 Итого", str(total))
            view = ConfirmView(author_id=interaction.user.id, on_confirm=_execute_transfer)
            if interaction.response.is_done():
                msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                view.message = msg
            else:
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                view.message = await interaction.original_response()
            return

        async with self.bot.db.session() as session:
            async with session.begin():
                economy = EconomyService(session)
                await economy.transfer(interaction.guild.id, interaction.user.id, member.id, amount, source="transfer")
                if fee > 0:
                    await economy.debit(interaction.guild.id, interaction.user.id, fee, "transfer_fee", {"recipient_user_id": member.id}, ledger_type="spend")
                session.add(ModLog(guild_id=interaction.guild.id, action="economy_transfer", moderator_id=interaction.user.id, user_id=member.id, reason=f"{amount}"))
        await reply_success(interaction, f"Перевод выполнен: {amount} {guild.currency_name} (комиссия {fee}, итого {total}).")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCog(bot))
