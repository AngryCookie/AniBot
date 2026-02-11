from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.pvp import PvpService


class PvpChallengeView(discord.ui.View):
    def __init__(self, cog: "PvpCog", duel_id: int, challenger_id: int, opponent_id: int) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.duel_id = duel_id
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message("Только оппонент может принять дуэль.", ephemeral=True)
            return
        async with self.cog.bot.db.session() as session:
            try:
                async with session.begin():
                    service = PvpService(session)
                    duel = await service.accept_duel(
                        guild_id=interaction.guild.id,
                        duel_id=self.duel_id,
                        actor_user_id=interaction.user.id,
                    )
                    resolved = await service.resolve_duel(
                        guild_id=interaction.guild.id,
                        duel_id=duel.id,
                    )
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return

        self.disable_all_items()
        winner_mention = f"<@{resolved.winner_id}>" if resolved.winner_id else "—"
        fee_amount = int(int(resolved.amount) * 2 * float(resolved.fee_percent) / 100.0)
        payout = int(resolved.amount) * 2 - fee_amount
        embed = discord.Embed(title="⚔️ PvP дуэль завершена", color=discord.Color.green())
        embed.add_field(name="Победитель", value=winner_mention, inline=False)
        embed.add_field(name="Ставка", value=str(resolved.amount), inline=True)
        embed.add_field(name="Комиссия", value=f"{resolved.fee_percent:.2f}% ({fee_amount})", inline=True)
        embed.add_field(name="Выплата", value=str(payout), inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message("Только оппонент может отклонить дуэль.", ephemeral=True)
            return

        async with self.cog.bot.db.session() as session:
            try:
                async with session.begin():
                    service = PvpService(session)
                    await service.decline_duel(
                        guild_id=interaction.guild.id,
                        duel_id=self.duel_id,
                        actor_user_id=interaction.user.id,
                    )
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return

        self.disable_all_items()
        embed = discord.Embed(
            title="⚔️ PvP дуэль отклонена",
            description=f"<@{self.opponent_id}> отклонил(а) вызов от <@{self.challenger_id}>.",
            color=discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=self)


class PvpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="pvp", description="Вызвать пользователя на PvP-дуэль на монеты")
    async def pvp(self, interaction: discord.Interaction, user: discord.Member, amount: int) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        async with self.bot.db.session() as session:
            try:
                async with session.begin():
                    service = PvpService(session)
                    settings = await self._get_pvp_settings(session, interaction.guild.id)
                    duel = await service.create_duel(
                        guild_id=interaction.guild.id,
                        challenger_id=interaction.user.id,
                        opponent_id=user.id,
                        amount=amount,
                        fee_percent=float(settings.get("fee_percent", 5.0)),
                    )
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return

        view = PvpChallengeView(self, duel.id, interaction.user.id, user.id)
        embed = discord.Embed(title="⚔️ PvP вызов", color=discord.Color.blurple())
        embed.description = f"{interaction.user.mention} вызывает {user.mention} на дуэль."
        embed.add_field(name="Ставка", value=str(amount), inline=True)
        embed.add_field(name="Комиссия", value=f"{duel.fee_percent:.2f}%", inline=True)
        embed.set_footer(text="Нажмите Принять или Отклонить")
        await interaction.response.send_message(embed=embed, view=view)


    @app_commands.command(name="pvp-top", description="Топ игроков PvP по рейтингу")
    async def pvp_top(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        async with self.bot.db.session() as session:
            service = PvpService(session)
            top_players = await service.get_top_players(interaction.guild.id, limit=10)

        if not top_players:
            await interaction.response.send_message("Пока нет PvP-статистики.", ephemeral=True)
            return

        embed = discord.Embed(title="🏆 PvP рейтинг", color=discord.Color.gold())
        lines = []
        for index, player in enumerate(top_players, start=1):
            lines.append(
                f"**{index}.** <@{player.user_id}> — R{player.rating} | W/L: {player.wins}/{player.losses}"
            )
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pvp-stats", description="Показать PvP статистику игрока")
    async def pvp_stats(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        target = user or interaction.user
        async with self.bot.db.session() as session:
            service = PvpService(session)
            stats = await service.get_user_stats(interaction.guild.id, target.id)

        total_duels = int(stats.wins or 0) + int(stats.losses or 0)
        winrate = (int(stats.wins or 0) / total_duels * 100.0) if total_duels > 0 else 0.0

        embed = discord.Embed(title="📊 PvP статистика", color=discord.Color.blurple())
        embed.description = f"Игрок: {target.mention}"
        embed.add_field(name="Рейтинг", value=str(stats.rating), inline=True)
        embed.add_field(name="Победы / Поражения", value=f"{stats.wins}/{stats.losses}", inline=True)
        embed.add_field(name="Винрейт", value=f"{winrate:.1f}%", inline=True)
        embed.add_field(name="Общий объём", value=str(stats.total_volume), inline=True)
        embed.add_field(name="Профит", value=str(stats.total_profit), inline=True)
        embed.add_field(name="Комиссии", value=str(stats.total_fees_paid), inline=True)
        embed.add_field(name="Текущий стрик", value=str(stats.current_streak), inline=True)
        embed.add_field(name="Лучший стрик", value=str(stats.best_streak), inline=True)
        await interaction.response.send_message(embed=embed)

    async def _get_pvp_settings(self, session, guild_id: int) -> dict:
        service = PvpService(session)
        return await service.get_pvp_settings(guild_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PvpCog(bot))
