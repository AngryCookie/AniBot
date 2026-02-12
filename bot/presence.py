from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import discord
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bot.betting.enums import BettingMatchStatus
from bot.betting.models import BettingMatch, BettingTeam
from bot.database.models import BotSettings, GuildConfig

DEFAULT_PRESENCE_SETTINGS: dict = {
    "enabled": True,
    "mode": "primary_guild",
    "primary_guild_id": None,
    "interval_seconds": 300,
    "templates": [
        {"type": "playing", "text": "🎲 Ставки: {open_matches} открыто"},
        {"type": "watching", "text": "⚔ PvP дуэли идут!"},
        {"type": "listening", "text": "Сегодня: {today_match}"},
    ],
}


@dataclass(slots=True)
class PresenceContext:
    guild_name: str
    members: str
    online: str
    active_matches: str
    open_matches: str
    today_match: str | None


class PresenceSettingsService:
    KEY = "presence"

    @classmethod
    def merge(cls, raw: dict | None) -> dict:
        payload = dict(DEFAULT_PRESENCE_SETTINGS)
        payload.update(raw or {})
        payload["interval_seconds"] = max(60, int(payload.get("interval_seconds", 300)))
        mode = str(payload.get("mode", "primary_guild"))
        payload["mode"] = mode if mode in {"primary_guild", "rotate_guilds"} else "primary_guild"
        templates = payload.get("templates", [])
        if not isinstance(templates, list):
            templates = []
        normalized = []
        for item in templates:
            if not isinstance(item, dict):
                continue
            t = str(item.get("type", "playing"))
            if t not in {"playing", "watching", "listening"}:
                t = "playing"
            text = str(item.get("text", "")).strip()
            if text:
                normalized.append({"type": t, "text": text[:128]})
        payload["templates"] = normalized or list(DEFAULT_PRESENCE_SETTINGS["templates"])
        try:
            payload["primary_guild_id"] = int(payload.get("primary_guild_id")) if payload.get("primary_guild_id") else None
        except (TypeError, ValueError):
            payload["primary_guild_id"] = None
        payload["enabled"] = bool(payload.get("enabled", True))
        return payload

    @classmethod
    async def get(cls, session: AsyncSession) -> dict:
        row = await session.scalar(select(BotSettings).where(BotSettings.key == cls.KEY))
        if row is None:
            return dict(DEFAULT_PRESENCE_SETTINGS)
        try:
            raw = json.loads(row.value or "{}")
        except json.JSONDecodeError:
            raw = {}
        return cls.merge(raw)

    @classmethod
    async def save(cls, session: AsyncSession, payload: dict) -> dict:
        merged = cls.merge(payload)
        row = await session.scalar(select(BotSettings).where(BotSettings.key == cls.KEY))
        encoded = json.dumps(merged)
        if row is None:
            row = BotSettings(key=cls.KEY, value=encoded)
            session.add(row)
        else:
            row.value = encoded
        await session.commit()
        return merged


class PresenceDataProvider:
    def __init__(self) -> None:
        self._cache: dict[int, tuple[dt.datetime, PresenceContext]] = {}

    async def get_context(self, session: AsyncSession, guild: discord.Guild) -> PresenceContext:
        now = dt.datetime.utcnow()
        cached = self._cache.get(guild.id)
        if cached and (now - cached[0]).total_seconds() < 60:
            return cached[1]

        members = str(getattr(guild, "member_count", None) or "—")
        online = "—"
        if guild.members:
            online_count = sum(1 for m in guild.members if getattr(m, "status", discord.Status.offline) != discord.Status.offline)
            online = str(online_count)

        cfg_raw = await session.scalar(select(GuildConfig.settings).where(GuildConfig.guild_id == guild.id))
        tz_name = "UTC"
        if cfg_raw:
            try:
                cfg = json.loads(cfg_raw)
                tz_name = str((cfg.get("betting") or {}).get("scheduling", {}).get("timezone", "UTC"))
            except (TypeError, ValueError, json.JSONDecodeError):
                tz_name = "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")

        now_tz = dt.datetime.now(tz)
        day_start_utc = now_tz.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc).replace(tzinfo=None)
        day_end_utc = (now_tz.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)).astimezone(dt.timezone.utc).replace(tzinfo=None)

        open_q = select(func.count(BettingMatch.id)).where(
            (BettingMatch.guild_id == guild.id) & (BettingMatch.status == BettingMatchStatus.open)
        )
        active_q = select(func.count(BettingMatch.id)).where(
            (BettingMatch.guild_id == guild.id)
            & (BettingMatch.betting_open_at >= day_start_utc)
            & (BettingMatch.betting_open_at < day_end_utc)
            & (BettingMatch.status.in_([BettingMatchStatus.open, BettingMatchStatus.closed, BettingMatchStatus.scheduled]))
        )
        open_matches = int((await session.execute(open_q)).scalar_one() or 0)
        active_matches = int((await session.execute(active_q)).scalar_one() or 0)

        team_a = aliased(BettingTeam)
        team_b = aliased(BettingTeam)
        today_q = (
            select(BettingMatch, team_a.name, team_b.name)
            .join(team_a, BettingMatch.team_a_id == team_a.id)
            .join(team_b, BettingMatch.team_b_id == team_b.id)
            .where(
                (BettingMatch.guild_id == guild.id)
                & (BettingMatch.betting_open_at >= day_start_utc)
                & (BettingMatch.betting_open_at < day_end_utc)
                & (BettingMatch.status.in_([BettingMatchStatus.scheduled, BettingMatchStatus.open]))
                & (BettingMatch.betting_close_at >= dt.datetime.utcnow())
            )
            .order_by(BettingMatch.betting_open_at.asc())
            .limit(1)
        )
        today = (await session.execute(today_q)).first()
        today_match = None
        if today:
            match, a_name, b_name = today
            local_time = match.betting_open_at.replace(tzinfo=dt.timezone.utc).astimezone(tz)
            today_match = f"{a_name} vs {b_name} • {local_time:%H:%M}"

        context = PresenceContext(
            guild_name=guild.name,
            members=members,
            online=online,
            active_matches=str(active_matches),
            open_matches=str(open_matches),
            today_match=today_match,
        )
        self._cache[guild.id] = (now, context)
        return context


def render_presence_text(template: str, ctx: PresenceContext) -> str | None:
    mapping = {
        "guild_name": ctx.guild_name or "—",
        "members": ctx.members or "—",
        "online": ctx.online or "—",
        "active_matches": ctx.active_matches or "0",
        "open_matches": ctx.open_matches or "0",
        "today_match": ctx.today_match or "—",
    }
    if "{today_match}" in template and not ctx.today_match:
        return None
    result = template
    for key, value in mapping.items():
        result = result.replace("{" + key + "}", str(value))
    return result[:128]


def to_activity(activity_type: str, text: str) -> discord.Activity:
    type_map = {
        "playing": discord.ActivityType.playing,
        "watching": discord.ActivityType.watching,
        "listening": discord.ActivityType.listening,
    }
    return discord.Activity(type=type_map.get(activity_type, discord.ActivityType.playing), name=text)
