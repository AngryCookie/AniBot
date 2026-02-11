from __future__ import annotations

from bot.analytics.activity_metrics import get_activity_daily_stats, get_activity_metrics
from bot.analytics.betting_metrics import get_betting_daily_stats, get_betting_metrics
from bot.analytics.economy_metrics import get_economy_daily_flow, get_economy_metrics
from bot.analytics.pvp_metrics import get_pvp_metrics
from bot.analytics.referral_metrics import get_referral_metrics


class AnalyticsService:
    """Orchestrates analytics submodules for a unified guild report."""

    def __init__(self, database) -> None:
        self.database = database

    async def get_full_analytics(self, guild_id: int, period_days: int) -> dict:
        """Return economy, betting and activity analytics for one guild."""
        async with self.database.session() as session:
            economy = await get_economy_metrics(session, guild_id, period_days)
            betting = await get_betting_metrics(session, guild_id, period_days)
            activity = await get_activity_metrics(session, guild_id, period_days)
            referrals = await get_referral_metrics(session, guild_id, period_days)
            pvp = await get_pvp_metrics(session, guild_id)

            economy_timeseries = await get_economy_daily_flow(session, guild_id, period_days)
            betting_timeseries = await get_betting_daily_stats(session, guild_id, period_days)
            activity_timeseries = await get_activity_daily_stats(session, guild_id, period_days)

        return {
            "economy": economy,
            "betting": betting,
            "activity": activity,
            "referrals": referrals,
            "pvp": pvp,
            "timeseries": {
                "economy": economy_timeseries,
                "betting": betting_timeseries,
                "activity": activity_timeseries,
            },
        }
