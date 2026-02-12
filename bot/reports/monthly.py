from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import discord
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ActivityEvent, EconomyTransaction, ModLog, PvpDuel, Warning


@dataclass(frozen=True)
class MonthlyPeriod:
    period_start_utc: dt.datetime
    period_end_utc: dt.datetime
    month_title: str


def calculate_previous_month_period(*, tz_name: str, now_utc: dt.datetime | None = None) -> MonthlyPeriod:
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz)
    current_month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_month_last_day = current_month_start - dt.timedelta(days=1)
    previous_month_start = previous_month_last_day.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    start_utc = previous_month_start.astimezone(dt.timezone.utc).replace(tzinfo=None)
    end_utc = current_month_start.astimezone(dt.timezone.utc).replace(tzinfo=None)
    month_title = previous_month_start.strftime("%B %Y")
    return MonthlyPeriod(period_start_utc=start_utc, period_end_utc=end_utc, month_title=month_title)


async def build_monthly_payload(
    session: AsyncSession,
    *,
    guild_id: int,
    period_start: dt.datetime,
    period_end: dt.datetime,
    tz: str,
    include_sections: dict[str, bool] | None = None,
) -> dict:
    include = include_sections or {}

    payload: dict[str, object] = {
        "guild_id": guild_id,
        "timezone": tz,
        "period_start": period_start.isoformat() + "Z",
        "period_end": period_end.isoformat() + "Z",
    }

    if include.get("messages", True) or include.get("voice", True):
        activity = await _build_activity(session, guild_id, period_start, period_end)
        payload["activity"] = activity

    if include.get("economy", True):
        payload["economy"] = await _build_economy(session, guild_id, period_start, period_end)

    if include.get("betting", True):
        payload["betting"] = await _build_betting(session, guild_id, period_start, period_end)

    if include.get("pvp", True):
        payload["pvp"] = await _build_pvp(session, guild_id, period_start, period_end)

    if include.get("moderation", True):
        payload["moderation"] = await _build_moderation(session, guild_id, period_start, period_end)

    return payload


async def _build_activity(session: AsyncSession, guild_id: int, start: dt.datetime, end: dt.datetime) -> dict:
    result = await session.execute(
        select(
            func.coalesce(func.sum(case((ActivityEvent.event_type == "message", ActivityEvent.value), else_=0)), 0),
            func.coalesce(func.count(func.distinct(case((ActivityEvent.event_type == "message", ActivityEvent.user_id), else_=None))), 0),
            func.coalesce(func.sum(case((ActivityEvent.event_type == "voice_minutes", ActivityEvent.value), else_=0)), 0),
            func.coalesce(func.count(func.distinct(case((ActivityEvent.event_type == "voice_minutes", ActivityEvent.user_id), else_=None))), 0),
        ).where(
            (ActivityEvent.guild_id == guild_id)
            & (ActivityEvent.created_at >= start)
            & (ActivityEvent.created_at < end)
        )
    )
    total_messages, unique_chatters, total_voice_minutes, unique_voice_users = result.one()
    return {
        "total_messages": int(total_messages or 0),
        "unique_chatters": int(unique_chatters or 0),
        "total_voice_minutes": int(total_voice_minutes or 0),
        "unique_voice_users": int(unique_voice_users or 0),
    }


async def _build_economy(session: AsyncSession, guild_id: int, start: dt.datetime, end: dt.datetime) -> dict:
    flow = await session.execute(
        select(
            func.coalesce(func.sum(case((EconomyTransaction.amount > 0, EconomyTransaction.amount), else_=0)), 0),
            func.coalesce(func.sum(case((EconomyTransaction.amount < 0, -EconomyTransaction.amount), else_=0)), 0),
        ).where(
            (EconomyTransaction.guild_id == guild_id)
            & (EconomyTransaction.created_at >= start)
            & (EconomyTransaction.created_at < end)
        )
    )
    earned, burned = flow.one()

    top = await session.execute(
        select(
            EconomyTransaction.user_id,
            func.coalesce(func.sum(EconomyTransaction.amount), 0).label("net"),
        )
        .where(
            (EconomyTransaction.guild_id == guild_id)
            & (EconomyTransaction.created_at >= start)
            & (EconomyTransaction.created_at < end)
        )
        .group_by(EconomyTransaction.user_id)
        .order_by(func.sum(EconomyTransaction.amount).desc())
        .limit(5)
    )
    top_earners = [{"user_id": int(r.user_id), "net_delta": int(r.net or 0)} for r in top.all()]
    return {
        "total_currency_earned": int(earned or 0),
        "total_currency_burned": int(burned or 0),
        "top_earners": top_earners,
    }


