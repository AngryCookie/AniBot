from __future__ import annotations

import datetime as dt
import logging
import os
from zoneinfo import ZoneInfo

import discord
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bot.database.models import GuildConfig, GuildReport
from bot.reports.monthly import build_monthly_embed, build_monthly_payload, calculate_previous_month_period
from bot.reports.yearly import build_yearly_embed, build_yearly_payload, calculate_previous_year_period

logger = logging.getLogger(__name__)

DEFAULT_REPORTS_SETTINGS = {
    "enabled": True,
    "timezone": "UTC",
    "retention_days": None,
    "monthly": {
        "enabled": True,
        "channel_id": None,
        "post_day": 1,
        "post_hour": 12,
        "include_sections": {
            "messages": True,
            "voice": True,
            "economy": True,
            "betting": True,
            "pvp": True,
            "moderation": True,
            "words": True,
            "emojis": True,
            "reactions": True,
        },
    },
    "yearly": {
        "enabled": True,
        "channel_id": None,
        "post_month": 12,
        "post_day": 28,
        "post_hour": 12,
        "include_sections": {
            "messages": True,
            "voice": True,
            "economy": True,
            "betting": True,
            "pvp": True,
            "moderation": True,
            "words": True,
            "emojis": True,
            "reactions": True,
        },
    },
}


