from __future__ import annotations
import datetime as dt
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from bot.database.models import ModLog, TavernItem
from bot.pvp.seasons import PvpSeasonService
from bot.services.pvp import PvpService
from bot.services.tavern import TavernService
from bot.ui import AmountModal, ConfirmView, EmbedFactory, map_exception_message, reply_error
class PvpAmountModal(AmountModal):
    def __init__(self, cog: "PvpCog", base_interaction: discord.Interaction, user: discord.Member):
        super().__init__(min_amount=1)
        self.cog = cog
        self.base = base_interaction
        self.user = user
    async def on_submit(self, interaction: discord.Interaction) -> None:
        await super().on_submit(interaction)
        if self.value is None:
            return
        await self.cog._start_duel(self.base, self.user, self.value)
class PvpChallengeView(discord.ui.View):
    def __init__(self, cog: "PvpCog", duel_id: int, challenger_id: int, opponent_id: int, amount: int, fee_percent: float) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.duel_id = duel_id
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id
        self.amount = amount
        self.fee_percent = fee_percent
        self.message: discord.Message | None = None
    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent_id:
            await reply_error(interaction, "Только оппонент может принять дуэль.")
            return
        async def _confirm(i: discord.Interaction) -> None:
            async with self.cog.bot.db.session() as session:
                try:
                    async with session.begin():
                        service = PvpService(session)
                        duel = await service.accept_duel(interaction.guild.id, self.duel_id, interaction.user.id)
                        resolved = await service.resolve_duel(interaction.guild.id, duel.id)
                        session.add(ModLog(guild_id=interaction.guild.id, action="pvp_resolve", moderator_id=interaction.user.id, user_id=resolved.winner_id, reason=f"duel={resolved.id};amount={resolved.amount}"))
                except Exception as exc:
                    message, hint = map_exception_message(exc)
                    await i.response.edit_message(content=f"❌ {message}\n💡 {hint}", embed=None, view=None)
                    return
            payout = int(resolved.amount) * 2 - int(int(resolved.amount) * 2 * float(resolved.fee_percent) / 100.0)
            embed = EmbedFactory.success("PvP дуэль завершена")
            EmbedFactory.add_kv(embed, "🏆 Победитель", f"<@{resolved.winner_id}>" if resolved.winner_id else "—", inline=False)
            EmbedFactory.add_kv(embed, "💰 Ставка", str(resolved.amount))
            EmbedFactory.add_kv(embed, "🧾 Комиссия", f"{resolved.fee_percent:.2f}%")
            EmbedFactory.add_kv(embed, "🎁 Выплата", str(payout), inline=False)
            await i.response.edit_message(embed=embed, view=None)
        hint = int(self.amount * 2 * self.fee_percent / 100.0)
        embed = EmbedFactory.warn("Подтверждение принятия дуэли", "Проверьте условия перед стартом боя.")
        EmbedFactory.add_kv(embed, "💰 Ставка", str(self.amount))
        EmbedFactory.add_kv(embed, "🧾 Комиссия", f"{self.fee_percent:.2f}% ({hint})")
        EmbedFactory.add_kv(embed, "🎲 Шанс победы", "50/50", inline=False)
        view = ConfirmView(author_id=interaction.user.id, on_confirm=_confirm)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent_id:
            await reply_error(interaction, "Только оппонент может отклонить дуэль.")
            return
        async with self.cog.bot.db.session() as session:
            async with session.begin():
                service = PvpService(session)
                await service.decline_duel(interaction.guild.id, self.duel_id, interaction.user.id)
        embed = EmbedFactory.error("Дуэль отклонена", f"<@{self.opponent_id}> отклонил вызов.")
        await interaction.response.edit_message(embed=embed, view=None)
