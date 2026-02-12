from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
from zoneinfo import ZoneInfo

import discord
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from bot.database.models import EmojiStatDaily, GuildConfig, GuildReport, ReactionStatDaily, WordStatDaily
from bot.reports.monthly import calculate_previous_month_period
from bot.ui import EmbedFactory

logger = logging.getLogger(__name__)

DEFAULT_RITUALS_SETTINGS = {
    "enabled": True,
    "timezone": "UTC",
    "daily_this_day": {
        "enabled": True,
        "channel_id": None,
        "post_hour": 12,
        "min_years_ago": 1,
        "max_items": 3,
    },
    "monthly_highlights": {
        "enabled": True,
        "channel_id": None,
        "post_day": 1,
        "post_hour": 12,
        "include": {
            "top_word": True,
            "top_emoji": True,
            "top_reaction": True,
        },
    },
}


class RitualsService:
    def __init__(self, bot) -> None:
        self.bot = bot
        self._guild_locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def _now_utc() -> dt.datetime:
        override = os.getenv("RITUALS_NOW", "").strip()
        if override:
            parsed = dt.datetime.fromisoformat(override.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        return dt.datetime.now(dt.timezone.utc)

    @classmethod
    def _load_rituals_settings(cls, raw_settings: str | None) -> dict:
        try:
            payload = json.loads(raw_settings or "{}")
        except json.JSONDecodeError:
            payload = {}
        rituals = payload.get("rituals", {}) if isinstance(payload, dict) else {}
        if not isinstance(rituals, dict):
            rituals = {}
        daily_raw = rituals.get("daily_this_day", {}) if isinstance(rituals.get("daily_this_day", {}), dict) else {}
        monthly_raw = rituals.get("monthly_highlights", {}) if isinstance(rituals.get("monthly_highlights", {}), dict) else {}
        include_raw = monthly_raw.get("include", {}) if isinstance(monthly_raw.get("include", {}), dict) else {}

        return {
            **DEFAULT_RITUALS_SETTINGS,
            **rituals,
            "daily_this_day": {
                **DEFAULT_RITUALS_SETTINGS["daily_this_day"],
                **daily_raw,
            },
            "monthly_highlights": {
                **DEFAULT_RITUALS_SETTINGS["monthly_highlights"],
                **monthly_raw,
                "include": {
                    **DEFAULT_RITUALS_SETTINGS["monthly_highlights"]["include"],
                    **include_raw,
                },
            },
        }

    async def run_scheduler_tick(self) -> None:
        now_utc = self._now_utc()
        async with self.bot.db.session() as session:
            configs = (await session.execute(select(GuildConfig))).scalars().all()

        for cfg in configs:
            guild = self.bot.get_guild(int(cfg.guild_id))
            if guild is None:
                continue
            lock = self._guild_locks.setdefault(int(cfg.guild_id), asyncio.Lock())
            if lock.locked():
                continue
            async with lock:
                try:
                    await self._process_guild(guild, cfg, now_utc=now_utc)
                except Exception:
                    logger.exception("Rituals scheduler failed", extra={"guild_id": int(cfg.guild_id)})

    async def _process_guild(self, guild, config: GuildConfig, *, now_utc: dt.datetime) -> None:
        settings = self._load_rituals_settings(config.settings)
        if not settings.get("enabled", True):
            return
        tz_name = str(settings.get("timezone", "UTC"))
        tz = ZoneInfo(tz_name)
        local_now = now_utc.astimezone(tz)

        daily = settings.get("daily_this_day", {})
        daily_channel = daily.get("channel_id")
        if daily.get("enabled", True) and daily_channel and local_now.hour == int(daily.get("post_hour", 12)):
            await self._post_daily_this_day(
                guild=guild,
                channel_id=int(daily_channel),
                tz_name=tz_name,
                min_years_ago=int(daily.get("min_years_ago", 1)),
                max_items=int(daily.get("max_items", 3)),
                now_utc=now_utc,
            )

        monthly = settings.get("monthly_highlights", {})
        monthly_channel = monthly.get("channel_id")
        if monthly.get("enabled", True) and monthly_channel:
            if local_now.day == int(monthly.get("post_day", 1)) and local_now.hour == int(monthly.get("post_hour", 12)):
                await self._post_monthly_highlights(
                    guild=guild,
                    channel_id=int(monthly_channel),
                    tz_name=tz_name,
                    include=monthly.get("include", {}),
                    now_utc=now_utc,
                )

    async def _post_daily_this_day(
        self,
        *,
        guild,
        channel_id: int,
        tz_name: str,
        min_years_ago: int,
        max_items: int,
        now_utc: dt.datetime,
    ) -> GuildReport | None:
        tz = ZoneInfo(tz_name)
        local_now = now_utc.astimezone(tz)
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = local_start + dt.timedelta(days=1)
        period_start = local_start.astimezone(dt.timezone.utc).replace(tzinfo=None)
        period_end = local_end.astimezone(dt.timezone.utc).replace(tzinfo=None)

        async with self.bot.db.session() as session:
            report = await self._get_or_create_report(
                session=session,
                guild_id=guild.id,
                report_type="ritual_daily_this_day",
                period_start=period_start,
                period_end=period_end,
                channel_id=channel_id,
            )
            if report.status in {"posted", "skipped"}:
                return report

            highlights = await self._build_this_day_highlights(
                session=session,
                guild_id=guild.id,
                target_month=local_now.month,
                min_years_ago=min_years_ago,
                max_items=max_items,
                current_year=local_now.year,
            )
            if not highlights:
                report.status = "skipped"
                report.payload_json = {"highlights": [], "reason": "no_data"}
                await session.commit()
                return report

            channel = await self._resolve_channel(guild, channel_id)
            if channel is None:
                report.status = "failed"
                report.payload_json = {"highlights": highlights, "error": "channel_unavailable"}
                await session.commit()
                return report

            embed = self._build_daily_embed(highlights)
            try:
                message = await channel.send(embed=embed)
                report.status = "posted"
                report.message_id = int(message.id)
                report.payload_json = {"highlights": highlights}
                report.created_at = dt.datetime.utcnow()
            except discord.Forbidden:
                report.status = "failed"
                report.payload_json = {"highlights": highlights, "error": "forbidden"}
            except Exception as exc:
                report.status = "failed"
                report.payload_json = {"highlights": highlights, "error": str(exc)[:300]}
            await session.commit()
            return report

    async def _post_monthly_highlights(self, *, guild, channel_id: int, tz_name: str, include: dict, now_utc: dt.datetime) -> GuildReport | None:
        period = calculate_previous_month_period(tz_name=tz_name, now_utc=now_utc)
        async with self.bot.db.session() as session:
            report = await self._get_or_create_report(
                session=session,
                guild_id=guild.id,
                report_type="ritual_monthly_highlights",
                period_start=period.period_start_utc,
                period_end=period.period_end_utc,
                channel_id=channel_id,
            )
            if report.status in {"posted", "skipped"}:
                return report

            payload = await self._build_monthly_highlights_payload(
                session=session,
                guild_id=guild.id,
                period_start=period.period_start_utc.date(),
                period_end=(period.period_end_utc - dt.timedelta(days=1)).date(),
                include=include,
            )
            if not any(payload.get(k) for k in ("top_word", "top_emoji", "top_reaction")):
                report.status = "skipped"
                report.payload_json = payload | {"reason": "no_data"}
                await session.commit()
                return report

            channel = await self._resolve_channel(guild, channel_id)
            if channel is None:
                report.status = "failed"
                report.payload_json = payload | {"error": "channel_unavailable"}
                await session.commit()
                return report

            embed = self._build_monthly_embed(payload, period.period_start_utc)
            try:
                message = await channel.send(embed=embed)
                report.status = "posted"
                report.message_id = int(message.id)
                report.payload_json = payload
                report.created_at = dt.datetime.utcnow()
            except discord.Forbidden:
                report.status = "failed"
                report.payload_json = payload | {"error": "forbidden"}
            except Exception as exc:
                report.status = "failed"
                report.payload_json = payload | {"error": str(exc)[:300]}
            await session.commit()
            return report

    async def _build_this_day_highlights(
        self,
        *,
        session,
        guild_id: int,
        target_month: int,
        min_years_ago: int,
        max_items: int,
        current_year: int,
    ) -> list[dict]:
        monthly_reports = (
            await session.execute(
                select(GuildReport)
                .where((GuildReport.guild_id == guild_id) & (GuildReport.report_type == "monthly"))
                .order_by(GuildReport.period_start.desc())
                .limit(60)
            )
        ).scalars().all()

        highlights: list[dict] = []
        for report in monthly_reports:
            year_gap = current_year - report.period_start.year
            if report.period_start.month != target_month or year_gap < min_years_ago:
                continue
            payload = report.payload_json if isinstance(report.payload_json, dict) else {}
            lines: list[str] = []
            activity = payload.get("activity") if isinstance(payload.get("activity"), dict) else {}
            language = payload.get("language") if isinstance(payload.get("language"), dict) else {}
            if activity:
                lines.append(f"💬 Сообщений: **{int(activity.get('total_messages', 0))}**")
                top_xp = activity.get("top_xp_users", [])
                if isinstance(top_xp, list) and top_xp:
                    top = top_xp[0]
                    user_id = top.get("user_id")
                    if user_id:
                        lines.append(f"🏆 Топ участник: <@{int(user_id)}>")
            top_words = language.get("top_words", []) if isinstance(language, dict) else []
            if isinstance(top_words, list) and top_words:
                lines.append(f"🧠 Слово: **{top_words[0].get('token', '—')}**")
            top_emojis = language.get("top_emojis", []) if isinstance(language, dict) else []
            if isinstance(top_emojis, list) and top_emojis:
                lines.append(f"😄 Эмодзи: {top_emojis[0].get('emoji_key', '—')}")

            if lines:
                highlights.append({"year": int(report.period_start.year), "lines": lines[:3]})
            if len(highlights) >= max_items:
                break
        return highlights

    async def _build_monthly_highlights_payload(self, *, session, guild_id: int, period_start: dt.date, period_end: dt.date, include: dict) -> dict:
        payload: dict[str, object] = {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "top_word": None,
            "top_emoji": None,
            "top_reaction": None,
        }

        if include.get("top_word", True):
            row = (
                await session.execute(
                    select(WordStatDaily.token.label("key"), func.sum(WordStatDaily.count).label("total"))
                    .where((WordStatDaily.guild_id == guild_id) & (WordStatDaily.day >= period_start) & (WordStatDaily.day <= period_end))
                    .group_by(WordStatDaily.token)
                    .order_by(func.sum(WordStatDaily.count).desc())
                    .limit(1)
                )
            ).first()
            if row:
                payload["top_word"] = {"key": str(row.key), "count": int(row.total or 0)}

        if include.get("top_emoji", True):
            row = (
                await session.execute(
                    select(EmojiStatDaily.emoji_key.label("key"), func.sum(EmojiStatDaily.count).label("total"))
                    .where((EmojiStatDaily.guild_id == guild_id) & (EmojiStatDaily.day >= period_start) & (EmojiStatDaily.day <= period_end))
                    .group_by(EmojiStatDaily.emoji_key)
                    .order_by(func.sum(EmojiStatDaily.count).desc())
                    .limit(1)
                )
            ).first()
            if row:
                payload["top_emoji"] = {"key": str(row.key), "count": int(row.total or 0)}

        if include.get("top_reaction", True):
            try:
                row = (
                    await session.execute(
                        select(ReactionStatDaily.emoji_key.label("key"), func.sum(ReactionStatDaily.count).label("total"))
                        .where((ReactionStatDaily.guild_id == guild_id) & (ReactionStatDaily.day >= period_start) & (ReactionStatDaily.day <= period_end))
                        .group_by(ReactionStatDaily.emoji_key)
                        .order_by(func.sum(ReactionStatDaily.count).desc())
                        .limit(1)
                    )
                ).first()
                if row:
                    payload["top_reaction"] = {"key": str(row.key), "count": int(row.total or 0)}
            except SQLAlchemyError:
                logger.warning("Reaction stats unavailable", extra={"guild_id": guild_id})

        return payload

    @staticmethod
    async def _resolve_channel(guild, channel_id: int):
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except Exception:
                return None
        return channel

    @staticmethod
    async def _get_or_create_report(*, session, guild_id: int, report_type: str, period_start: dt.datetime, period_end: dt.datetime, channel_id: int) -> GuildReport:
        existing = (
            await session.execute(
                select(GuildReport).where(
                    (GuildReport.guild_id == guild_id)
                    & (GuildReport.report_type == report_type)
                    & (GuildReport.period_start == period_start)
                    & (GuildReport.period_end == period_end)
                )
            )
        ).scalars().first()
        if existing:
            return existing
        report = GuildReport(
            guild_id=guild_id,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            channel_id=channel_id,
            payload_json={},
            status="failed",
        )
        session.add(report)
        await session.flush()
        return report

    @staticmethod
    def _build_daily_embed(highlights: list[dict]) -> discord.Embed:
        embed = EmbedFactory.info("🕰️ В этот день…")
        for item in highlights:
            year = int(item.get("year", 0))
            lines = item.get("lines", []) if isinstance(item.get("lines"), list) else []
            EmbedFactory.add_section(embed, "📅", f"Год: {year}", [str(v) for v in lines[:3]])
        return embed

    @staticmethod
    def _build_monthly_embed(payload: dict, period_start: dt.datetime) -> discord.Embed:
        embed = EmbedFactory.info("🎉 Итоги месяца: хайлайты", period_start.strftime("%Y-%m"))
        top_word = payload.get("top_word") if isinstance(payload.get("top_word"), dict) else None
        top_emoji = payload.get("top_emoji") if isinstance(payload.get("top_emoji"), dict) else None
        top_reaction = payload.get("top_reaction") if isinstance(payload.get("top_reaction"), dict) else None

        if top_word:
            EmbedFactory.add_kv(embed, "🧠 Слово месяца", f"`{top_word.get('key', '—')}` ({int(top_word.get('count', 0))})", inline=False)
        if top_emoji:
            EmbedFactory.add_kv(embed, "😄 Эмодзи месяца", f"{top_emoji.get('key', '—')} ({int(top_emoji.get('count', 0))})", inline=False)
        if top_reaction:
            EmbedFactory.add_kv(embed, "👍 Реакция месяца", f"{top_reaction.get('key', '—')} ({int(top_reaction.get('count', 0))})", inline=False)
        return embed
