from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time
from collections.abc import Awaitable, Callable

from discord.ext import commands, tasks
from sqlalchemy import and_, delete, select, update

from bot.community_goals import CommunityGoalService
from bot.database.models import EconomyLedger, GuildConfig, GuildReport, ModLog, PvpSeason, PvpSeasonResult, ServerMonthlyGoal, UserProfile
from bot.goals.service import MonthlyCommunityGoalService
from bot.monthly_goals import MonthlyGoalService
from bot.pvp.seasons import PvpSeasonService
from bot.reports.service import MonthlyWrappedService

logger = logging.getLogger(__name__)


class SchedulerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.monthly_reports_service = MonthlyWrappedService(bot)
        self._task_locks: dict[str, asyncio.Lock] = {}
        self._next_run: dict[str, dt.datetime] = {}
        self.daily_reset_task.start()
        self.cleanup_task.start()
        self.community_goals_task.start()
        self.monthly_goals_task.start()
        self.monthly_reports_task.start()
        self.monthly_community_goals_v2_task.start()
        self.pvp_seasons_task.start()

    def cog_unload(self) -> None:
        self.daily_reset_task.cancel()
        self.cleanup_task.cancel()
        self.community_goals_task.cancel()
        self.monthly_goals_task.cancel()
        self.monthly_reports_task.cancel()
        self.monthly_community_goals_v2_task.cancel()
        self.pvp_seasons_task.cancel()

    async def _run_task(self, key: str, coro_factory: Callable[[], Awaitable[None]]) -> None:
        lock = self._task_locks.setdefault(key, asyncio.Lock())
        if lock.locked():
            logger.warning("Scheduler task skipped due to overlap", extra={"task": key, "next_run": self._next_run.get(key).isoformat() if self._next_run.get(key) else None})
            return

        started = time.monotonic()
        async with lock:
            try:
                await coro_factory()
            except Exception:
                logger.exception("Scheduler task failed", extra={"task": key})
            finally:
                next_iter = getattr(getattr(self, key), "next_iteration", None)
                self._next_run[key] = next_iter
                logger.info(
                    "Scheduler task finished",
                    extra={
                        "task": key,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                        "next_run": next_iter.isoformat() if next_iter else None,
                    },
                )

    @tasks.loop(hours=24)
    async def daily_reset_task(self) -> None:
        async def _job() -> None:
            async with self.bot.db.session() as session:
                async with session.begin():
                    await session.execute(update(UserProfile).values(daily_bet_amount=0, daily_xp=0))

        await self._run_task("daily_reset_task", _job)

    @tasks.loop(hours=12)
    async def cleanup_task(self) -> None:
        async def _job() -> None:
            now = dt.datetime.utcnow()
            deleted = {"ledger": 0, "mod_log": 0, "season_results": 0, "reports": 0}
            async with self.bot.db.session() as session:
                async with session.begin():
                    configs = (await session.execute(select(GuildConfig))).scalars().all()
                    for cfg in configs:
                        settings = self._load_settings(cfg.settings)
                        guild_id = int(cfg.guild_id)

                        ledger_cutoff = now - dt.timedelta(days=90)
                        modlog_cutoff = now - dt.timedelta(days=90)
                        seasonal_cutoff = now - dt.timedelta(days=int(settings.get("elo_history_retention_days", 365)))

                        deleted["ledger"] += await self._delete_in_batches(
                            session,
                            EconomyLedger,
                            (EconomyLedger.guild_id == guild_id) & (EconomyLedger.timestamp < ledger_cutoff),
                        )
                        deleted["mod_log"] += await self._delete_in_batches(
                            session,
                            ModLog,
                            (ModLog.guild_id == guild_id) & (ModLog.created_at < modlog_cutoff),
                        )
                        old_seasons_subq = select(PvpSeason.id).where((PvpSeason.guild_id == guild_id) & (PvpSeason.ends_at < seasonal_cutoff))
                        deleted["season_results"] += await self._delete_in_batches(
                            session,
                            PvpSeasonResult,
                            (PvpSeasonResult.guild_id == guild_id) & (PvpSeasonResult.season_id.in_(old_seasons_subq)),
                            enabled=bool(settings.get("elo_history_retention_enabled", False)),
                        )

                        reports_retention_days = settings.get("reports_retention_days")
                        if reports_retention_days:
                            report_cutoff = now - dt.timedelta(days=int(reports_retention_days))
                            deleted["reports"] += await self._delete_in_batches(
                                session,
                                GuildReport,
                                (GuildReport.guild_id == guild_id) & (GuildReport.created_at < report_cutoff),
                            )

            logger.info("Cleanup task completed", extra={"deleted": deleted})

        await self._run_task("cleanup_task", _job)

    @staticmethod
    def _load_settings(raw_settings: str | None) -> dict:
        try:
            payload = json.loads(raw_settings or "{}")
        except json.JSONDecodeError:
            payload = {}
        scheduler = payload.get("scheduler", {}) if isinstance(payload, dict) else {}
        if not isinstance(scheduler, dict):
            scheduler = {}
        return {
            "elo_history_retention_enabled": bool(scheduler.get("elo_history_retention_enabled", False)),
            "elo_history_retention_days": int(scheduler.get("elo_history_retention_days", 365)),
            "reports_retention_days": scheduler.get("reports_retention_days"),
        }

    async def _delete_in_batches(self, session, model, where_clause, *, batch_size: int = 500, enabled: bool = True) -> int:
        if not enabled:
            return 0
        deleted_total = 0
        while True:
            ids = (await session.execute(select(model.id).where(where_clause).order_by(model.id.asc()).limit(batch_size))).scalars().all()
            if not ids:
                break
            result = await session.execute(delete(model).where(model.id.in_(ids)))
            deleted_total += int(result.rowcount or 0)
            if len(ids) < batch_size:
                break
        return deleted_total

    @tasks.loop(minutes=10)
    async def community_goals_task(self) -> None:
        async def _job() -> None:
            for guild in self.bot.guilds:
                try:
                    async with self.bot.db.session() as session:
                        async with session.begin():
                            service = CommunityGoalService(session)
                            goal = await service.get_active_goal(guild.id)
                            if goal is None:
                                continue

                            now = dt.datetime.utcnow()
                            if goal.status != "active" or now < goal.ends_at:
                                continue

                            evaluated_goal = await service.evaluate_goal(guild.id)
                            if evaluated_goal is None:
                                continue

                            if evaluated_goal.status == "completed":
                                removed_count = await service.remove_previous_goal_roles(self.bot, guild.id)
                                rewarded_count = await service.distribute_rewards(self.bot, guild.id)
                                logger.info(
                                    "Community goal completed and rewards processed",
                                    extra={
                                        "guild_id": guild.id,
                                        "goal_id": evaluated_goal.id,
                                        "removed_previous_roles": removed_count,
                                        "rewarded_members": rewarded_count,
                                    },
                                )
                            else:
                                logger.info(
                                    "Community goal finished with failed status",
                                    extra={"guild_id": guild.id, "goal_id": evaluated_goal.id},
                                )
                except Exception:
                    logger.exception(
                        "Community goal scheduler iteration failed",
                        extra={"guild_id": guild.id},
                    )

        await self._run_task("community_goals_task", _job)

    @tasks.loop(hours=24)
    async def monthly_goals_task(self) -> None:
        async def _job() -> None:
            current_month = dt.datetime.utcnow().strftime("%Y-%m")
            previous_month_date = dt.datetime.utcnow().replace(day=1) - dt.timedelta(days=1)
            previous_month = previous_month_date.strftime("%Y-%m")

            async with self.bot.db.session() as session:
                async with session.begin():
                    service = MonthlyGoalService(session)

                    await session.execute(
                        update(ServerMonthlyGoal)
                        .where(
                            and_(
                                ServerMonthlyGoal.month == previous_month,
                                ServerMonthlyGoal.is_active.is_(True),
                            )
                        )
                        .values(is_active=False)
                    )

                    result = await session.execute(
                        select(ServerMonthlyGoal).where(
                            (ServerMonthlyGoal.is_active.is_(True)) & (ServerMonthlyGoal.month == current_month)
                        )
                    )
                    active_goals = result.scalars().all()

                    for goal in active_goals:
                        completion = await service.check_and_complete_goal(goal.guild_id, goal.month)
                        if completion is None or not completion.completed:
                            continue

                        eligible_users = await service.get_eligible_users(
                            goal.guild_id,
                            goal.metric_type,
                            goal.month,
                            goal.min_user_contribution,
                        )

                        assigned_count = await service.assign_reward_role(
                            bot=self.bot,
                            guild_id=goal.guild_id,
                            reward_role_id=goal.reward_role_id,
                            user_ids=eligible_users,
                            reason=f"Monthly goal reward {goal.month}",
                        )

                        logger.info(
                            "Monthly goal completed and rewards assigned",
                            extra={
                                "guild_id": goal.guild_id,
                                "goal_id": goal.id,
                                "month": goal.month,
                                "metric_type": goal.metric_type,
                                "progress": completion.progress,
                                "target": goal.target_value,
                                "eligible_count": len(eligible_users),
                                "assigned_count": assigned_count,
                            },
                        )

                    previous_result = await session.execute(
                        select(ServerMonthlyGoal).where(
                            and_(
                                ServerMonthlyGoal.month == previous_month,
                                ServerMonthlyGoal.completed_at.is_not(None),
                                ServerMonthlyGoal.reward_role_id.is_not(None),
                            )
                        )
                    )
                    for old_goal in previous_result.scalars().all():
                        old_users = await service.get_eligible_users(
                            old_goal.guild_id,
                            old_goal.metric_type,
                            old_goal.month,
                            old_goal.min_user_contribution,
                        )
                        removed_count = await service.remove_reward_role(
                            bot=self.bot,
                            guild_id=old_goal.guild_id,
                            reward_role_id=old_goal.reward_role_id,
                            user_ids=old_users,
                            reason=f"Monthly goal cleanup {old_goal.month}",
                        )
                        if removed_count:
                            logger.info(
                                "Monthly goal previous month role cleanup completed",
                                extra={
                                    "guild_id": old_goal.guild_id,
                                    "goal_id": old_goal.id,
                                    "month": old_goal.month,
                                    "removed_count": removed_count,
                                },
                            )

        await self._run_task("monthly_goals_task", _job)

    @tasks.loop(minutes=15)
    async def pvp_seasons_task(self) -> None:
        async def _job() -> None:
            now = dt.datetime.utcnow()
            async with self.bot.db.session() as session:
                async with session.begin():
                    result = await session.execute(select(GuildConfig))
                    for config in result.scalars().all():
                        try:
                            service = PvpSeasonService(session, self.bot)
                            await service.process_rotation_for_guild(int(config.guild_id), now)
                        except Exception:
                            logger.exception(
                                "PvP season scheduler iteration failed",
                                extra={"guild_id": int(config.guild_id)},
                            )

        await self._run_task("pvp_seasons_task", _job)

    @tasks.loop(minutes=10)
    async def monthly_reports_task(self) -> None:
        await self._run_task("monthly_reports_task", self.monthly_reports_service.run_scheduler_tick)

    @tasks.loop(minutes=20)
    async def monthly_community_goals_v2_task(self) -> None:
        async def _job() -> None:
            async with self.bot.db.session() as session:
                async with session.begin():
                    service = MonthlyCommunityGoalService(session)
                    await service.scheduler_tick(self.bot)

        await self._run_task("monthly_community_goals_v2_task", _job)

    @daily_reset_task.before_loop
    @cleanup_task.before_loop
    @community_goals_task.before_loop
    @monthly_goals_task.before_loop
    @monthly_reports_task.before_loop
    @pvp_seasons_task.before_loop
    @monthly_community_goals_v2_task.before_loop
    async def before_tasks(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
