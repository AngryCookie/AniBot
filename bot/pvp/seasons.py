from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

import discord
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import GuildConfig, PvpSeason, PvpSeasonResult, PvpStats
from bot.services.pvp import DEFAULT_RATING

logger = logging.getLogger(__name__)

DEFAULT_PVP_SEASON_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "season_duration_days": 30,
    "auto_close_enabled": True,
    "announce_channel_id": None,
    "reset_mode": "hard",
    "reward_roles": {
        "top1_role_id": None,
        "top3_role_id": None,
        "top10_role_id": None,
    },
}


class PvpSeasonService:
    def __init__(self, session: AsyncSession, bot: discord.Client | None = None) -> None:
        self.session = session
        self.bot = bot

    async def get_settings(self, guild_id: int) -> dict[str, Any]:
        config = await self.session.get(GuildConfig, guild_id)
        if config is None:
            return json.loads(json.dumps(DEFAULT_PVP_SEASON_SETTINGS))
        try:
            raw = json.loads(config.settings or "{}")
        except json.JSONDecodeError:
            raw = {}
        pvp_season = raw.get("pvp_season", {}) if isinstance(raw, dict) else {}
        if not isinstance(pvp_season, dict):
            pvp_season = {}
        merged = json.loads(json.dumps(DEFAULT_PVP_SEASON_SETTINGS))
        merged.update({k: v for k, v in pvp_season.items() if k != "reward_roles"})
        reward_roles = pvp_season.get("reward_roles", {})
        if isinstance(reward_roles, dict):
            merged["reward_roles"].update(reward_roles)
        return merged

    async def get_or_create_active_season(self, guild_id: int, now: dt.datetime) -> PvpSeason:
        result = await self.session.execute(
            select(PvpSeason)
            .where(PvpSeason.guild_id == guild_id, PvpSeason.status == "active")
            .order_by(PvpSeason.season_number.desc())
            .limit(1)
        )
        existing = result.scalars().first()
        if existing is not None:
            return existing
        return await self.start_new_season(guild_id, now)

    async def start_new_season(self, guild_id: int, now: dt.datetime) -> PvpSeason:
        latest_result = await self.session.execute(
            select(PvpSeason)
            .where(PvpSeason.guild_id == guild_id)
            .order_by(PvpSeason.season_number.desc())
            .limit(1)
        )
        latest = latest_result.scalars().first()
        next_number = (int(latest.season_number) + 1) if latest else 1

        settings = await self.get_settings(guild_id)
        duration_days = max(1, int(settings.get("season_duration_days", 30)))
        start_at = now
        end_at = now + dt.timedelta(days=duration_days)

        season = PvpSeason(
            guild_id=guild_id,
            season_number=next_number,
            starts_at=start_at,
            ends_at=end_at,
            status="active",
        )
        self.session.add(season)
        await self.session.flush()
        return season

    async def close_season(self, guild_id: int, season_id: int, now: dt.datetime) -> PvpSeason | None:
        result = await self.session.execute(
            select(PvpSeason)
            .where(PvpSeason.guild_id == guild_id, PvpSeason.id == season_id)
            .with_for_update()
        )
        season = result.scalars().first()
        if season is None:
            return None
        if season.status == "closed":
            return season

        standings_result = await self.session.execute(
            select(PvpStats)
            .where(PvpStats.guild_id == guild_id)
            .order_by(PvpStats.rating.desc(), PvpStats.wins.desc(), PvpStats.user_id.asc())
            .limit(50)
        )
        standings = list(standings_result.scalars().all())

        existing_results = await self.session.execute(
            select(PvpSeasonResult.id)
            .where(PvpSeasonResult.guild_id == guild_id, PvpSeasonResult.season_id == season.id)
            .limit(1)
        )
        has_results = existing_results.first() is not None

        if not has_results:
            for rank, stat in enumerate(standings, start=1):
                self.session.add(
                    PvpSeasonResult(
                        guild_id=guild_id,
                        season_id=season.id,
                        user_id=stat.user_id,
                        final_rating=stat.rating,
                        wins=stat.wins,
                        losses=stat.losses,
                        total_profit=stat.total_profit,
                        total_volume=stat.total_volume,
                        rank=rank,
                    )
                )

        season.status = "closed"
        season.closed_at = now

        settings = await self.get_settings(guild_id)
        await self._rotate_roles(guild_id=guild_id, season=season, settings=settings)
        await self._post_summary(guild_id=guild_id, season=season, settings=settings, standings=standings)
        await self._reset_stats(guild_id=guild_id, settings=settings)
        await self.session.flush()
        return season

    async def _post_summary(
        self,
        *,
        guild_id: int,
        season: PvpSeason,
        settings: dict[str, Any],
        standings: list[PvpStats],
    ) -> None:
        if season.summary_message_id:
            return
        if self.bot is None:
            return

        announce_channel_id = settings.get("announce_channel_id")
        if not announce_channel_id:
            return

        channel = self.bot.get_channel(int(announce_channel_id))
        if channel is None:
            return

        embed = discord.Embed(
            title=f"🏁 Итоги PvP сезона #{season.season_number}",
            color=discord.Color.gold(),
            timestamp=dt.datetime.utcnow(),
        )
        embed.description = (
            f"Период: **{season.starts_at:%d.%m.%Y} — {season.ends_at:%d.%m.%Y}**\n"
            f"Закрыт: **{season.closed_at:%d.%m.%Y %H:%M UTC}**"
        )

        if standings:
            lines = []
            for rank, item in enumerate(standings[:10], start=1):
                lines.append(
                    f"**{rank}.** <@{item.user_id}> — R{item.rating} | W/L: {item.wins}/{item.losses}"
                )
            embed.add_field(name="🏆 Топ-10", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="🏆 Топ-10", value="Нет данных за сезон", inline=False)

        try:
            message = await channel.send(embed=embed)
        except Exception:
            logger.exception("Failed to post PvP season summary", extra={"guild_id": guild_id, "season_id": season.id})
            return

        season.summary_message_id = int(message.id)
        season.summary_channel_id = int(channel.id)

    async def _rotate_roles(self, *, guild_id: int, season: PvpSeason, settings: dict[str, Any]) -> None:
        if self.bot is None:
            return
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return

        reward_roles = settings.get("reward_roles", {}) if isinstance(settings.get("reward_roles"), dict) else {}
        top1_role_id = reward_roles.get("top1_role_id")
        top3_role_id = reward_roles.get("top3_role_id")
        top10_role_id = reward_roles.get("top10_role_id")

        previous_closed_result = await self.session.execute(
            select(PvpSeason)
            .where(PvpSeason.guild_id == guild_id, PvpSeason.status == "closed", PvpSeason.id != season.id)
            .order_by(PvpSeason.closed_at.desc(), PvpSeason.id.desc())
            .limit(1)
        )
        prev = previous_closed_result.scalars().first()

        if prev is not None:
            old_results_result = await self.session.execute(
                select(PvpSeasonResult).where(
                    PvpSeasonResult.guild_id == guild_id,
                    PvpSeasonResult.season_id == prev.id,
                    PvpSeasonResult.rank <= 10,
                )
            )
            for res in old_results_result.scalars().all():
                member = guild.get_member(int(res.user_id))
                if member is None:
                    continue
                for rid in [top1_role_id, top3_role_id, top10_role_id]:
                    if not rid:
                        continue
                    role = guild.get_role(int(rid))
                    if role and role in member.roles:
                        try:
                            await member.remove_roles(role, reason=f"PvP season {season.season_number} rotation")
                        except Exception:
                            logger.exception("Failed to remove PvP season role", extra={"guild_id": guild_id, "user_id": res.user_id})

        new_results_result = await self.session.execute(
            select(PvpSeasonResult).where(
                PvpSeasonResult.guild_id == guild_id,
                PvpSeasonResult.season_id == season.id,
                PvpSeasonResult.rank <= 10,
            )
        )
        for res in new_results_result.scalars().all():
            member = guild.get_member(int(res.user_id))
            if member is None:
                continue
            role_ids: list[int] = []
            if res.rank == 1 and top1_role_id:
                role_ids.append(int(top1_role_id))
            if res.rank <= 3 and top3_role_id:
                role_ids.append(int(top3_role_id))
            if res.rank <= 10 and top10_role_id:
                role_ids.append(int(top10_role_id))
            for role_id in role_ids:
                role = guild.get_role(role_id)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"PvP season {season.season_number} reward")
                    except Exception:
                        logger.exception("Failed to add PvP season role", extra={"guild_id": guild_id, "user_id": res.user_id})

    async def _reset_stats(self, *, guild_id: int, settings: dict[str, Any]) -> None:
        reset_mode = str(settings.get("reset_mode", "hard")).lower().strip()
        stats_result = await self.session.execute(select(PvpStats).where(PvpStats.guild_id == guild_id))
        stats = stats_result.scalars().all()
        now = dt.datetime.utcnow()
        for item in stats:
            item.rating = DEFAULT_RATING
            if reset_mode == "hard":
                item.wins = 0
                item.losses = 0
                item.total_volume = 0
                item.total_profit = 0
                item.total_fees_paid = 0
                item.current_streak = 0
                item.best_streak = 0
            item.updated_at = now

    async def process_rotation_for_guild(self, guild_id: int, now: dt.datetime) -> None:
        settings = await self.get_settings(guild_id)
        if not bool(settings.get("enabled", True)):
            return
        if not bool(settings.get("auto_close_enabled", True)):
            return

        active = await self.get_or_create_active_season(guild_id, now)
        if now < active.ends_at:
            return

        closed = await self.close_season(guild_id, active.id, now)
        if closed is None:
            return
        await self.start_new_season(guild_id, now)


__all__ = ["PvpSeasonService", "DEFAULT_PVP_SEASON_SETTINGS"]
