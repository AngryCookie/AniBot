from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, or_, select

from bot.cogs.utils import get_or_create_guild
from bot.database.models import FeatureFlag, GuildFeatureFlag, UserProfile
from bot.referral.core import utcnow
from bot.referral.models import ReferralCampaign, ReferralLinkExtended, ReferralSeason
from bot.referral.service import PromoService, ReferralService
from bot.services.feature_flags import is_feature_enabled

REFERRAL_FEATURE_FLAG = "referral_enabled"
PROMO_FEATURE_FLAG = "promo_enabled"


class CopyCodeReminderView(discord.ui.View):
    def __init__(self, code: str) -> None:
        super().__init__(timeout=300)
        self.code = code

    @discord.ui.button(label="📋 Copy Code Reminder", style=discord.ButtonStyle.secondary)
    async def copy_code_reminder(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        embed = discord.Embed(
            title="📋 Как поделиться кодом",
            description=(
                "1. Скопируйте ваш код из сообщения выше.\n"
                "2. Отправьте друзьям в личку или в соцсетях.\n"
                "3. Друг должен использовать ваш код при регистрации/активации в рамках кампании."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Ваш код", value=f"`{self.code}`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def _is_feature_available(
    session,
    *,
    guild_id: int,
    flag_name: str,
) -> bool:
    guild_flag = await session.scalar(
        select(func.count())
        .select_from(GuildFeatureFlag)
        .where(
            GuildFeatureFlag.guild_id == guild_id,
            GuildFeatureFlag.flag_name == flag_name,
        )
    )
    global_flag = await session.scalar(
        select(func.count())
        .select_from(FeatureFlag)
        .where(FeatureFlag.name == flag_name)
    )

    if int(guild_flag or 0) == 0 and int(global_flag or 0) == 0:
        return True
    return await is_feature_enabled(session, guild_id, flag_name)


def _fmt_number(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


async def _resolve_active_campaign(session) -> ReferralCampaign | None:
    now = utcnow()
    result = await session.execute(
        select(ReferralCampaign)
        .where(
            ReferralCampaign.is_active.is_(True),
            or_(ReferralCampaign.start_at.is_(None), ReferralCampaign.start_at <= now),
            or_(ReferralCampaign.end_at.is_(None), ReferralCampaign.end_at >= now),
        )
        .order_by(ReferralCampaign.id.desc())
    )
    return result.scalars().first()


async def _resolve_active_season(session) -> ReferralSeason | None:
    now = utcnow()
    result = await session.execute(
        select(ReferralSeason)
        .where(
            ReferralSeason.is_active.is_(True),
            ReferralSeason.start_at <= now,
            ReferralSeason.end_at >= now,
        )
        .order_by(ReferralSeason.id.desc())
    )
    return result.scalars().first()


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
            if not await _is_feature_available(
                session,
                guild_id=interaction.guild.id,
                flag_name=REFERRAL_FEATURE_FLAG,
            ):
                embed = discord.Embed(
                    title="❌ Реферальная система недоступна",
                    description="Функция временно отключена на этом сервере.",
                    color=discord.Color.red(),
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            campaign = await _resolve_active_campaign(session)
            if campaign is None:
                embed = discord.Embed(
                    title="ℹ️ Активных кампаний нет",
                    description="Сейчас нет активной реферальной кампании. Попробуйте позже.",
                    color=discord.Color.blurple(),
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            service = ReferralService(session)
            code = await service.create_referral_link(
                guild_id=interaction.guild.id,
                owner_user_id=interaction.user.id,
                campaign_id=int(campaign.id),
            )

        embed = discord.Embed(
            title="✅ Ваш реферальный код готов",
            description="Поделитесь кодом с друзьями, чтобы получать награды за их активность.",
            color=discord.Color.green(),
        )
        embed.add_field(name="🔑 Код", value=f"`{code}`", inline=False)
        embed.add_field(
            name="🧭 Как использовать",
            value="Передайте код другу — он должен указать его при активации реферала.",
            inline=False,
        )
        embed.add_field(
            name="💡 Важно",
            value="Награды и условия зависят от текущей кампании сервера.",
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=CopyCodeReminderView(code=code),
            ephemeral=True,
        )

    @app_commands.command(name="stats", description="Показать вашу реферальную статистику")
    async def stats(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        async with self.bot.db.session() as session:
            if not await _is_feature_available(
                session,
                guild_id=interaction.guild.id,
                flag_name=REFERRAL_FEATURE_FLAG,
            ):
                embed = discord.Embed(
                    title="❌ Реферальная система недоступна",
                    description="Функция временно отключена на этом сервере.",
                    color=discord.Color.red(),
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            totals = await session.execute(
                select(
                    func.coalesce(func.sum(ReferralLinkExtended.total_invited), 0),
                    func.coalesce(func.sum(ReferralLinkExtended.total_active_invited), 0),
                    func.coalesce(func.sum(ReferralLinkExtended.total_revenue_generated), 0),
                    func.coalesce(func.sum(ReferralLinkExtended.total_reward_paid), 0),
                ).where(
                    ReferralLinkExtended.guild_id == interaction.guild.id,
                    ReferralLinkExtended.owner_user_id == interaction.user.id,
                )
            )
            total_invited, total_active, lifetime_revenue, total_earned = totals.one()

            season = await _resolve_active_season(session)
            season_position_text = "—"
            if season is not None:
                leaderboard = await ReferralService(session).get_leaderboard(
                    guild_id=interaction.guild.id,
                    season_id=int(season.id),
                )
                user_rank = next(
                    (
                        index
                        for index, row in enumerate(leaderboard, start=1)
                        if int(row.owner_user_id) == interaction.user.id
                    ),
                    None,
                )
                if user_rank is not None:
                    season_position_text = f"#{user_rank} ({season.name})"
                else:
                    season_position_text = f"Вне рейтинга ({season.name})"

        embed = discord.Embed(
            title="📊 Ваша реферальная статистика",
            description="Актуальные показатели по вашим приглашениям.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="👥 Всего приглашено", value=_fmt_number(int(total_invited or 0)), inline=True)
        embed.add_field(name="🔥 Активных", value=_fmt_number(int(total_active or 0)), inline=True)
        embed.add_field(
            name="💸 Lifetime Revenue",
            value=f"{_fmt_number(int(lifetime_revenue or 0))} {guild.currency_name}",
            inline=False,
        )
        embed.add_field(
            name="🪙 Заработано с рефералов",
            value=f"{_fmt_number(int(total_earned or 0))} {guild.currency_name}",
            inline=False,
        )
        embed.add_field(name="🏁 Позиция в сезоне", value=season_position_text, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="Топ пригласивших пользователей")
    @app_commands.describe(sort_by="Сортировка рейтинга")
    @app_commands.choices(
        sort_by=[
            app_commands.Choice(name="Активные приглашённые", value="active"),
            app_commands.Choice(name="Выручка", value="revenue"),
        ]
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        sort_by: app_commands.Choice[str] | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        sort_key = sort_by.value if sort_by is not None else "active"

        async with self.bot.db.session() as session:
            if not await _is_feature_available(
                session,
                guild_id=interaction.guild.id,
                flag_name=REFERRAL_FEATURE_FLAG,
            ):
                embed = discord.Embed(
                    title="❌ Реферальная система недоступна",
                    description="Функция временно отключена на этом сервере.",
                    color=discord.Color.red(),
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            statement = select(ReferralLinkExtended).where(ReferralLinkExtended.guild_id == interaction.guild.id)
            if sort_key == "revenue":
                statement = statement.order_by(
                    ReferralLinkExtended.total_revenue_generated.desc(),
                    ReferralLinkExtended.total_active_invited.desc(),
                    ReferralLinkExtended.id.asc(),
                )
            else:
                statement = statement.order_by(
                    ReferralLinkExtended.total_active_invited.desc(),
                    ReferralLinkExtended.total_revenue_generated.desc(),
                    ReferralLinkExtended.id.asc(),
                )
            top_links = (await session.execute(statement.limit(10))).scalars().all()

        if not top_links:
            embed = discord.Embed(
                title="ℹ️ Лидерборд пока пуст",
                description="Ещё никто не набрал статистику по рефералам.",
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        metric_title = "по активным приглашённым" if sort_key == "active" else "по выручке"
        embed = discord.Embed(
            title=f"🏆 Реферальный топ-10 ({metric_title})",
            description="Лучшие инвайтеры сервера на текущий момент.",
            color=discord.Color.blurple(),
        )
        lines: list[str] = []
        for index, row in enumerate(top_links, start=1):
            lines.append(
                (
                    f"**{index}.** <@{int(row.owner_user_id)}> — "
                    f"активных: **{_fmt_number(int(row.total_active_invited or 0))}**, "
                    f"выручка: **{_fmt_number(int(row.total_revenue_generated or 0))} {guild.currency_name}**"
                )
            )
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class PromoGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="promo", description="Промокоды")
        self.bot = bot

    @app_commands.command(name="redeem", description="Активировать промокод")
    async def redeem(self, interaction: discord.Interaction, code: str) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        async with self.bot.db.session() as session:
            if not await _is_feature_available(
                session,
                guild_id=interaction.guild.id,
                flag_name=PROMO_FEATURE_FLAG,
            ):
                embed = discord.Embed(
                    title="❌ Промокоды недоступны",
                    description="Функция временно отключена на этом сервере.",
                    color=discord.Color.red(),
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            service = PromoService(session)
            try:
                reward_amount = await service.redeem_promo(
                    guild_id=interaction.guild.id,
                    user_id=interaction.user.id,
                    code=code,
                )
            except ValueError as exc:
                embed = discord.Embed(
                    title="❌ Не удалось активировать промокод",
                    description=str(exc),
                    color=discord.Color.red(),
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            user_row = await session.execute(
                select(UserProfile).where(
                    UserProfile.guild_id == interaction.guild.id,
                    UserProfile.user_id == interaction.user.id,
                )
            )
            user = user_row.scalars().first()
            new_balance = int(user.balance or 0) if user is not None else 0

        embed = discord.Embed(
            title="✅ Промокод успешно активирован",
            description="Награда начислена на ваш баланс.",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="🎁 Награда",
            value=f"+{_fmt_number(int(reward_amount))} {guild.currency_name}",
            inline=False,
        )
        embed.add_field(
            name="💰 Новый баланс",
            value=f"{_fmt_number(new_balance)} {guild.currency_name}",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ReferralCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(ReferralGroup(bot))
        self.bot.tree.add_command(RefGroup(bot))
        self.bot.tree.add_command(PromoGroupV2(bot), override=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReferralCog(bot))

from bot.referral.service import GrowthV2Service


class RewardConfirmView(discord.ui.View):
    def __init__(self, amount: int, currency_name: str) -> None:
        super().__init__(timeout=120)
        self.amount = amount
        self.currency_name = currency_name

    @discord.ui.button(label="Понял, спасибо!", style=discord.ButtonStyle.success)
    async def ok(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message(
            f"Отлично! Вам начислено **{_fmt_number(self.amount)} {self.currency_name}** 🎉",
            ephemeral=True,
        )


class PromoRedeemModal(discord.ui.Modal, title="Активация промокода"):
    promo_code = discord.ui.TextInput(label="Введите промокод", min_length=3, max_length=64)

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            guild = await get_or_create_guild(session, interaction.guild.id, "Coins")
            service = GrowthV2Service(session)
            try:
                amount = await service.redeem_promo(interaction.guild.id, interaction.user.id, str(self.promo_code))
                await session.commit()
            except ValueError as exc:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return
        embed = discord.Embed(title="✅ Промокод активирован", description="Награда зачислена.", color=discord.Color.green())
        embed.add_field(name="Награда", value=f"+{_fmt_number(amount)} {guild.currency_name}")
        await interaction.response.send_message(embed=embed, view=RewardConfirmView(amount, guild.currency_name), ephemeral=True)


class RefUseModal(discord.ui.Modal, title="Привязка реферального кода"):
    ref_code = discord.ui.TextInput(label="Введите реферальный код", min_length=3, max_length=32)

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            service = GrowthV2Service(session)
            try:
                await service.use_ref_code(interaction.guild.id, interaction.user.id, str(self.ref_code))
                await session.commit()
            except ValueError as exc:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return
        await interaction.response.send_message("✅ Код принят. Ваша заявка на активацию реферала создана (статус: pending).", ephemeral=True)


class RefGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="ref", description="Реферальная система v2")
        self.bot = bot

    @app_commands.command(name="link", description="Показать ваш персональный реферальный код")
    async def link(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            service = GrowthV2Service(session)
            code = await service.get_or_create_ref_link(interaction.guild.id, interaction.user.id)
            await session.commit()
        await interaction.response.send_message(f"Ваш реферальный код: `{code}`\nПередайте его другу для команды `/ref use`.", ephemeral=True)

    @app_commands.command(name="use", description="Использовать чужой реферальный код")
    async def use(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RefUseModal(self.bot))

    @app_commands.command(name="stats", description="Ваша статистика по рефералам")
    async def stats(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            service = GrowthV2Service(session)
            stats = await service.referral_stats(interaction.guild.id, interaction.user.id)
        embed = discord.Embed(title="📊 Ваша реферальная статистика", color=discord.Color.blurple())
        embed.add_field(name="Инвайты", value=_fmt_number(stats["invites"]))
        embed.add_field(name="Активации", value=_fmt_number(stats["activations"]))
        embed.add_field(name="Награды", value=_fmt_number(stats["rewards"]))
        await interaction.response.send_message(embed=embed, ephemeral=True)


class PromoGroupV2(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="promo", description="Промокоды")
        self.bot = bot

    @app_commands.command(name="redeem", description="Активировать промокод через модальное окно")
    async def redeem(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(PromoRedeemModal(self.bot))