class TavernView(discord.ui.View):
    def __init__(self, cog: "PvpCog", guild_id: int, user_id: int) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if getattr(self, "message", None):
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await reply_error(interaction, "Это меню не для вас.")
            return False
        return True

    @discord.ui.button(label="🛒 Магазин", style=discord.ButtonStyle.secondary)
    async def shop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog._open_tavern_slot_picker(interaction)

    @discord.ui.button(label="🗡 Выбрать Attack", style=discord.ButtonStyle.primary)
    async def attack_slot(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog._open_tavern_shop(interaction, slot_type="attack")

    @discord.ui.button(label="🛡 Выбрать Defense", style=discord.ButtonStyle.primary)
    async def defense_slot(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog._open_tavern_shop(interaction, slot_type="defense")

    @discord.ui.button(label="❌ Снять Attack", style=discord.ButtonStyle.danger)
    async def remove_attack(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog._confirm_unequip(interaction, "attack")

    @discord.ui.button(label="❌ Снять Defense", style=discord.ButtonStyle.danger)
    async def remove_defense(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog._confirm_unequip(interaction, "defense")


class PvpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
    @app_commands.command(name="pvp", description="Вызвать пользователя на PvP-дуэль на монеты")
    async def pvp(self, interaction: discord.Interaction, user: discord.Member, amount: int | None = None) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        if amount is None:
            await interaction.response.send_modal(PvpAmountModal(self, interaction, user))
            return
        await self._start_duel(interaction, user, amount)
    async def _start_duel(self, interaction: discord.Interaction, user: discord.Member, amount: int) -> None:
        async with self.bot.db.session() as session:
            try:
                async with session.begin():
                    service = PvpService(session)
                    settings = await self._get_pvp_settings(session, interaction.guild.id)
                    duel = await service.create_duel(interaction.guild.id, interaction.user.id, user.id, amount, float(settings.get("fee_percent", 5.0)))
                    session.add(ModLog(guild_id=interaction.guild.id, action="pvp_challenge", moderator_id=interaction.user.id, user_id=user.id, reason=f"duel={duel.id};amount={amount}"))
            except Exception as exc:
                message, hint = map_exception_message(exc)
                await reply_error(interaction, message, hint)
                return
        view = PvpChallengeView(self, duel.id, interaction.user.id, user.id, amount, duel.fee_percent)
        embed = EmbedFactory.info("PvP вызов", f"{interaction.user.mention} вызывает {user.mention}.")
        EmbedFactory.add_kv(embed, "💰 Ставка", str(amount))
        EmbedFactory.add_kv(embed, "🧾 Комиссия", f"{duel.fee_percent:.2f}%")
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view)
            view.message = msg
        else:
            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()
    @app_commands.command(name="pvp-top", description="Топ игроков PvP по рейтингу")
    async def pvp_top(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            service = PvpService(session)
            season_service = PvpSeasonService(session, self.bot)
            season = await season_service.get_or_create_active_season(interaction.guild.id, dt.datetime.utcnow())
            top_players = await service.get_top_players(interaction.guild.id, limit=10)
        if not top_players:
            await reply_error(interaction, "Пока нет PvP-статистики.")
            return
        embed = EmbedFactory.success("PvP рейтинг")
        embed.description = "\n".join([f"**{i}.** <@{p.user_id}> — R{p.rating} | W/L: {p.wins}/{p.losses}" for i, p in enumerate(top_players, 1)])
        EmbedFactory.add_kv(embed, "🗓️ Сезон", f"#{season.season_number}: {season.starts_at:%d.%m} - {season.ends_at:%d.%m}", inline=False)
        await interaction.response.send_message(embed=embed)
    @app_commands.command(name="pvp-stats", description="Показать PvP статистику игрока")
    async def pvp_stats(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        target = user or interaction.user
        async with self.bot.db.session() as session:
            service = PvpService(session)
            season_service = PvpSeasonService(session, self.bot)
            season = await season_service.get_or_create_active_season(interaction.guild.id, dt.datetime.utcnow())
            stats = await service.get_user_stats(interaction.guild.id, target.id)
        total_duels = int(stats.wins or 0) + int(stats.losses or 0)
        winrate = (int(stats.wins or 0) / total_duels * 100.0) if total_duels > 0 else 0.0
        embed = EmbedFactory.info("PvP статистика", f"Игрок: {target.mention}")
        EmbedFactory.add_kv(embed, "⭐ Рейтинг", str(stats.rating))
        EmbedFactory.add_kv(embed, "⚔️ W/L", f"{stats.wins}/{stats.losses}")
        EmbedFactory.add_kv(embed, "📈 Винрейт", f"{winrate:.1f}%")
        EmbedFactory.add_kv(embed, "🗓️ Сезон", f"#{season.season_number}: {season.starts_at:%d.%m.%Y} - {season.ends_at:%d.%m.%Y}", inline=False)
        await interaction.response.send_message(embed=embed)
    @app_commands.command(name="pvp_season", description="Текущий PvP сезон и предварительный топ")
    async def pvp_season(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            service = PvpService(session)
            season_service = PvpSeasonService(session, self.bot)
            season = await season_service.get_or_create_active_season(interaction.guild.id, dt.datetime.utcnow())
            top_players = await service.get_top_players(interaction.guild.id, limit=10)
        embed = EmbedFactory.info(f"PvP сезон #{season.season_number}")
        EmbedFactory.add_kv(embed, "🕒 Начало", season.starts_at.strftime("%d.%m.%Y %H:%M UTC"))
        EmbedFactory.add_kv(embed, "🏁 Окончание", season.ends_at.strftime("%d.%m.%Y %H:%M UTC"))
        EmbedFactory.add_kv(
            embed,
            "🏆 Топ-10",
            "\n".join([f"**{idx}.** <@{p.user_id}> — R{p.rating}" for idx, p in enumerate(top_players, 1)]) if top_players else "Пока нет данных.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)
    @app_commands.command(name="pvp_season_top", description="Топ-10 игроков текущего PvP сезона")
    async def pvp_season_top(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            service = PvpService(session)
            top_players = await service.get_top_players(interaction.guild.id, limit=10)
        if not top_players:
            await reply_error(interaction, "За текущий сезон нет статистики.")
            return
        embed = EmbedFactory.success("Топ-10 сезона PvP")
        embed.description = "\n".join(
            [f"**{index}.** <@{p.user_id}> — R{p.rating} | W/L: {p.wins}/{p.losses} | Профит: {p.total_profit}" for index, p in enumerate(top_players, 1)]
        )
        await interaction.response.send_message(embed=embed)
    async def _get_pvp_settings(self, session, guild_id: int) -> dict:
        return await PvpService(session).get_pvp_settings(guild_id)
    @app_commands.command(name="tavern", description="PvP таверна: баффы Attack/Defense")
    async def tavern(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            service = TavernService(session)
            settings = await service.get_tavern_settings(interaction.guild.id)
            if not settings.get("enabled", True):
                await reply_error(interaction, "Таверна отключена администратором.")
                return
            embed = await self._build_tavern_embed(session, interaction.guild.id, interaction.user.id, settings)
            view = TavernView(self, interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
    @app_commands.command(name="tavern_remove", description="Снять предмет таверны из слота")
    @app_commands.describe(slot="attack или defense")
    async def tavern_remove(self, interaction: discord.Interaction, slot: str) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        async with self.bot.db.session() as session:
            async with session.begin():
                await TavernService(session).unequip_slot(
                    guild_id=interaction.guild.id,
                    user_id=interaction.user.id,
                    slot_type=slot,
                )
        await interaction.response.send_message(
            embed=EmbedFactory.success("Слот очищен", f"Слот **{slot}** очищен."),
            ephemeral=True,
        )

    async def _build_tavern_embed(self, session, guild_id: int, user_id: int, settings: dict | None = None) -> discord.Embed:
        service = TavernService(session)
        settings = settings or await service.get_tavern_settings(guild_id)
        loadout = await service.get_or_create_loadout(guild_id, user_id)
        now = dt.datetime.utcnow()

        attack_item = await session.get(TavernItem, int(loadout.attack_item_id)) if loadout.attack_item_id else None
        defense_item = await session.get(TavernItem, int(loadout.defense_item_id)) if loadout.defense_item_id else None

        def _fmt(item: TavernItem | None, ends_at: dt.datetime | None) -> str:
            if not item or not ends_at or ends_at <= now:
                return "Пусто"
            left = int((ends_at - now).total_seconds())
            hours = max(0, left // 3600)
            mins = max(0, (left % 3600) // 60)
            return f"**{item.name}** • {item.effect_type}: {item.value} • осталось {hours}ч {mins}м"

        caps = settings.get("max_bonus_caps", {}) if isinstance(settings, dict) else {}
        info = (
            f"📌 Правила: берём {str(settings.get('stacking_rule', 'max')).upper()} бонус по типу • "
            f"Капы: атака {caps.get('attack_bonus_percent', 15)}%, защита {caps.get('defense_bonus_percent', 15)}%, "
            f"crit {caps.get('crit_chance_percent', 5)}%, dodge {caps.get('dodge_chance_percent', 5)}%"
        )
        embed = EmbedFactory.info("Таверна PvP", info)
        EmbedFactory.add_kv(embed, "🗡 Attack", _fmt(attack_item, loadout.attack_ends_at), inline=False)
        EmbedFactory.add_kv(embed, "🛡 Defense", _fmt(defense_item, loadout.defense_ends_at), inline=False)
        return embed

    async def _confirm_unequip(self, interaction: discord.Interaction, slot_type: str) -> None:
        async def _confirm(i: discord.Interaction) -> None:
            async with self.bot.db.session() as session:
                async with session.begin():
                    await TavernService(session).unequip_slot(
                        guild_id=interaction.guild.id,
                        user_id=interaction.user.id,
                        slot_type=slot_type,
                    )
                    embed = await self._build_tavern_embed(session, interaction.guild.id, interaction.user.id)
            await i.response.edit_message(embed=embed, view=None)

        view = ConfirmView(author_id=interaction.user.id, on_confirm=_confirm)
        await interaction.response.send_message(
            embed=EmbedFactory.warn("Подтверждение", f"Снять предмет из слота **{slot_type}**?"),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    async def _open_tavern_slot_picker(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=EmbedFactory.info("Магазин таверны", "Сначала выберите слот: 🗡 Attack или 🛡 Defense."),
            ephemeral=True,
        )

    async def _open_tavern_shop(self, interaction: discord.Interaction, slot_type: str | None) -> None:
        if not interaction.guild:
            await reply_error(interaction, "Команда доступна только на сервере.")
            return
        if slot_type not in {"attack", "defense"}:
            await reply_error(interaction, "Сначала выберите слот Attack/Defense.")
            return
        async with self.bot.db.session() as session:
            result = await session.execute(
                select(TavernItem).where(
                    TavernItem.guild_id == interaction.guild.id,
                    TavernItem.enabled.is_(True),
                    TavernItem.slot_type == slot_type,
                ).order_by(TavernItem.price.asc(), TavernItem.id.asc())
            )
            items = list(result.scalars().all())
        if not items:
            await reply_error(interaction, "Нет доступных предметов в этом слоте.")
            return

        first = items[0]
        lines = [f"**{it.id}.** {it.name} • {it.effect_type} {it.value} • {it.price}" for it in items[:25]]
        embed = EmbedFactory.info(f"Магазин Tavern • {slot_type.title()}", "\n".join(lines))
        EmbedFactory.add_kv(embed, "Выбран предмет", f"{first.name} ({first.effect_type} {first.value})", inline=False)

        async def _confirm(i: discord.Interaction) -> None:
            async with self.bot.db.session() as session:
                try:
                    async with session.begin():
                        loadout = await TavernService(session).purchase_item(
                            guild_id=interaction.guild.id,
                            user_id=interaction.user.id,
                            item_id=int(first.id),
                        )
                except Exception as exc:
                    message, hint = map_exception_message(exc)
                    await i.response.edit_message(content=f"❌ {message}\n💡 {hint}", embed=None, view=None)
                    return
            ends_at = loadout.attack_ends_at if slot_type == "attack" else loadout.defense_ends_at
            left = int((ends_at - dt.datetime.utcnow()).total_seconds()) if ends_at else 0
            await i.response.edit_message(
                embed=EmbedFactory.success("✅ Куплено и экипировано", f"{first.name} • осталось ~{max(0, left // 60)}м"),
                view=None,
            )

        view = ConfirmView(author_id=interaction.user.id, on_confirm=_confirm)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PvpCog(bot))
