from __future__ import annotations

import datetime as dt
import logging

import discord
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bot.analytics.service import AnalyticsService
from bot.database.models import GuildConfig, MonthlyAnalyticsReport
from bot.services.feature_flags import is_feature_enabled

logger = logging.getLogger(__name__)

MONTHLY_REPORTS_ENABLED_FLAG = "monthly_reports_enabled"
MONTHLY_REPORTS_AUTOPOST_FLAG = "monthly_reports_autopost"


class MonthlyAnalyticsReportService:
    def __init__(self, bot) -> None:
        self.bot = bot
        self.analytics_service = AnalyticsService(bot.db)

    @staticmethod
    def _previous_month(today: dt.date) -> tuple[int, int]:
        prev_last_day = today.replace(day=1) - dt.timedelta(days=1)
        return prev_last_day.year, prev_last_day.month

    @staticmethod
    def _period_days_for_month(year: int, month: int) -> int:
        current_month_start = dt.date(year=year, month=month, day=1)
        next_month = (current_month_start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return (next_month - current_month_start).days

    def build_embed(self, guild_name: str, report_payload: dict, year: int, month: int) -> discord.Embed:
        economy = report_payload.get("economy", {})
        betting = report_payload.get("betting", {})
        activity = report_payload.get("activity", {})

        embed = discord.Embed(
            title=f"Ежемесячный отчёт • {month:02d}.{year}",
            description=f"Сервер: **{guild_name}**",
            color=discord.Color.blurple(),
            timestamp=dt.datetime.utcnow(),
        )
        embed.add_field(name="Валюта в обороте", value=str(int(economy.get("total_currency_in_circulation", 0))), inline=True)
        embed.add_field(name="Заработано", value=str(int(economy.get("total_earned", 0))), inline=True)
        embed.add_field(name="Потрачено", value=str(int(economy.get("total_spent", 0))), inline=True)
        embed.add_field(name="Объём ставок", value=str(int(betting.get("total_bets_amount", 0))), inline=True)
        embed.add_field(name="Net house", value=str(int(betting.get("house_net", 0))), inline=True)
        embed.add_field(name="Сообщения", value=str(int(activity.get("total_messages", 0))), inline=True)
        return embed

    async def run_daily(self) -> None:
        today = dt.datetime.utcnow().date()
        if today.day != 1:
            return

        year, month = self._previous_month(today)
        period_days = self._period_days_for_month(year, month)

        for guild in self.bot.guilds:
            await self._process_guild(guild, year=year, month=month, period_days=period_days)

    async def _process_guild(self, guild, *, year: int, month: int, period_days: int) -> None:
        async with self.bot.db.session() as session:
            if not await is_feature_enabled(session, guild.id, MONTHLY_REPORTS_ENABLED_FLAG):
                return

            existing = await session.execute(
                select(MonthlyAnalyticsReport).where(
                    (MonthlyAnalyticsReport.guild_id == guild.id)
                    & (MonthlyAnalyticsReport.year == year)
                    & (MonthlyAnalyticsReport.month == month)
                )
            )
            report = existing.scalars().first()
            if report is None:
                analytics = await self.analytics_service.get_full_analytics(
                    guild_id=guild.id,
                    period_days=period_days,
                )
                report = MonthlyAnalyticsReport(
                    guild_id=guild.id,
                    year=year,
                    month=month,
                    report_payload={
                        "economy": analytics.get("economy", {}),
                        "betting": analytics.get("betting", {}),
                        "activity": analytics.get("activity", {}),
                    },
                )
                session.add(report)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    logger.info(
                        "Monthly report already exists due to concurrent write",
                        extra={"guild_id": guild.id, "year": year, "month": month},
                    )
                    return
                await session.refresh(report)

            if report.autoposted_at is not None:
                return

            if not await is_feature_enabled(session, guild.id, MONTHLY_REPORTS_AUTOPOST_FLAG):
                return

            cfg_result = await session.execute(
                select(GuildConfig).where(GuildConfig.guild_id == guild.id)
            )
            config = cfg_result.scalars().first()
            channel_id = int(config.analytics_channel_id) if config and config.analytics_channel_id else None
            if not channel_id:
                return

            channel = guild.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await guild.fetch_channel(channel_id)
                except Exception:
                    logger.warning(
                        "Analytics channel not found for monthly report autopost",
                        extra={"guild_id": guild.id, "channel_id": channel_id},
                    )
                    return

            try:
                embed = self.build_embed(guild.name, report.report_payload, year, month)
                await channel.send(embed=embed)
                report.autoposted_at = dt.datetime.utcnow()
                await session.commit()
            except discord.Forbidden:
                logger.warning(
                    "Missing permissions to send monthly analytics report",
                    extra={"guild_id": guild.id, "channel_id": channel_id},
                )
            except Exception:
                logger.exception(
                    "Failed to autopost monthly analytics report",
                    extra={"guild_id": guild.id, "channel_id": channel_id},
                )
