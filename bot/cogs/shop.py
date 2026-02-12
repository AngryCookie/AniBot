from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from bot.cogs.utils import get_or_create_guild
from bot.database.models import ModLog, ShopItem, ShopPurchase, ShopPurchaseLog, UserBuff
from bot.database.operations import get_or_create_user_locked
from bot.services.buffs import BuffService
from bot.services.economy import EconomyService
from bot.ui import AmountModal, ConfirmView, EmbedFactory, PaginationView, reply_error

BUFF_TYPE_LABELS = {
    "jobs_bonus": "+% к награде за работу",
    "xp_bonus": "+% к получаемому XP",
    "fee_reduction_pvp": "-% комиссии PvP",
    "fee_reduction_betting": "-% комиссии ставок",
}


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
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await reply_error(interaction, "Эта покупка открыта другим пользователем.", "Запустите /shop buy от своего аккаунта.")
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
            await reply_error(interaction, f"Не хватает {abs(balance_after)} {self.currency_name}.", "Уменьшите количество или пополните баланс.")
            return

        embed = EmbedFactory.warn("Подтверждение покупки", f"Товар: **{self.item.name}**")
        EmbedFactory.add_kv(embed, "📦 Кол-во", str(qty))
        EmbedFactory.add_kv(embed, "💰 Цена за 1", f"{self.unit_price} {self.currency_name}")
        EmbedFactory.add_kv(embed, "🧾 Итого", f"{total_price} {self.currency_name}")
        EmbedFactory.add_kv(embed, "📉 Баланс после", str(balance_after), inline=False)

        async def _confirm(i: discord.Interaction) -> None:
            now = dt.datetime.utcnow()
            active_summary: str | None = None
            async with self.cog.bot.db.session() as session:
                async with session.begin():
                    result = await session.execute(
                        select(ShopItem)
                        .where(
                            ShopItem.id == self.item.id,
                            ShopItem.guild_id == interaction.guild.id,
                            ShopItem.is_active.is_(True),
                            ShopItem.enabled.is_(True),
                        )
                        .with_for_update()
                    )
                    item = result.scalars().first()
                    if item is None:
                        raise ValueError("Товар недоступен для покупки.")

                    if item.purchase_limit_total is not None:
                        total_bought = await session.scalar(
                            select(func.coalesce(func.sum(ShopPurchaseLog.quantity), 0)).where(
                                ShopPurchaseLog.guild_id == interaction.guild.id,
                                ShopPurchaseLog.item_id == item.id,
                            )
                        )
                        if int(total_bought or 0) + qty > int(item.purchase_limit_total):
                            raise ValueError("Достигнут общий лимит покупок этого предмета.")

                    if item.purchase_limit_per_user is not None:
                        user_bought = await session.scalar(
                            select(func.coalesce(func.sum(ShopPurchaseLog.quantity), 0)).where(
                                ShopPurchaseLog.guild_id == interaction.guild.id,
                                ShopPurchaseLog.item_id == item.id,
                                ShopPurchaseLog.user_id == interaction.user.id,
                            )
                        )
                        if int(user_bought or 0) + qty > int(item.purchase_limit_per_user):
                            raise ValueError("Вы достигли личного лимита покупок этого предмета.")

                    await EconomyService(session).shop_purchase(
                        guild_id=interaction.guild.id,
                        user_id=interaction.user.id,
                        amount=total_price,
                        source="shop_purchase",
                        reference_id=item.id,
                        metadata={"item_name": item.name, "qty": qty},
                    )
                    session.add(ShopPurchase(guild_id=interaction.guild.id, user_id=interaction.user.id, item_id=item.id, price=total_price))
                    session.add(ShopPurchaseLog(guild_id=interaction.guild.id, user_id=interaction.user.id, item_id=item.id, quantity=qty, total_price=total_price, purchased_at=now))

                    if item.item_type == "buff":
                        buff_data = item.buff_json or {}
                        buff_type = str(buff_data.get("buff_type") or "")
                        value_percent = float(buff_data.get("value_percent") or 0)
                        duration = int(item.duration_seconds or 0)
                        if not buff_type or duration <= 0:
                            raise ValueError("У предмета-баффа не настроены buff_type/duration.")

                        max_active = int(item.max_active_per_user or 1)
                        current_active = (
                            await session.execute(
                                select(UserBuff)
                                .where(
                                    UserBuff.guild_id == interaction.guild.id,
                                    UserBuff.user_id == interaction.user.id,
                                    UserBuff.item_id == item.id,
                                    UserBuff.active.is_(True),
                                    UserBuff.ends_at > now,
                                )
                                .order_by(UserBuff.ends_at.desc(), UserBuff.id.desc())
                            )
                        ).scalars().all()

                        total_duration = dt.timedelta(seconds=duration * qty)
                        if current_active:
                            target = current_active[0]
                            target.ends_at = max(target.ends_at, now) + total_duration
                            for extra in current_active[1:]:
                                extra.active = False
                            ends_at = target.ends_at
                        elif max_active <= 1 or len(current_active) < max_active:
                            ends_at = now + total_duration
                            session.add(
                                UserBuff(
                                    guild_id=interaction.guild.id,
                                    user_id=interaction.user.id,
                                    item_id=item.id,
                                    buff_type=buff_type,
                                    value_percent=value_percent,
                                    starts_at=now,
                                    ends_at=ends_at,
                                    active=True,
                                    metadata_json={"item_name": item.name, "qty": qty},
                                )
                            )
                        else:
                            raise ValueError("Достигнут лимит одновременно активных баффов этого предмета.")

                        active_summary = f"{BUFF_TYPE_LABELS.get(buff_type, buff_type)}: **{value_percent:.0f}%** до {ends_at:%Y-%m-%d %H:%M UTC}"

                    session.add(ModLog(guild_id=interaction.guild.id, action="shop_purchase", moderator_id=interaction.user.id, user_id=interaction.user.id, reason=f"{item.name}x{qty} ({total_price})"))

            success_embed = EmbedFactory.success("✅ Покупка успешна", f"{self.item.name} x{qty}")
            EmbedFactory.add_kv(success_embed, "💰 Списано", f"{total_price} {self.currency_name}")
            if active_summary:
                EmbedFactory.add_kv(success_embed, "✨ Активный бафф", active_summary, inline=False)
            await i.response.edit_message(content=None, embed=success_embed, view=None)

        view = ConfirmView(author_id=self.author_id, on_confirm=_confirm)
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        view.message = msg


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return "—"
    hours = seconds // 3600
    days, rest_hours = divmod(hours, 24)
    if days > 0:
        return f"{days}д {rest_hours}ч"
    return f"{hours}ч"


class ShopGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="shop", description="Магазин")
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.shop_list(interaction)

    @app_commands.command(name="list", description="Список товаров")
    async def shop_list(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            rows = await session.execute(select(ShopItem).where((ShopItem.guild_id == interaction.guild.id) & (ShopItem.is_active.is_(True)) & (ShopItem.enabled.is_(True))))
            items = rows.scalars().all()
        if not items:
            await reply_error(interaction, "Магазин пуст.", "Добавьте товары через админ-инструменты.")
            return

        pages: list[discord.Embed] = []
        for idx in range(0, len(items), 5):
            embed = EmbedFactory.info("Магазин", "Листайте страницы или используйте /shop buy.")
            for item in items[idx : idx + 5]:
                price = int(item.base_price * guild.server_rate)
                if item.item_type == "buff":
                    buff = item.buff_json or {}
                    effect = f"+{float(buff.get('value_percent') or 0):.0f}% {BUFF_TYPE_LABELS.get(str(buff.get('buff_type') or ''), str(buff.get('buff_type') or 'эффект'))}"
                    details = f"{price} {guild.currency_name}\n⏳ Длительность: {_format_duration(item.duration_seconds)}\n✨ Эффект: {effect}"
                else:
                    details = f"{price} {guild.currency_name} • {item.item_type}"
                EmbedFactory.add_kv(embed, f"🧩 {item.name}", details, inline=False)
            pages.append(embed)
        view = PaginationView(author_id=interaction.user.id, pages=pages)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="info", description="Информация о товаре")
    async def shop_info(self, interaction: discord.Interaction, name: str) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            item_result = await session.execute(select(ShopItem).where((ShopItem.guild_id == interaction.guild.id) & (ShopItem.name == name) & (ShopItem.is_active.is_(True)) & (ShopItem.enabled.is_(True))))
            item = item_result.scalars().first()
        if not item:
            await reply_error(interaction, "Товар не найден.", "Проверьте название или откройте /shop list.")
            return
        price = int(item.base_price * guild.server_rate)
        embed = EmbedFactory.info(item.name, item.description or "Без описания")
        EmbedFactory.add_kv(embed, "💰 Цена", f"{price} {guild.currency_name}")
        EmbedFactory.add_kv(embed, "🏷️ Тип", item.item_type)
        if item.item_type == "buff":
            buff = item.buff_json or {}
            buff_type = str(buff.get("buff_type") or "")
            value = float(buff.get("value_percent") or 0)
            EmbedFactory.add_kv(embed, "⏳ Длительность", _format_duration(item.duration_seconds))
            EmbedFactory.add_kv(embed, "✨ Эффект", f"+{value:.0f}% {BUFF_TYPE_LABELS.get(buff_type, buff_type)}", inline=False)
        view = ShopBuyView(self, item, guild.currency_name, price, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="buy", description="Купить товар")
    async def shop_buy(self, interaction: discord.Interaction, name: str) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            item_result = await session.execute(select(ShopItem).where((ShopItem.guild_id == interaction.guild.id) & (ShopItem.name == name) & (ShopItem.is_active.is_(True)) & (ShopItem.enabled.is_(True))))
            item = item_result.scalars().first()
        if not item:
            await reply_error(interaction, "Товар не найден.", "Проверьте название или откройте /shop list.")
            return
        price = int(item.base_price * guild.server_rate)
        embed = EmbedFactory.info("Покупка", f"{item.name} — {price} {guild.currency_name}")
        EmbedFactory.add_section(embed, "💡", "Что дальше", ["Нажмите «Купить», затем укажите количество."])
        view = ShopBuyView(self, item, guild.currency_name, price, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = ShopGroup(bot)
        self.bot.tree.add_command(self.group)

    @app_commands.command(name="buffs", description="Показать активные баффы")
    async def buffs(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            service = BuffService(session)
            active = await service.list_active_buffs(interaction.guild.id, interaction.user.id)

        if not active:
            await reply_error(interaction, "У вас нет активных баффов.", "Купите буст через /shop list.")
            return

        pages: list[discord.Embed] = []
        now = dt.datetime.utcnow()
        for idx in range(0, len(active), 5):
            embed = EmbedFactory.info("Активные баффы", "Ваши временные эффекты")
            for buff in active[idx : idx + 5]:
                left = max(0, int((buff.ends_at - now).total_seconds()))
                hours = left // 3600
                minutes = (left % 3600) // 60
                EmbedFactory.add_kv(
                    embed,
                    f"✨ {BUFF_TYPE_LABELS.get(buff.buff_type, buff.buff_type)}",
                    f"+{buff.value_percent:.0f}% • осталось {hours}ч {minutes}м",
                    inline=False,
                )
            pages.append(embed)

        view = PaginationView(author_id=interaction.user.id, pages=pages)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShopCog(bot))
