from __future__ import annotations

import datetime as dt
import logging
import os
import random
from zoneinfo import ZoneInfo

import discord
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ActivityEvent, EconomyTransaction, GuildConfig, GuildGoalTemplate, GuildMonthlyGoal, GuildMonthlyGoalContribution

logger = logging.getLogger(__name__)

GOAL_TYPES = {"voice_minutes", "messages", "economy_earned", "betting_volume", "pvp_volume"}
ELIGIBILITY_TYPES = {"voice_minutes", "messages", "economy_activity"}

DEFAULT_MONTHLY_GOALS_SETTINGS = {
    "enabled": True,
    "auto_generate": True,
    "announce_channel_id": None,
    "reward_role_id": None,
    "close_day": 1,
    "close_hour": 12,
    "timezone": "UTC",
    "default_template_id": None,
}


class MonthlyCommunityGoalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _now_utc() -> dt.datetime:
        override = os.getenv("MONTHLY_GOALS_NOW", "").strip()
        if override:
            parsed = dt.datetime.fromisoformat(override.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return dt.datetime.utcnow()

    @staticmethod
    def _month_date(now_tz: dt.datetime) -> dt.date:
        return dt.date(now_tz.year, now_tz.month, 1)

    @staticmethod
    def _month_bounds(month: dt.date, tz: ZoneInfo) -> tuple[dt.datetime, dt.datetime]:
        start_local = dt.datetime(month.year, month.month, 1, tzinfo=tz)
        if month.month == 12:
            next_local = dt.datetime(month.year + 1, 1, 1, tzinfo=tz)
        else:
            next_local = dt.datetime(month.year, month.month + 1, 1, tzinfo=tz)
        return (
            start_local.astimezone(dt.timezone.utc).replace(tzinfo=None),
            next_local.astimezone(dt.timezone.utc).replace(tzinfo=None),
        )

    @classmethod
    def parse_settings(cls, raw_settings: str | None) -> dict:
        import json

        try:
            payload = json.loads(raw_settings or "{}")
        except Exception:
            payload = {}
        section = payload.get("monthly_goals", {}) if isinstance(payload, dict) else {}
        if not isinstance(section, dict):
            section = {}
        return {**DEFAULT_MONTHLY_GOALS_SETTINGS, **section}

    @staticmethod
    def save_settings(raw_settings: str | None, monthly_goals: dict) -> str:
        import json

        try:
            payload = json.loads(raw_settings or "{}")
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload["monthly_goals"] = monthly_goals
        return json.dumps(payload, ensure_ascii=False)

    async def get_or_create_monthly_goal(self, guild_id: int, now_tz: dt.datetime, settings: dict) -> GuildMonthlyGoal | None:
        month = self._month_date(now_tz)
        result = await self.session.execute(select(GuildMonthlyGoal).where((GuildMonthlyGoal.guild_id == guild_id) & (GuildMonthlyGoal.month == month)))
        existing = result.scalars().first()
        if existing is not None:
            return existing
        if not settings.get("auto_generate", True):
            return None

        template = await self._pick_template(guild_id, settings)
        if template is None:
            return None
        tz = ZoneInfo(str(settings.get("timezone", "UTC")))
        start_utc, end_utc = self._month_bounds(month, tz)
        goal = GuildMonthlyGoal(
            guild_id=guild_id,
            month=month,
            template_id=template.id,
            goal_type=template.goal_type,
            target_value=int(template.target_value),
            progress_value=0,
            status="active",
            started_at=start_utc,
            ends_at=end_utc,
            reward_role_id=settings.get("reward_role_id"),
            announce_channel_id=settings.get("announce_channel_id"),
        )
        self.session.add(goal)
        await self.session.flush()
        return goal

    async def _pick_template(self, guild_id: int, settings: dict) -> GuildGoalTemplate | None:
        default_template_id = settings.get("default_template_id")
        if default_template_id:
            result = await self.session.execute(select(GuildGoalTemplate).where((GuildGoalTemplate.guild_id == guild_id) & (GuildGoalTemplate.id == int(default_template_id)) & (GuildGoalTemplate.enabled.is_(True))))
            template = result.scalars().first()
            if template is not None:
                return template
        result = await self.session.execute(select(GuildGoalTemplate).where((GuildGoalTemplate.guild_id == guild_id) & (GuildGoalTemplate.enabled.is_(True))).order_by(GuildGoalTemplate.id.asc()))
        templates = result.scalars().all()
        if not templates:
            return None
        return random.choice(templates)

    async def recalc_progress(self, guild_id: int, goal_id: int, period_start: dt.datetime, period_end: dt.datetime) -> int:
        goal = await self.session.get(GuildMonthlyGoal, goal_id)
        if goal is None:
            return 0
        value = await self._aggregate_metric(guild_id, goal.goal_type, period_start, period_end)
        goal.progress_value = int(value)
        if goal.status == "active" and goal.progress_value >= goal.target_value:
            goal.status = "completed"
        await self.session.flush()
        return goal.progress_value

    async def _aggregate_metric(self, guild_id: int, metric: str, start: dt.datetime, end: dt.datetime) -> int:
        if metric == "voice_minutes":
            q = select(func.coalesce(func.sum(ActivityEvent.value), 0)).where((ActivityEvent.guild_id == guild_id) & (ActivityEvent.event_type == "voice_minutes") & (ActivityEvent.created_at >= start) & (ActivityEvent.created_at < end))
            return int(await self.session.scalar(q) or 0)
        if metric == "messages":
            q = select(func.coalesce(func.sum(ActivityEvent.value), 0)).where((ActivityEvent.guild_id == guild_id) & (ActivityEvent.event_type == "message") & (ActivityEvent.created_at >= start) & (ActivityEvent.created_at < end))
            return int(await self.session.scalar(q) or 0)
        if metric == "economy_earned":
            q = select(func.coalesce(func.sum(case((EconomyTransaction.amount > 0, EconomyTransaction.amount), else_=0)), 0)).where((EconomyTransaction.guild_id == guild_id) & (EconomyTransaction.created_at >= start) & (EconomyTransaction.created_at < end))
            return int(await self.session.scalar(q) or 0)
        if metric == "betting_volume":
            q = select(func.coalesce(func.sum(case(((EconomyTransaction.source == "bet_placement") & (EconomyTransaction.amount < 0), -EconomyTransaction.amount), else_=0)), 0)).where((EconomyTransaction.guild_id == guild_id) & (EconomyTransaction.created_at >= start) & (EconomyTransaction.created_at < end))
            return int(await self.session.scalar(q) or 0)
        if metric == "pvp_volume":
            q = select(func.coalesce(func.sum(case((EconomyTransaction.source == "pvp_duel_lock", EconomyTransaction.amount), else_=0)), 0)).where((EconomyTransaction.guild_id == guild_id) & (EconomyTransaction.created_at >= start) & (EconomyTransaction.created_at < end))
            return int(await self.session.scalar(q) or 0)
        return 0

    async def recalc_contributions(self, guild_id: int, goal_id: int, period_start: dt.datetime, period_end: dt.datetime) -> int:
        goal = await self.session.get(GuildMonthlyGoal, goal_id)
        if goal is None:
            return 0
        template = await self.session.get(GuildGoalTemplate, goal.template_id) if goal.template_id else None
        eligibility_type = template.eligibility_type if template else "messages"
        eligibility_min = int(template.eligibility_min_value if template else 0)
        rows = await self._aggregate_per_user(guild_id, eligibility_type, period_start, period_end)
        affected = 0
        for user_id, value in rows:
            stmt = select(GuildMonthlyGoalContribution).where((GuildMonthlyGoalContribution.goal_id == goal_id) & (GuildMonthlyGoalContribution.user_id == user_id))
            existing = (await self.session.execute(stmt)).scalars().first()
            eligible = int(value) >= eligibility_min
            if existing is None:
                existing = GuildMonthlyGoalContribution(guild_id=guild_id, goal_id=goal_id, user_id=int(user_id), contribution_value=int(value), eligible=eligible, rewarded=False)
                self.session.add(existing)
                affected += 1
            else:
                existing.contribution_value = int(value)
                existing.eligible = eligible
                affected += 1
        await self.session.flush()
        return affected

    async def _aggregate_per_user(self, guild_id: int, metric: str, start: dt.datetime, end: dt.datetime) -> list[tuple[int, int]]:
        if metric == "voice_minutes":
            q = select(ActivityEvent.user_id, func.coalesce(func.sum(ActivityEvent.value), 0).label("v")).where((ActivityEvent.guild_id == guild_id) & (ActivityEvent.event_type == "voice_minutes") & (ActivityEvent.created_at >= start) & (ActivityEvent.created_at < end)).group_by(ActivityEvent.user_id)
        elif metric == "messages":
            q = select(ActivityEvent.user_id, func.coalesce(func.sum(ActivityEvent.value), 0).label("v")).where((ActivityEvent.guild_id == guild_id) & (ActivityEvent.event_type == "message") & (ActivityEvent.created_at >= start) & (ActivityEvent.created_at < end)).group_by(ActivityEvent.user_id)
        else:
            q = select(EconomyTransaction.user_id, func.count(EconomyTransaction.id).label("v")).where((EconomyTransaction.guild_id == guild_id) & (EconomyTransaction.created_at >= start) & (EconomyTransaction.created_at < end)).group_by(EconomyTransaction.user_id)
        result = await self.session.execute(q)
        return [(int(r[0]), int(r[1] or 0)) for r in result.all() if r[0] is not None]

    async def close_monthly_goal(self, guild: discord.Guild, goal_id: int, now_tz: dt.datetime) -> dict:
        goal = await self.session.get(GuildMonthlyGoal, goal_id)
        if goal is None:
            return {"closed": False, "reason": "not_found"}
        if goal.closed_at is not None and goal.status == "closed":
            return {"closed": False, "reason": "already_closed"}

        success = int(goal.progress_value) >= int(goal.target_value)
        eligible_result = await self.session.execute(select(GuildMonthlyGoalContribution).where((GuildMonthlyGoalContribution.goal_id == goal.id) & (GuildMonthlyGoalContribution.eligible.is_(True))).order_by(GuildMonthlyGoalContribution.contribution_value.desc()))
        eligible_rows = eligible_result.scalars().all()

        role_added = 0
        role_removed = 0
        if success and goal.reward_role_id:
            role = guild.get_role(int(goal.reward_role_id))
            if role is not None:
                for row in eligible_rows:
                    member = guild.get_member(int(row.user_id))
                    if member is None:
                        continue
                    if role not in member.roles:
                        await member.add_roles(role, reason=f"Monthly goal reward {goal.month}")
                    if not row.rewarded:
                        row.rewarded = True
                        role_added += 1

        prev_result = await self.session.execute(
            select(GuildMonthlyGoal)
            .where((GuildMonthlyGoal.guild_id == goal.guild_id) & (GuildMonthlyGoal.month < goal.month) & (GuildMonthlyGoal.closed_at.is_not(None)) & (GuildMonthlyGoal.reward_role_id.is_not(None)))
            .order_by(GuildMonthlyGoal.month.desc())
            .limit(1)
        )
        prev_goal = prev_result.scalars().first()
        if prev_goal is not None and prev_goal.reward_role_id:
            prev_role = guild.get_role(int(prev_goal.reward_role_id))
            if prev_role is not None:
                prev_contrib = await self.session.execute(select(GuildMonthlyGoalContribution).where((GuildMonthlyGoalContribution.goal_id == prev_goal.id) & (GuildMonthlyGoalContribution.rewarded.is_(True))))
                for row in prev_contrib.scalars().all():
                    member = guild.get_member(int(row.user_id))
                    if member is None:
                        continue
                    if prev_role in member.roles:
                        await member.remove_roles(prev_role, reason=f"Monthly goal rotation {goal.month}")
                        role_removed += 1

        if goal.summary_message_id is None and goal.announce_channel_id:
            channel = guild.get_channel(int(goal.announce_channel_id))
            if channel is not None:
                top10 = "\n".join([f"<@{r.user_id}> — {int(r.contribution_value)}" for r in eligible_rows[:10]]) or "—"
                embed = discord.Embed(title="🎯 Итог цели месяца", color=discord.Color.green() if success else discord.Color.red(), timestamp=dt.datetime.utcnow())
                embed.add_field(name="Результат", value="Выполнена" if success else "Не выполнена", inline=True)
                embed.add_field(name="Прогресс", value=f"{int(goal.progress_value)} / {int(goal.target_value)}", inline=True)
                embed.add_field(name="Подходящих участников", value=str(len(eligible_rows)), inline=True)
                embed.add_field(name="Топ-10 участников", value=top10, inline=False)
                msg = await channel.send(embed=embed)
                goal.summary_message_id = int(msg.id)

        goal.status = "closed"
        goal.closed_at = dt.datetime.utcnow()
        await self.session.flush()
        return {"closed": True, "success": success, "eligible": len(eligible_rows), "role_added": role_added, "role_removed": role_removed}

    async def scheduler_tick(self, bot: discord.Client) -> None:
        now_utc = self._now_utc()
        configs = (await self.session.execute(select(GuildConfig))).scalars().all()
        for cfg in configs:
            settings = self.parse_settings(cfg.settings)
            if not settings.get("enabled", True):
                continue
            guild = bot.get_guild(int(cfg.guild_id))
            if guild is None:
                continue
            tz = ZoneInfo(str(settings.get("timezone", "UTC")))
            now_tz = now_utc.replace(tzinfo=dt.timezone.utc).astimezone(tz)
            goal = await self.get_or_create_monthly_goal(int(cfg.guild_id), now_tz, settings)
            if goal is not None and goal.status in {"active", "completed"}:
                await self.recalc_progress(int(cfg.guild_id), int(goal.id), goal.started_at, goal.ends_at)
                await self.recalc_contributions(int(cfg.guild_id), int(goal.id), goal.started_at, goal.ends_at)

            prev_month = (now_tz.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
            close_moment = now_tz.replace(day=int(settings.get("close_day", 1)), hour=int(settings.get("close_hour", 12)), minute=0, second=0, microsecond=0)
            prev_goal_result = await self.session.execute(select(GuildMonthlyGoal).where((GuildMonthlyGoal.guild_id == int(cfg.guild_id)) & (GuildMonthlyGoal.month == prev_month.date())))
            prev_goal = prev_goal_result.scalars().first()
            if prev_goal and prev_goal.closed_at is None and now_tz >= close_moment:
                await self.recalc_progress(int(cfg.guild_id), int(prev_goal.id), prev_goal.started_at, prev_goal.ends_at)
                await self.recalc_contributions(int(cfg.guild_id), int(prev_goal.id), prev_goal.started_at, prev_goal.ends_at)
                await self.close_monthly_goal(guild, int(prev_goal.id), now_tz)