class MonthlyWrappedService:
    def __init__(self, bot) -> None:
        self.bot = bot

    @staticmethod
    def _now_utc() -> dt.datetime:
        override = os.getenv("REPORTS_NOW", "").strip()
        if override:
            parsed = dt.datetime.fromisoformat(override.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        return dt.datetime.now(dt.timezone.utc)

    @staticmethod
    def _merge_include_sections(reports: dict, report_type: str) -> dict:
        report_settings = reports.get(report_type, {}) if isinstance(reports.get(report_type, {}), dict) else {}
        include = report_settings.get("include_sections", {}) if isinstance(report_settings.get("include_sections", {}), dict) else {}
        return {
            **DEFAULT_REPORTS_SETTINGS[report_type],
            **report_settings,
            "include_sections": {
                **DEFAULT_REPORTS_SETTINGS[report_type]["include_sections"],
                **include,
            },
        }

    @classmethod
    def _load_reports_settings(cls, raw_settings: str | None) -> dict:
        import json

        try:
            payload = json.loads(raw_settings or "{}")
        except json.JSONDecodeError:
            payload = {}
        reports = payload.get("reports", {}) if isinstance(payload, dict) else {}
        if not isinstance(reports, dict):
            reports = {}

        return {
            **DEFAULT_REPORTS_SETTINGS,
            **reports,
            "monthly": cls._merge_include_sections(reports, "monthly"),
            "yearly": cls._merge_include_sections(reports, "yearly"),
        }

    async def run_scheduler_tick(self) -> None:
        now_utc = self._now_utc()
        async with self.bot.db.session() as session:
            configs_result = await session.execute(select(GuildConfig))
            configs = configs_result.scalars().all()

        for cfg in configs:
            guild = self.bot.get_guild(int(cfg.guild_id))
            if guild is None:
                continue
            try:
                await self._process_guild(guild, cfg, now_utc=now_utc)
            except Exception:
                logger.exception("Reports scheduler failed", extra={"guild_id": int(cfg.guild_id)})

    async def _process_guild(self, guild, config: GuildConfig, *, now_utc: dt.datetime) -> None:
        settings = self._load_reports_settings(config.settings)
        if not settings.get("enabled", True):
            return

        tz_name = str(settings.get("timezone", "UTC"))
        tz = ZoneInfo(tz_name)
        local_now = now_utc.astimezone(tz)

        monthly = settings.get("monthly", {})
        monthly_channel_id = monthly.get("channel_id")
        if monthly.get("enabled", True) and monthly_channel_id:
            post_day = int(monthly.get("post_day", 1))
            post_hour = int(monthly.get("post_hour", 12))
            if local_now.day == post_day and local_now.hour == post_hour:
                period = calculate_previous_month_period(tz_name=tz_name, now_utc=now_utc)
                await self._generate_and_post(
                    guild=guild,
                    channel_id=int(monthly_channel_id),
                    period_start=period.period_start_utc,
                    period_end=period.period_end_utc,
                    tz_name=tz_name,
                    include_sections=monthly.get("include_sections", {}),
                    report_type="monthly",
                )

        yearly = settings.get("yearly", {})
        yearly_channel_id = yearly.get("channel_id")
        if yearly.get("enabled", True) and yearly_channel_id:
            post_month = int(yearly.get("post_month", 12))
            post_day = int(yearly.get("post_day", 28))
            post_hour = int(yearly.get("post_hour", 12))
            if local_now.month == post_month and local_now.day == post_day and local_now.hour == post_hour:
                period = calculate_previous_year_period(tz_name=tz_name, now_utc=now_utc)
                await self._generate_and_post(
                    guild=guild,
                    channel_id=int(yearly_channel_id),
                    period_start=period.period_start_utc,
                    period_end=period.period_end_utc,
                    tz_name=tz_name,
                    include_sections=yearly.get("include_sections", {}),
                    report_type="yearly",
                )

    async def preview_last_month(self, *, guild_id: int, include_sections: dict[str, bool], tz_name: str) -> dict:
        now_utc = self._now_utc()
        period = calculate_previous_month_period(tz_name=tz_name, now_utc=now_utc)
        async with self.bot.db.session() as session:
            return await build_monthly_payload(
                session,
                guild_id=guild_id,
                period_start=period.period_start_utc,
                period_end=period.period_end_utc,
                tz=tz_name,
                include_sections=include_sections,
            )

    async def preview_last_year(self, *, guild_id: int, include_sections: dict[str, bool], tz_name: str) -> dict:
        now_utc = self._now_utc()
        period = calculate_previous_year_period(tz_name=tz_name, now_utc=now_utc)
        async with self.bot.db.session() as session:
            return await build_yearly_payload(
                session,
                guild_id=guild_id,
                period_start=period.period_start_utc,
                period_end=period.period_end_utc,
                tz=tz_name,
                include_sections=include_sections,
            )

    async def post_now(self, *, guild, channel_id: int, include_sections: dict[str, bool], tz_name: str) -> GuildReport | None:
        now_utc = self._now_utc()
        period = calculate_previous_month_period(tz_name=tz_name, now_utc=now_utc)
        return await self._generate_and_post(
            guild=guild,
            channel_id=channel_id,
            period_start=period.period_start_utc,
            period_end=period.period_end_utc,
            tz_name=tz_name,
            include_sections=include_sections,
            report_type="monthly",
        )

    async def post_yearly_now(self, *, guild, channel_id: int, include_sections: dict[str, bool], tz_name: str) -> GuildReport | None:
        now_utc = self._now_utc()
        period = calculate_previous_year_period(tz_name=tz_name, now_utc=now_utc)
        return await self._generate_and_post(
            guild=guild,
            channel_id=channel_id,
            period_start=period.period_start_utc,
            period_end=period.period_end_utc,
            tz_name=tz_name,
            include_sections=include_sections,
            report_type="yearly",
        )

    async def _generate_and_post(
        self,
        *,
        guild,
        channel_id: int,
        period_start: dt.datetime,
        period_end: dt.datetime,
        tz_name: str,
        include_sections: dict[str, bool],
        report_type: str,
    ) -> GuildReport | None:
        async with self.bot.db.session() as session:
            existing_result = await session.execute(
                select(GuildReport).where(
                    (GuildReport.guild_id == guild.id)
                    & (GuildReport.report_type == report_type)
                    & (GuildReport.period_start == period_start)
                    & (GuildReport.period_end == period_end)
                )
            )
            existing = existing_result.scalars().first()
            if existing and existing.status == "posted":
                return existing

            if report_type == "monthly":
                payload = await build_monthly_payload(
                    session,
                    guild_id=guild.id,
                    period_start=period_start,
                    period_end=period_end,
                    tz=tz_name,
                    include_sections=include_sections,
                )
            else:
                payload = await build_yearly_payload(
                    session,
                    guild_id=guild.id,
                    period_start=period_start,
                    period_end=period_end,
                    tz=tz_name,
                    include_sections=include_sections,
                )

            report = existing
            if report is None:
                report = GuildReport(
                    guild_id=guild.id,
                    report_type=report_type,
                    period_start=period_start,
                    period_end=period_end,
                    channel_id=channel_id,
                    payload_json=payload,
                    status="skipped",
                )
                session.add(report)

            channel = guild.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await guild.fetch_channel(channel_id)
                except Exception:
                    report.status = "failed"
                    report.payload_json = payload
                    report.channel_id = channel_id
                    await session.commit()
                    return report

            try:
                embed = build_monthly_embed(payload) if report_type == "monthly" else build_yearly_embed(payload)
                message = await channel.send(embed=embed)
                report.status = "posted"
                report.message_id = int(message.id)
                report.payload_json = payload
                report.channel_id = channel_id
                report.created_at = dt.datetime.utcnow()
                await session.commit()
            except discord.Forbidden:
                report.status = "failed"
                report.payload_json = payload
                report.channel_id = channel_id
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.info("Guild report already exists", extra={"guild_id": guild.id, "report_type": report_type})
                return None
            except Exception:
                report.status = "failed"
                report.payload_json = payload
                report.channel_id = channel_id
                await session.commit()

            return report
