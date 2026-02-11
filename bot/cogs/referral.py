from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from bot.cogs.utils import get_or_create_guild
from bot.database.models import ReferralCode, ReferralUsage
from bot.services.referral import ReferralService


class ReferralGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="referral", description="Реферальная система")
        self.bot = bot

    @app_commands.command(name="create", description="Создать персональный реферальный код")
    async def create(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        async with self.bot.db.session() as session:
            async with session.begin():
                guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
                service = ReferralService(session)
                code = await service.create_referral_code(
                    guild_id=interaction.guild.id,
                    inviter_user_id=interaction.user.id,
                    reward_amount=500,
                )

        embed = discord.Embed(title="Реферальный код создан", color=discord.Color.green())
        embed.add_field(name="Код", value=f"`{code.code}`", inline=False)
        embed.add_field(name="Награда", value=f"{code.reward_amount} {guild.currency_name}", inline=True)
        embed.add_field(
            name="Лимит",
            value=str(code.max_uses) if code.max_uses is not None else "Без лимита",
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="redeem", description="Активировать реферальный код")
    async def redeem(self, interaction: discord.Interaction, code: str) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        async with self.bot.db.session() as session:
            async with session.begin():
                guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
                code_row = await session.execute(
                    select(ReferralCode).where(
                        ReferralCode.guild_id == interaction.guild.id,
                        ReferralCode.code == code.strip().upper(),
                    )
                )
                referral_code = code_row.scalars().first()
                if referral_code is None or not referral_code.creator_user_id:
                    await interaction.response.send_message("Реферальный код не найден.", ephemeral=True)
                    return

                service = ReferralService(session)
                try:
                    result = await service.redeem_code(
                        guild_id=interaction.guild.id,
                        inviter_user_id=int(referral_code.creator_user_id),
                        invited_user_id=interaction.user.id,
                        code=code,
                    )
                except ValueError as exc:
                    await interaction.response.send_message(str(exc), ephemeral=True)
                    return

        embed = discord.Embed(title="Код активирован", color=discord.Color.blurple())
        embed.add_field(name="Код", value=f"`{result.code}`", inline=True)
        embed.add_field(
            name="Ваша награда",
            value=f"+{result.invited_reward} {guild.currency_name}",
            inline=True,
        )
        embed.add_field(name="Использований", value=str(result.current_uses), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="stats", description="Показать реферальную статистику")
    async def stats(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            invited_count = await session.scalar(
                select(func.count())
                .select_from(ReferralUsage)
                .where(
                    ReferralUsage.guild_id == interaction.guild.id,
                    ReferralUsage.inviter_user_id == interaction.user.id,
                )
            )
            earned_total = await session.scalar(
                select(func.coalesce(func.sum(ReferralUsage.reward_amount), 0)).where(
                    ReferralUsage.guild_id == interaction.guild.id,
                    ReferralUsage.inviter_user_id == interaction.user.id,
                )
            )

        embed = discord.Embed(title="Реферальная статистика", color=discord.Color.blue())
        embed.add_field(name="Приглашено", value=str(int(invited_count or 0)), inline=True)
        embed.add_field(
            name="Награды получено",
            value=f"{int(earned_total or 0)} {guild.currency_name}",
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ReferralCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(ReferralGroup(bot))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReferralCog(bot))
