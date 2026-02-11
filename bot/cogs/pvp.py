from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands

from bot.database.models import ModLog
from bot.pvp.seasons import PvpSeasonService
from bot.services.pvp import PvpService
from bot.ui import AmountModal, ConfirmView, build_ux_embed


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

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message("Только оппонент может принять дуэль.", ephemeral=True)
            return

        async def _confirm(i: discord.Interaction) -> None:
            async with self.cog.bot.db.session() as session:
                try:
                    async with session.begin():
                        service = PvpService(session)
                        duel = await service.accept_duel(interaction.guild.id, self.duel_id, interaction.user.id)
                        resolved = await service.resolve_duel(interaction.guild.id, duel.id)
                        session.add(ModLog(guild_id=interaction.guild.id, action="pvp_resolve", moderator_id=interaction.user.id, user_id=resolved.winner_id, reason=f"duel={resolved.id};amount={resolved.amount}"))
                except ValueError as exc:
                    await i.response.edit_message(content=str(exc), embed=None, view=None)
                    return
            payout = int(resolved.amount) * 2 - int(int(resolved.amount) * 2 * float(resolved.fee_percent) / 100.0)
            embed = build_ux_embed(title="⚔️ PvP дуэль завершена", color=discord.Color.green(), next_hint="Запустите /pvp-stats для деталей.")
            embed.add_field(name="Победитель", value=f"<@{resolved.winner_id}>" if resolved.winner_id else "—", inline=False)
            embed.add_field(name="Ставка", value=str(resolved.amount), inline=True)
            embed.add_field(name="Комиссия", value=f"{resolved.fee_percent:.2f}%", inline=True)
            embed.add_field(name="Выплата", value=str(payout), inline=False)
            await i.response.edit_message(embed=embed, view=None)

        hint = int(self.amount * 2 * self.fee_percent / 100.0)
        embed = build_ux_embed(title="Подтверждение принятия дуэли", description=f"Ставка: {self.amount}\nКомиссия: {self.fee_percent:.2f}% ({hint})\nШанс победы: 50/50", color=discord.Color.orange(), next_hint="Нажмите Подтвердить, чтобы провести бой.")
        view = ConfirmView(author_id=interaction.user.id, on_confirm=_confirm)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message("Только оппонент может отклонить дуэль.", ephemeral=True)
            return
        async with self.cog.bot.db.session() as session:
            async with session.begin():
                service = PvpService(session)
                await service.decline_duel(interaction.guild.id, self.duel_id, interaction.user.id)
        embed = build_ux_embed(title="❌ Дуэль отклонена", description=f"<@{self.opponent_id}> отклонил вызов.", color=discord.Color.red())
        await interaction.response.edit_message(embed=embed, view=None)


class PvpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="pvp", description="Вызвать пользователя на PvP-дуэль на монеты")
    async def pvp(self, interaction: discord.Interaction, user: discord.Member, amount: int | None = None) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
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
            except ValueError as exc:
                if interaction.response.is_done():
                    await interaction.followup.send(str(exc), ephemeral=True)
                else:
                    await interaction.response.send_message(str(exc), ephemeral=True)
                return
        view = PvpChallengeView(self, duel.id, interaction.user.id, user.id, amount, duel.fee_percent)
        embed = build_ux_embed(title="⚔️ PvP вызов", description=f"{interaction.user.mention} вызывает {user.mention}.", color=discord.Color.blurple(), next_hint="Оппонент должен принять или отклонить вызов.")
        embed.add_field(name="Ставка", value=str(amount), inline=True)
        embed.add_field(name="Комиссия", value=f"{duel.fee_percent:.2f}%", inline=True)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="pvp-top", description="Топ игроков PvP по рейтингу")
    async def pvp_top(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            service = PvpService(session)
            season_service = PvpSeasonService(session, self.bot)
            season = await season_service.get_or_create_active_season(interaction.guild.id, dt.datetime.utcnow())
            top_players = await service.get_top_players(interaction.guild.id, limit=10)
        if not top_players:
            await interaction.response.send_message("Пока нет PvP-статистики.", ephemeral=True)
            return
        embed = build_ux_embed(title="🏆 PvP рейтинг", color=discord.Color.gold(), next_hint="Используйте /pvp-stats для игрока.")
        embed.description = "\n".join([f"**{i}.** <@{p.user_id}> — R{p.rating} | W/L: {p.wins}/{p.losses}" for i, p in enumerate(top_players, 1)])
        embed.add_field(name="Сезон", value=f"#{season.season_number}: {season.starts_at:%d.%m} - {season.ends_at:%d.%m}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pvp-stats", description="Показать PvP статистику игрока")
    async def pvp_stats(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        target = user or interaction.user
        async with self.bot.db.session() as session:
            service = PvpService(session)
            season_service = PvpSeasonService(session, self.bot)
            season = await season_service.get_or_create_active_season(interaction.guild.id, dt.datetime.utcnow())
            stats = await service.get_user_stats(interaction.guild.id, target.id)
        total_duels = int(stats.wins or 0) + int(stats.losses or 0)
        winrate = (int(stats.wins or 0) / total_duels * 100.0) if total_duels > 0 else 0.0
        embed = build_ux_embed(title="📊 PvP статистика", description=f"Игрок: {target.mention}", color=discord.Color.blurple(), next_hint="Используйте /pvp для нового боя.")
        embed.add_field(name="Рейтинг", value=str(stats.rating), inline=True)
        embed.add_field(name="W/L", value=f"{stats.wins}/{stats.losses}", inline=True)
        embed.add_field(name="Винрейт", value=f"{winrate:.1f}%", inline=True)
        embed.add_field(name="Сезон", value=f"#{season.season_number}: {season.starts_at:%d.%m.%Y} - {season.ends_at:%d.%m.%Y}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pvp_season", description="Текущий PvP сезон и предварительный топ")
    async def pvp_season(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            service = PvpService(session)
            season_service = PvpSeasonService(session, self.bot)
            season = await season_service.get_or_create_active_season(interaction.guild.id, dt.datetime.utcnow())
            top_players = await service.get_top_players(interaction.guild.id, limit=10)
        embed = discord.Embed(title=f"🗓️ PvP сезон #{season.season_number}", color=discord.Color.blurple())
        embed.add_field(name="Начало", value=season.starts_at.strftime("%d.%m.%Y %H:%M UTC"), inline=True)
        embed.add_field(name="Окончание", value=season.ends_at.strftime("%d.%m.%Y %H:%M UTC"), inline=True)
        embed.add_field(name="Топ-10", value="\n".join([f"**{idx}.** <@{p.user_id}> — R{p.rating}" for idx, p in enumerate(top_players, 1)]) if top_players else "Пока нет данных.", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pvp_season_top", description="Топ-10 игроков текущего PvP сезона")
    async def pvp_season_top(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            service = PvpService(session)
            top_players = await service.get_top_players(interaction.guild.id, limit=10)
        if not top_players:
            await interaction.response.send_message("За текущий сезон нет статистики.", ephemeral=True)
            return
        embed = discord.Embed(title="🏆 Топ-10 сезона PvP", color=discord.Color.gold())
        embed.description = "\n".join([f"**{index}.** <@{p.user_id}> — R{p.rating} | W/L: {p.wins}/{p.losses} | Профит: {p.total_profit}" for index, p in enumerate(top_players, 1)])
        await interaction.response.send_message(embed=embed)

    async def _get_pvp_settings(self, session, guild_id: int) -> dict:
        return await PvpService(session).get_pvp_settings(guild_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PvpCog(bot))