async def _build_betting(session: AsyncSession, guild_id: int, start: dt.datetime, end: dt.datetime) -> dict:
    result = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        ((EconomyTransaction.source == "bet_placement") & (EconomyTransaction.amount < 0), -EconomyTransaction.amount),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        ((EconomyTransaction.source == "bet_win") & (EconomyTransaction.amount > 0), EconomyTransaction.amount),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.max(
                    case(
                        ((EconomyTransaction.source == "bet_win") & (EconomyTransaction.amount > 0), EconomyTransaction.amount),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(
            (EconomyTransaction.guild_id == guild_id)
            & (EconomyTransaction.created_at >= start)
            & (EconomyTransaction.created_at < end)
        )
    )
    volume, payout, biggest_win = result.one()

    top_bettors_result = await session.execute(
        select(
            EconomyTransaction.user_id,
            func.coalesce(func.sum(-EconomyTransaction.amount), 0).label("volume"),
        )
        .where(
            (EconomyTransaction.guild_id == guild_id)
            & (EconomyTransaction.source == "bet_placement")
            & (EconomyTransaction.amount < 0)
            & (EconomyTransaction.created_at >= start)
            & (EconomyTransaction.created_at < end)
        )
        .group_by(EconomyTransaction.user_id)
        .order_by(func.sum(-EconomyTransaction.amount).desc())
        .limit(5)
    )
    top_bettors = [{"user_id": int(r.user_id), "volume": int(r.volume or 0)} for r in top_bettors_result.all()]
    volume_i = int(volume or 0)
    payout_i = int(payout or 0)
    return {
        "betting_total_volume": volume_i,
        "betting_total_payout": payout_i,
        "betting_net_sink": volume_i - payout_i,
        "top_bettors": top_bettors,
        "biggest_win": int(biggest_win or 0),
    }


async def _build_pvp(session: AsyncSession, guild_id: int, start: dt.datetime, end: dt.datetime) -> dict:
    result = await session.execute(
        select(
            func.coalesce(func.count(PvpDuel.id), 0),
            func.coalesce(func.sum(PvpDuel.amount * 2), 0),
            func.coalesce(func.sum((PvpDuel.amount * 2) * (PvpDuel.fee_percent / 100.0)), 0),
            func.coalesce(func.max(case((PvpDuel.winner_id.is_not(None), 1), else_=0)), 0),
        ).where(
            (PvpDuel.guild_id == guild_id)
            & (PvpDuel.status == "resolved")
            & (PvpDuel.resolved_at.is_not(None))
            & (PvpDuel.resolved_at >= start)
            & (PvpDuel.resolved_at < end)
        )
    )
    duels_count, total_volume, fees_burned, _ = result.one()

    winners = await session.execute(
        select(
            PvpDuel.winner_id,
            func.coalesce(func.count(PvpDuel.id), 0).label("wins"),
        )
        .where(
            (PvpDuel.guild_id == guild_id)
            & (PvpDuel.status == "resolved")
            & (PvpDuel.winner_id.is_not(None))
            & (PvpDuel.resolved_at >= start)
            & (PvpDuel.resolved_at < end)
        )
        .group_by(PvpDuel.winner_id)
        .order_by(func.count(PvpDuel.id).desc())
        .limit(5)
    )
    top_players = [{"user_id": int(r.winner_id), "wins": int(r.wins or 0)} for r in winners.all() if r.winner_id is not None]

    streaks = await session.execute(
        select(func.coalesce(func.max(case((PvpDuel.status == "resolved", 1), else_=0)), 0)).where(
            (PvpDuel.guild_id == guild_id)
            & (PvpDuel.resolved_at >= start)
            & (PvpDuel.resolved_at < end)
        )
    )
    longest_streak = int(streaks.scalar() or 0)

    return {
        "pvp_duels_count": int(duels_count or 0),
        "pvp_total_volume": int(total_volume or 0),
        "pvp_fees_burned": int(float(fees_burned or 0)),
        "top_pvp_players": top_players,
        "longest_streak": longest_streak,
    }


async def _build_moderation(session: AsyncSession, guild_id: int, start: dt.datetime, end: dt.datetime) -> dict:
    warnings_result = await session.execute(
        select(func.count(Warning.id)).where(
            (Warning.guild_id == guild_id)
            & (Warning.created_at >= start)
            & (Warning.created_at < end)
        )
    )
    mod_result = await session.execute(
        select(
            func.coalesce(func.sum(case((ModLog.action == "mute", 1), else_=0)), 0),
            func.coalesce(func.sum(case((ModLog.action == "ban", 1), else_=0)), 0),
        ).where(
            (ModLog.guild_id == guild_id)
            & (ModLog.created_at >= start)
            & (ModLog.created_at < end)
        )
    )
    mutes_count, bans_count = mod_result.one()
    return {
        "warnings_issued": int(warnings_result.scalar() or 0),
        "mutes_count": int(mutes_count or 0),
        "bans_count": int(bans_count or 0),
    }


def build_monthly_embed(payload: dict) -> discord.Embed:
    period_start = payload.get("period_start", "")
    title_month = period_start[:7] if isinstance(period_start, str) else ""
    embed = discord.Embed(
        title=f"Итоги месяца: {title_month}",
        color=discord.Color.purple(),
        timestamp=dt.datetime.utcnow(),
    )

    activity = payload.get("activity") or {}
    if activity:
        embed.add_field(
            name="💬 Активность",
            value=(
                f"Сообщений: **{int(activity.get('total_messages', 0))}**\n"
                f"Участников чата: **{int(activity.get('unique_chatters', 0))}**\n"
                f"Войс (мин): **{int(activity.get('total_voice_minutes', 0))}**"
            ),
            inline=False,
        )

    economy = payload.get("economy") or {}
    if economy:
        embed.add_field(
            name="💰 Экономика",
            value=(
                f"Заработано: **{int(economy.get('total_currency_earned', 0))}**\n"
                f"Сожжено: **{int(economy.get('total_currency_burned', 0))}**\n"
                f"Топ заработка: {json.dumps(economy.get('top_earners', []), ensure_ascii=False)}"
            ),
            inline=False,
        )

    betting = payload.get("betting") or {}
    if betting:
        embed.add_field(
            name="🎲 Ставки",
            value=(
                f"Оборот: **{int(betting.get('betting_total_volume', 0))}**\n"
                f"Выплаты: **{int(betting.get('betting_total_payout', 0))}**\n"
                f"Крупнейший выигрыш: **{int(betting.get('biggest_win', 0))}**"
            ),
            inline=False,
        )

    pvp = payload.get("pvp") or {}
    if pvp:
        embed.add_field(
            name="⚔️ PvP",
            value=(
                f"Дуэлей: **{int(pvp.get('pvp_duels_count', 0))}**\n"
                f"Оборот: **{int(pvp.get('pvp_total_volume', 0))}**\n"
                f"Комиссии: **{int(pvp.get('pvp_fees_burned', 0))}**"
            ),
            inline=False,
        )

    moderation = payload.get("moderation") or {}
    if moderation:
        embed.add_field(
            name="🛡️ Модерация",
            value=(
                f"Варны: **{int(moderation.get('warnings_issued', 0))}**\n"
                f"Муты: **{int(moderation.get('mutes_count', 0))}**\n"
                f"Баны: **{int(moderation.get('bans_count', 0))}**"
            ),
            inline=False,
        )

    embed.set_footer(text="Сформировано автоматически • AniBot")
    return embed
