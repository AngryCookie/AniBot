from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.cogs.utils import get_or_create_guild
from bot.database.models import ModLog, ShopItem, ShopPurchase
from bot.database.operations import get_or_create_user_locked
from bot.services.economy import EconomyService
from bot.ui import AmountModal, ConfirmView, PaginationView, build_ux_embed


class BuyAmountModal(AmountModal):
    def __init__(self, view: "ShopBuyView") -> None:
        super().__init__(min_amount=1, max_amount=99)
        self.view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await super().on_submit(interaction)
        if self.value is None:
            return
        await self.view.preview_purchase(interaction, self.value)


class ShopBuyView(discord.ui.View):
    def __init__(self, cog: "ShopGroup", item: ShopItem, currency_name: str, unit_price: int, author_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.item = item
        self.currency_name = currency_name
        self.unit_price = unit_price
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Эта покупка открыта другим пользователем.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Купить", style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(BuyAmountModal(self))

    async def preview_purchase(self, interaction: discord.Interaction, qty: int) -> None:
        total_price = self.unit_price * qty
        async with self.cog.bot.db.session() as session:
            async with session.begin():
                user = await get_or_create_user_locked(session, interaction.guild.id, interaction.user.id)
                balance_after = user.balance - total_price
        if balance_after < 0:
            await interaction.followup.send(f"😕 Не хватает {abs(balance_after)} {self.currency_name}.", ephemeral=True)
            return

        embed = build_ux_embed(
            title="🧾 Подтверждение покупки",
            description=(
                f"Товар: **{self.item.name}**\n"
                f"Кол-во: **{qty}**\n"
                f"Цена за 1: **{self.unit_price}** {self.currency_name}\n"
                f"Скидки/курс сервера: учтены\n"
                f"Итого: **{total_price}** {self.currency_name}\n"
                f"Баланс после: **{balance_after}**"
            ),
            color=discord.Color.orange(),
            next_hint="Подтвердите списание, чтобы завершить покупку.",
        )

        async def _confirm(i: discord.Interaction) -> None:
            async with self.cog.bot.db.session() as session:
                async with session.begin():
                    await EconomyService(session).shop_purchase(
                        guild_id=interaction.guild.id,
                        user_id=interaction.user.id,
                        amount=total_price,
                        source="shop_purchase",
                        reference_id=self.item.id,
                        metadata={"item_name": self.item.name, "qty": qty},
                    )
                    session.add(ShopPurchase(guild_id=interaction.guild.id, user_id=interaction.user.id, item_id=self.item.id, price=total_price))
                    session.add(ModLog(guild_id=interaction.guild.id, action="shop_purchase", moderator_id=interaction.user.id, user_id=interaction.user.id, reason=f"{self.item.name}x{qty} ({total_price})"))
            await i.response.edit_message(content=f"✅ Покупка {self.item.name} x{qty} успешна.", embed=None, view=None)

        view = ConfirmView(author_id=self.author_id, on_confirm=_confirm)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


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
            rows = await session.execute(select(ShopItem).where((ShopItem.guild_id == interaction.guild.id) & (ShopItem.is_active.is_(True))))
            items = rows.scalars().all()
        if not items:
            await interaction.response.send_message("Магазин пуст.", ephemeral=True)
            return

        pages: list[discord.Embed] = []
        for idx in range(0, len(items), 5):
            embed = build_ux_embed(title="🛒 Магазин", color=discord.Color.blue(), next_hint="Листайте страницы или используйте /shop buy.")
            for item in items[idx : idx + 5]:
                price = int(item.base_price * guild.server_rate)
                embed.add_field(name=item.name, value=f"Цена: {price} {guild.currency_name}\nТип: {item.item_type}", inline=False)
            pages.append(embed)
        view = PaginationView(author_id=interaction.user.id, pages=pages)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="info", description="Информация о товаре")
    async def shop_info(self, interaction: discord.Interaction, name: str) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            item_result = await session.execute(select(ShopItem).where((ShopItem.guild_id == interaction.guild.id) & (ShopItem.name == name) & (ShopItem.is_active.is_(True))))
            item = item_result.scalars().first()
        if not item:
            await interaction.response.send_message("Товар не найден.", ephemeral=True)
            return
        price = int(item.base_price * guild.server_rate)
        embed = build_ux_embed(title=f"🧩 {item.name}", description=item.description or "Без описания", color=discord.Color.blue(), next_hint="Нажмите кнопку покупки ниже.")
        embed.add_field(name="Цена", value=f"{price} {guild.currency_name}")
        embed.add_field(name="Тип", value=item.item_type)
        await interaction.response.send_message(embed=embed, view=ShopBuyView(self, item, guild.currency_name, price, interaction.user.id), ephemeral=True)

    @app_commands.command(name="buy", description="Купить товар")
    async def shop_buy(self, interaction: discord.Interaction, name: str) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            item_result = await session.execute(select(ShopItem).where((ShopItem.guild_id == interaction.guild.id) & (ShopItem.name == name) & (ShopItem.is_active.is_(True))))
            item = item_result.scalars().first()
        if not item:
            await interaction.response.send_message("Товар не найден.", ephemeral=True)
            return
        price = int(item.base_price * guild.server_rate)
        embed = build_ux_embed(title="🛍️ Покупка", description=f"{item.name} — {price} {guild.currency_name}", next_hint="Нажмите «Купить», затем укажите количество.")
        await interaction.response.send_message(embed=embed, view=ShopBuyView(self, item, guild.currency_name, price, interaction.user.id), ephemeral=True)


class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(ShopGroup(bot))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShopCog(bot))
