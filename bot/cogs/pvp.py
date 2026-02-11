from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.pvp import PvpService


class PvpChallengeView(discord.ui.View):
    def __init__(
        self,
        cog: "PvpCog",
        *,
        guild_id: int,
        duel_id: int,
        challenger_id: int,
        opponent_id: int,
        channel_id: int,
    ) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.duel_id = duel_id
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id
        self.channel_id = channel_id
        self.message_id: int | None = None

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

    async def on_timeout(self) -> None:
        async with self.cog.bot.db.session() as session:
            async with session.begin():
                service = PvpService(session)
                duel = await service.expire_pending_duel(guild_id=self.guild_id, duel_id=self.duel_id)

        if duel.status != "expired":
            return

        self.disable_all_items()
        embed = discord.Embed(
            title="⚔️ PvP вызов истёк",
            description=f"<@{self.opponent_id}> не ответил(а) на вызов от <@{self.challenger_id}> вовремя.",
            color=discord.Color.dark_orange(),
        )
        if self.message_id is None:
            return
        channel = self.cog.bot.get_channel(self.channel_id)
        if channel is None:
            return
        try:
            message = await channel.fetch_message(self.message_id)
            await message.edit(embed=embed, view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return


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
                    if not settings.get("enabled", True):
                        raise ValueError("PvP-дуэли отключены на этом сервере.")
                    if interaction.user.id == user.id:
                        raise ValueError("Нельзя вызвать самого себя на дуэль.")
                    min_bet = int(settings.get("min_bet", 10))
                    max_bet = int(settings.get("max_bet", 5000))
                    if amount < min_bet or amount > max_bet:
                        raise ValueError(f"Ставка должна быть в диапазоне {min_bet}..{max_bet}.")
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

        view = PvpChallengeView(
            self,
            guild_id=interaction.guild.id,
            duel_id=duel.id,
            challenger_id=interaction.user.id,
            opponent_id=user.id,
            channel_id=interaction.channel_id,
        )
        embed = discord.Embed(title="⚔️ PvP вызов", color=discord.Color.blurple())
        embed.description = f"{interaction.user.mention} вызывает {user.mention} на дуэль."
        embed.add_field(name="Ставка", value=str(amount), inline=True)
        embed.add_field(name="Комиссия", value=f"{duel.fee_percent:.2f}%", inline=True)
        embed.set_footer(text="Нажмите Принять или Отклонить")
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()
        view.message_id = message.id

    async def _get_pvp_settings(self, session, guild_id: int) -> dict:
        from bot.database.models import GuildConfig
        from bot.cogs.utils import parse_settings

        config = await session.get(GuildConfig, guild_id)
        if config is None:
            return {
                "enabled": True,
                "min_bet": 10,
                "max_bet": 5000,
                "fee_percent": 5.0,
                "cooldown_seconds": 30,
                "influence_level_weight": 1.0,
            }
        settings_map = parse_settings(config.settings)
        return settings_map.get(
            "pvp",
            {
                "enabled": True,
                "min_bet": 10,
                "max_bet": 5000,
                "fee_percent": 5.0,
                "cooldown_seconds": 30,
                "influence_level_weight": 1.0,
            },
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PvpCog(bot))
