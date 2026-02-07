from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.cogs.utils import get_or_create_guild
from bot.database.models import ModLog, ShopItem, ShopPurchase
from bot.database.operations import apply_balance_change, get_or_create_user_locked


class ShopGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="shop", description="Магазин")
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.shop_list(interaction)

    @app_commands.command(name="list", description="Список товаров")
    async def shop_list(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            items = await session.execute(
                select(ShopItem).where(
                    (ShopItem.guild_id == interaction.guild.id) & (ShopItem.is_active.is_(True))
                )
            )
            items = items.scalars().all()
        if not items:
            await interaction.response.send_message("Магазин пуст.", ephemeral=True)
            return
        embed = discord.Embed(title="Магазин", color=discord.Color.blue())
        for item in items:
            price = int(item.base_price * guild.server_rate)
            embed.add_field(
                name=item.name,
                value=f"Цена: {price} {guild.currency_name}\nТип: {item.item_type}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="info", description="Информация о товаре")
    async def shop_info(self, interaction: discord.Interaction, name: str) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            item_result = await session.execute(
                select(ShopItem).where(
                    (ShopItem.guild_id == interaction.guild.id)
                    & (ShopItem.name == name)
                    & (ShopItem.is_active.is_(True))
                )
            )
            item = item_result.scalars().first()
        if not item:
            await interaction.response.send_message("Товар не найден.", ephemeral=True)
            return
        price = int(item.base_price * guild.server_rate)
        embed = discord.Embed(title=item.name, description=item.description, color=discord.Color.blue())
        embed.add_field(name="Цена", value=f"{price} {guild.currency_name}")
        embed.add_field(name="Тип", value=item.item_type)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="buy", description="Купить товар")
    async def shop_buy(self, interaction: discord.Interaction, name: str) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            async with session.begin():
                guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
                _ = await get_or_create_user_locked(session, interaction.guild.id, interaction.user.id)
                item_result = await session.execute(
                    select(ShopItem).where(
                        (ShopItem.guild_id == interaction.guild.id)
                        & (ShopItem.name == name)
                        & (ShopItem.is_active.is_(True))
                    )
                )
                item = item_result.scalars().first()
                if not item:
                    await interaction.response.send_message("Товар не найден.", ephemeral=True)
                    return
                price = int(item.base_price * guild.server_rate)
                try:
                    await apply_balance_change(
                        session,
                        guild_id=interaction.guild.id,
                        user_id=interaction.user.id,
                        amount=-price,
                        ledger_type="spend",
                        source="shop_purchase",
                    )
                except ValueError:
                    await interaction.response.send_message("Недостаточно средств.", ephemeral=True)
                    return
                purchase = ShopPurchase(
                    guild_id=interaction.guild.id,
                    user_id=interaction.user.id,
                    item_id=item.id,
                    price=price,
                )
                session.add(purchase)
                session.add(
                    ModLog(
                        guild_id=interaction.guild.id,
                        action="shop_purchase",
                        moderator_id=interaction.user.id,
                        user_id=interaction.user.id,
                        reason=f"{item.name} ({price})",
                    )
                )
        if item.item_type == "role" and item.role_id:
            role = interaction.guild.get_role(item.role_id)
            if role:
                await interaction.user.add_roles(role, reason="Shop purchase")
        await interaction.response.send_message(
            f"Покупка {item.name} успешна за {price} {guild.currency_name}.",
            ephemeral=True,
        )


class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(ShopGroup(bot))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShopCog(bot))
