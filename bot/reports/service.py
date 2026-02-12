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

logger = logging.getLogger(__name__)

DEFAULT_REPORTS_SETTINGS = {
    "enabled": True,
    "timezone": "UTC",
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
    def _load_reports_settings(raw_settings: str | None) -> dict:
        import json

        try:
            payload = json.loads(raw_settings or "{}")
        except json.JSONDecodeError:
            payload = {}
        reports = payload.get("reports", {}) if isinstance(payload, dict) else {}
        if not isinstance(reports, dict):
            reports = {}

        merged = {
            **DEFAULT_REPORTS_SETTINGS,
            **reports,
            "monthly": {
                **DEFAULT_REPORTS_SETTINGS["monthly"],
                **(reports.get("monthly", {}) if isinstance(reports.get("monthly", {}), dict) else {}),
                "include_sections": {
                    **DEFAULT_REPORTS_SETTINGS["monthly"]["include_sections"],
                    **(
                        reports.get("monthly", {}).get("include_sections", {})
                        if isinstance(reports.get("monthly", {}), dict)
                        and isinstance(reports.get("monthly", {}).get("include_sections", {}), dict)
                        else {}
                    ),
                },
            },
        }
        return merged

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
                logger.exception("Monthly wrapped scheduler failed", extra={"guild_id": int(cfg.guild_id)})

    async def _process_guild(self, guild, config: GuildConfig, *, now_utc: dt.datetime) -> None:
        settings = self._load_reports_settings(config.settings)
        monthly = settings.get("monthly", {})
        if not settings.get("enabled", True) or not monthly.get("enabled", True):
            return

        channel_id = monthly.get("channel_id")
        if not channel_id:
            return

        tz_name = str(settings.get("timezone", "UTC"))
        tz = ZoneInfo(tz_name)
        local_now = now_utc.astimezone(tz)
        post_day = int(monthly.get("post_day", 1))
        post_hour = int(monthly.get("post_hour", 12))
        if local_now.day != post_day or local_now.hour != post_hour:
            return

        period = calculate_previous_month_period(tz_name=tz_name, now_utc=now_utc)
        await self._generate_and_post(
            guild=guild,
            channel_id=int(channel_id),
            period_start=period.period_start_utc,
            period_end=period.period_end_utc,
            tz_name=tz_name,
            include_sections=monthly.get("include_sections", {}),
            allow_failed_retry=True,
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
            allow_failed_retry=True,
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
        allow_failed_retry: bool,
    ) -> GuildReport | None:
        async with self.bot.db.session() as session:
            existing_result = await session.execute(
                select(GuildReport).where(
                    (GuildReport.guild_id == guild.id)
                    & (GuildReport.report_type == "monthly")
                    & (GuildReport.period_start == period_start)
                    & (GuildReport.period_end == period_end)
                )
            )
            existing = existing_result.scalars().first()
            if existing and existing.status == "posted":
                return existing

            payload = await build_monthly_payload(
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
                    report_type="monthly",
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
                embed = build_monthly_embed(payload)
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
                logger.info("Guild monthly report already exists", extra={"guild_id": guild.id})
                return None
            except Exception:
                report.status = "failed"
                report.payload_json = payload
                report.channel_id = channel_id
                await session.commit()

            return report
