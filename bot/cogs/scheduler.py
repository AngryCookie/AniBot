from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time
from collections.abc import Awaitable, Callable

from discord.ext import commands, tasks
from sqlalchemy import and_, delete, select, update

from bot.betting.scheduler import apply_power_drift_for_guild, ensure_scheduling_horizon, run_betting_automation_tick, update_match_statuses
from bot.betting.service import BettingService
from bot.betting.models import BettingBet, BettingPayout, BettingMatch, PowerDriftLog
from bot.community_goals import CommunityGoalService
from bot.database.models import EconomyLedger, GuildConfig, GuildReport, JobRun, ModLog, PvpSeason, PvpSeasonResult, ServerMonthlyGoal, UserBuff, UserProfile, TavernPurchaseLog
from bot.goals.service import MonthlyCommunityGoalService
from bot.monthly_goals import MonthlyGoalService
from bot.presence import PresenceDataProvider, PresenceSettingsService, render_presence_text, to_activity
from bot.pvp.seasons import PvpSeasonService
from bot.reports.rituals import RitualsService
from bot.reports.service import MonthlyWrappedService
from bot.services.buffs import BuffService
from bot.services.tavern import TavernService

logger = logging.getLogger(__name__)


class SchedulerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.monthly_reports_service = MonthlyWrappedService(bot)
        self.rituals_service = RitualsService(bot)
        self._task_locks: dict[str, asyncio.Lock] = {}
        self._next_run: dict[str, dt.datetime] = {}
        self._betting_auto_apply_next: dict[int, dt.datetime] = {}
        self._presence_provider = PresenceDataProvider()
        self._presence_template_idx = 0
        self._presence_guild_idx = 0
        self._presence_next_run = dt.datetime.min
        self.daily_reset_task.start()
        self.cleanup_task.start()
        self.community_goals_task.start()
        self.monthly_goals_task.start()
        self.monthly_reports_task.start()
        self.rituals_task.start()
        self.monthly_community_goals_v2_task.start()
        self.pvp_seasons_task.start()
        self.betting_scheduling_task.start()
        self.buff_expiry_task.start()
        self.presence_task.start()

    def cog_unload(self) -> None:
        self.daily_reset_task.cancel()
        self.cleanup_task.cancel()
        self.community_goals_task.cancel()
        self.monthly_goals_task.cancel()
        self.monthly_reports_task.cancel()
        self.rituals_task.cancel()
        self.monthly_community_goals_v2_task.cancel()
        self.pvp_seasons_task.cancel()
        self.betting_scheduling_task.cancel()
        self.buff_expiry_task.cancel()
        self.presence_task.cancel()

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
                task_obj = getattr(self, key, None)
                next_iter = getattr(task_obj, "next_iteration", None) if task_obj is not None else None
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
            deleted = {
                "ledger": 0,
                "mod_log": 0,
                "season_results": 0,
                "reports": 0,
                "job_runs": 0,
                "tavern_purchase_logs": 0,
                "betting_bets": 0,
                "betting_payouts": 0,
                "betting_matches": 0,
                "power_drift_logs": 0,
                "inactive_buffs": 0,
            }
            async with self.bot.db.session() as session:
                async with session.begin():
                    configs = (await session.execute(select(GuildConfig))).scalars().all()
                    for cfg in configs:
                        settings = self._load_settings(cfg.settings)
                        guild_id = int(cfg.guild_id)

                        ledger_cutoff = now - dt.timedelta(days=90)
                        modlog_cutoff = now - dt.timedelta(days=90)
                        seasonal_cutoff = now - dt.timedelta(days=int(settings.get("elo_history_retention_days", 365)))
                        power_drift_cutoff = now.date() - dt.timedelta(days=int(settings.get("power_drift_retention_days", 600)))

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

                        optional_cutoffs = {
                            "job_runs": settings.get("job_runs_retention_days"),
                            "tavern_purchase_logs": settings.get("tavern_purchase_retention_days"),
                            "betting_bets": settings.get("betting_logs_retention_days"),
                            "betting_payouts": settings.get("betting_logs_retention_days"),
                            "betting_matches": settings.get("betting_match_retention_days"),
                        }

                        if optional_cutoffs["job_runs"]:
                            deleted["job_runs"] += await self._delete_in_batches(
                                session,
                                JobRun,
                                (JobRun.guild_id == guild_id)
                                & (JobRun.ran_at < now - dt.timedelta(days=int(optional_cutoffs["job_runs"]))),
                            )

                        if optional_cutoffs["tavern_purchase_logs"]:
                            deleted["tavern_purchase_logs"] += await self._delete_in_batches(
                                session,
                                TavernPurchaseLog,
                                (TavernPurchaseLog.guild_id == guild_id)
                                & (TavernPurchaseLog.purchased_at < now - dt.timedelta(days=int(optional_cutoffs["tavern_purchase_logs"]))),
                            )

                        if optional_cutoffs["betting_bets"]:
                            cutoff = now - dt.timedelta(days=int(optional_cutoffs["betting_bets"]))
                            deleted["betting_bets"] += await self._delete_in_batches(
                                session,
                                BettingBet,
                                (BettingBet.guild_id == guild_id) & (BettingBet.created_at < cutoff),
                            )
                            deleted["betting_payouts"] += await self._delete_in_batches(
                                session,
                                BettingPayout,
                                (BettingPayout.guild_id == guild_id) & (BettingPayout.created_at < cutoff),
                            )

                        if optional_cutoffs["betting_matches"]:
                            deleted["betting_matches"] += await self._delete_in_batches(
                                session,
                                BettingMatch,
                                (BettingMatch.guild_id == guild_id)
                                & (BettingMatch.created_at < now - dt.timedelta(days=int(optional_cutoffs["betting_matches"]))),
                            )

                        deleted["power_drift_logs"] += await self._delete_in_batches(
                            session,
                            PowerDriftLog,
                            (PowerDriftLog.guild_id == guild_id) & (PowerDriftLog.day < power_drift_cutoff),
                        )
                        deleted["inactive_buffs"] += await self._delete_in_batches(
                            session,
                            UserBuff,
                            (UserBuff.guild_id == guild_id)
                            & (UserBuff.active.is_(False))
                            & (UserBuff.ends_at < now - dt.timedelta(days=int(settings.get("inactive_buff_retention_days", 30)))),
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
            "power_drift_retention_days": int(scheduler.get("power_drift_retention_days", 600)),
            "job_runs_retention_days": scheduler.get("job_runs_retention_days"),
            "tavern_purchase_retention_days": scheduler.get("tavern_purchase_retention_days"),
            "betting_logs_retention_days": scheduler.get("betting_logs_retention_days"),
            "betting_match_retention_days": scheduler.get("betting_match_retention_days"),
            "inactive_buff_retention_days": int(scheduler.get("inactive_buff_retention_days", 30)),
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

    @tasks.loop(hours=1)
    async def buff_expiry_task(self) -> None:
        async def _job() -> None:
            async with self.bot.db.session() as session:
                async with session.begin():
                    deactivated = await BuffService(session).deactivate_expired_buffs()
                    tavern_cleaned = await TavernService(session).cleanup_expired_loadouts()
                    if deactivated > 0:
                        logger.info("Expired buffs deactivated", extra={"count": deactivated})
                    if tavern_cleaned > 0:
                        logger.info("Expired tavern loadouts cleaned", extra={"count": tavern_cleaned})

        await self._run_task("buff_expiry_task", _job)


    def _pick_presence_guild(self, settings: dict):
        if not self.bot.guilds:
            return None
        mode = settings.get("mode", "primary_guild")
        if mode == "primary_guild":
            primary_id = settings.get("primary_guild_id")
            if primary_id:
                guild = self.bot.get_guild(int(primary_id))
                if guild is not None:
                    return guild
            return self.bot.guilds[0]

        guilds = list(self.bot.guilds)
        if not guilds:
            return None
        guild = guilds[self._presence_guild_idx % len(guilds)]
        self._presence_guild_idx = (self._presence_guild_idx + 1) % max(len(guilds), 1)
        return guild

    @tasks.loop(seconds=60)
    async def presence_task(self) -> None:
        async def _job() -> None:
            now = dt.datetime.utcnow()
            if now < self._presence_next_run:
                return
            async with self.bot.db.session() as session:
                settings = await PresenceSettingsService.get(session)
                if not settings.get("enabled", True):
                    self._presence_next_run = now + dt.timedelta(seconds=60)
                    return

                guild = self._pick_presence_guild(settings)
                if guild is None:
                    self._presence_next_run = now + dt.timedelta(seconds=60)
                    return

                templates = settings.get("templates", [])
                if not templates:
                    self._presence_next_run = now + dt.timedelta(seconds=60)
                    return

                context = await self._presence_provider.get_context(session, guild)
                rendered = None
                chosen = None
                for _ in range(len(templates)):
                    idx = self._presence_template_idx % len(templates)
                    candidate = templates[idx]
                    self._presence_template_idx = (self._presence_template_idx + 1) % max(len(templates), 1)
                    text = render_presence_text(str(candidate.get("text", "")), context)
                    if text:
                        rendered = text
                        chosen = candidate
                        break

                if not rendered or chosen is None:
                    self._presence_next_run = now + dt.timedelta(seconds=int(settings.get("interval_seconds", 300)))
                    return

                await self.bot.change_presence(activity=to_activity(str(chosen.get("type", "playing")), rendered))
                self._presence_next_run = now + dt.timedelta(seconds=int(settings.get("interval_seconds", 300)))

        await self._run_task("presence_task", _job)


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


    @tasks.loop(minutes=1)
    async def betting_scheduling_task(self) -> None:
        async def _job() -> None:
            now = dt.datetime.utcnow()
            async with self.bot.db.session() as session:
                result = await session.execute(select(GuildConfig))
                configs = result.scalars().all()

            for config in configs:
                guild_id = int(config.guild_id)

                async def _guild_job() -> None:
                    async with self.bot.db.session() as guild_session:
                        async with guild_session.begin():
                            service = BettingService(guild_session)
                            settings = await service._get_betting_settings(guild_id)
                            scheduling = settings.get("scheduling", {})
                            auto_apply = scheduling.get("auto_apply", {})
                            run_every = max(1, int(auto_apply.get("run_every_minutes", 30)))
                            next_auto_apply = self._betting_auto_apply_next.get(guild_id)

                            inserted = 0
                            if next_auto_apply is None or now >= next_auto_apply:
                                inserted = await ensure_scheduling_horizon(session=guild_session, guild_id=guild_id, now=now)
                                self._betting_auto_apply_next[guild_id] = now + dt.timedelta(minutes=run_every)

                            opened, closed = await update_match_statuses(session=guild_session, guild_id=guild_id, now=now)
                            automation = await run_betting_automation_tick(session=guild_session, bot=self.bot, guild_id=guild_id, now=now)
                            drift_applied = 0
                            if bool(settings.get("power_drift", {}).get("enabled", True)):
                                drift_applied = await apply_power_drift_for_guild(session=guild_session, guild_id=guild_id, now=now)
                            if inserted or opened or closed or drift_applied or any(automation.values()):
                                logger.info(
                                    "Betting scheduling tick applied",
                                    extra={
                                        "guild_id": guild_id,
                                        "inserted": inserted,
                                        "opened": opened,
                                        "closed": closed,
                                        "power_drift_applied": drift_applied,
                                        "open_announced": automation.get("open_announced", 0),
                                        "close_announced": automation.get("close_announced", 0),
                                        "auto_resolved": automation.get("auto_resolved", 0),
                                    },
                                )

                await self._run_task(f"betting_power_drift_{guild_id}", _guild_job)

        await self._run_task("betting_scheduling_task", _job)

    @tasks.loop(minutes=10)
    async def monthly_reports_task(self) -> None:
        await self._run_task("monthly_reports_task", self.monthly_reports_service.run_scheduler_tick)

    @tasks.loop(minutes=30)
    async def rituals_task(self) -> None:
        await self._run_task("rituals_task", self.rituals_service.run_scheduler_tick)

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
    @rituals_task.before_loop
    @pvp_seasons_task.before_loop
    @betting_scheduling_task.before_loop
    @monthly_community_goals_v2_task.before_loop
    @buff_expiry_task.before_loop
    @presence_task.before_loop
    async def before_tasks(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
