from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import discord
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import GuildReport, GuildMonthlyGoal
from bot.reports.monthly import build_monthly_payload


@dataclass(frozen=True)
class YearlyPeriod:
    period_start_utc: dt.datetime
    period_end_utc: dt.datetime
    year: int


def calculate_previous_year_period(*, tz_name: str, now_utc: dt.datetime | None = None) -> YearlyPeriod:
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz)
    previous_year = local_now.year - 1

    year_start_local = dt.datetime(previous_year, 1, 1, tzinfo=tz)
    year_end_local = dt.datetime(previous_year + 1, 1, 1, tzinfo=tz)

    start_utc = year_start_local.astimezone(dt.timezone.utc).replace(tzinfo=None)
    end_utc = year_end_local.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return YearlyPeriod(period_start_utc=start_utc, period_end_utc=end_utc, year=previous_year)


def _month_period(*, year: int, month: int, tz_name: str) -> tuple[dt.datetime, dt.datetime]:
    tz = ZoneInfo(tz_name)
    month_start_local = dt.datetime(year, month, 1, tzinfo=tz)
    next_month_local = dt.datetime(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1, tzinfo=tz)
    start_utc = month_start_local.astimezone(dt.timezone.utc).replace(tzinfo=None)
    end_utc = next_month_local.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def _sum_section(monthly_payloads: list[dict], section: str, key: str) -> int:
    return int(sum(int((p.get(section) or {}).get(key, 0)) for p in monthly_payloads))


def _merge_top_list(monthly_payloads: list[dict], section: str, key: str, value_key: str) -> list[dict]:
    acc: dict[int, int] = defaultdict(int)
    for payload in monthly_payloads:
        for item in (payload.get(section) or {}).get(key, []):
            user_id = item.get("user_id")
            if user_id is None:
                continue
            acc[int(user_id)] += int(item.get(value_key, 0))

    sorted_items = sorted(acc.items(), key=lambda x: x[1], reverse=True)[:5]
    return [{"user_id": user_id, value_key: value} for user_id, value in sorted_items]


def _merge_keyed_counts(monthly_payloads: list[dict], section: str, key: str, value_key: str) -> list[dict]:
    acc: dict[str, int] = defaultdict(int)
    for payload in monthly_payloads:
        language = payload.get(section) or {}
        for item in language.get(key, []):
            k = str(item.get(value_key, "")).strip()
            if not k:
                continue
            acc[k] += int(item.get("count", 0))
    top = sorted(acc.items(), key=lambda x: x[1], reverse=True)[:10]
    field_name = "token" if key == "top_words" else "emoji_key"
    return [{field_name: k, "count": v} for k, v in top]


def _build_highlights(monthly_payloads: list[dict]) -> dict:
    best_month = None
    best_score = -1
    biggest_bet_win = 0
    biggest_bet_win_month = None
    biggest_pvp_streak = 0
    biggest_pvp_streak_month = None

    for payload in monthly_payloads:
        label = str(payload.get("period_start", ""))[:7]
        activity = payload.get("activity") or {}
        score = int(activity.get("total_messages", 0)) + int(activity.get("total_voice_minutes", 0))
        if score > best_score:
            best_score = score
            best_month = label

        betting = payload.get("betting") or {}
        win = int((betting.get("biggest_win") or {}).get("payout", 0))
        if win > biggest_bet_win:
            biggest_bet_win = win
            biggest_bet_win_month = label

        pvp = payload.get("pvp") or {}
        streak = int(pvp.get("longest_streak", 0))
        if streak > biggest_pvp_streak:
            biggest_pvp_streak = streak
            biggest_pvp_streak_month = label

    return {
        "best_month_by_activity": {"month": best_month, "score": best_score if best_score > 0 else 0},
        "biggest_bet_win": {"amount": biggest_bet_win, "month": biggest_bet_win_month},
        "biggest_pvp_streak": {"value": biggest_pvp_streak, "month": biggest_pvp_streak_month},
    }


def _aggregate_yearly_payload(
    *,
    guild_id: int,
    period_start: dt.datetime,
    period_end: dt.datetime,
    tz: str,
    include_sections: dict[str, bool],
    monthly_payloads: list[dict],
    source: str,
) -> dict:
    year = period_start.astimezone(ZoneInfo(tz)).year
    payload: dict[str, object] = {
        "guild_id": guild_id,
        "timezone": tz,
        "period_start": period_start.isoformat() + "Z",
        "period_end": period_end.isoformat() + "Z",
        "year": year,
        "year_label": str(year),
        "source": source,
        "months_covered": len(monthly_payloads),
    }

    if include_sections.get("messages", True) or include_sections.get("voice", True):
        payload["activity"] = {
            "total_messages": _sum_section(monthly_payloads, "activity", "total_messages"),
            "unique_chatters": max([int((p.get("activity") or {}).get("unique_chatters", 0)) for p in monthly_payloads] or [0]),
            "total_voice_minutes": _sum_section(monthly_payloads, "activity", "total_voice_minutes"),
            "unique_voice_users": max([int((p.get("activity") or {}).get("unique_voice_users", 0)) for p in monthly_payloads] or [0]),
        }

    if include_sections.get("economy", True):
        payload["economy"] = {
            "total_currency_earned": _sum_section(monthly_payloads, "economy", "total_currency_earned"),
            "total_currency_burned": _sum_section(monthly_payloads, "economy", "total_currency_burned"),
            "top_earners": _merge_top_list(monthly_payloads, "economy", "top_earners", "net_delta"),
        }

    if include_sections.get("betting", True):
        payload["betting"] = {
            "bets_count": _sum_section(monthly_payloads, "betting", "bets_count"),
            "unique_bettors": max([int((p.get("betting") or {}).get("unique_bettors", 0)) for p in monthly_payloads] or [0]),
            "total_volume": _sum_section(monthly_payloads, "betting", "total_volume"),
            "total_payout": _sum_section(monthly_payloads, "betting", "total_payout"),
            "users_net_profit": _sum_section(monthly_payloads, "betting", "users_net_profit"),
            "system_net_sink": _sum_section(monthly_payloads, "betting", "system_net_sink"),
            "top_bettors_by_volume": _merge_top_list(monthly_payloads, "betting", "top_bettors_by_volume", "volume"),
            "top_profitable": _merge_top_list(monthly_payloads, "betting", "top_profitable", "net_profit"),
            "biggest_win": max(
                [(p.get("betting") or {}).get("biggest_win", {}).get("payout", 0) for p in monthly_payloads] or [0]
            ),
        }

    if include_sections.get("pvp", True):
        payload["pvp"] = {
            "pvp_duels_count": _sum_section(monthly_payloads, "pvp", "pvp_duels_count"),
            "pvp_total_volume": _sum_section(monthly_payloads, "pvp", "pvp_total_volume"),
            "pvp_fees_burned": _sum_section(monthly_payloads, "pvp", "pvp_fees_burned"),
            "top_pvp_players": _merge_top_list(monthly_payloads, "pvp", "top_pvp_players", "wins"),
            "longest_streak": max([int((p.get("pvp") or {}).get("longest_streak", 0)) for p in monthly_payloads] or [0]),
        }

    if include_sections.get("moderation", True):
        payload["moderation"] = {
            "warnings_issued": _sum_section(monthly_payloads, "moderation", "warnings_issued"),
            "mutes_count": _sum_section(monthly_payloads, "moderation", "mutes_count"),
            "bans_count": _sum_section(monthly_payloads, "moderation", "bans_count"),
        }

    if include_sections.get("words", True) or include_sections.get("emojis", True) or include_sections.get("reactions", True):
        payload["language"] = {
            "top_words": _merge_keyed_counts(monthly_payloads, "language", "top_words", "token"),
            "top_emojis": _merge_keyed_counts(monthly_payloads, "language", "top_emojis", "emoji_key"),
            "top_reactions": _merge_keyed_counts(monthly_payloads, "language", "top_reactions", "emoji_key"),
        }


    payload["growth"] = {
        "promo_total_redemptions": _sum_section(monthly_payloads, "growth", "promo_total_redemptions"),
        "promo_total_payout": _sum_section(monthly_payloads, "growth", "promo_total_payout"),
        "referrals_pending": int((monthly_payloads[-1].get("growth") or {}).get("referrals_pending", 0)) if monthly_payloads else 0,
        "referrals_activated": _sum_section(monthly_payloads, "growth", "referrals_activated"),
        "referrals_total_rewards": _sum_section(monthly_payloads, "growth", "referrals_total_rewards"),
        "top_referrers": _merge_top_list(monthly_payloads, "growth", "top_referrers", "activations"),
    }

    payload["highlights"] = _build_highlights(monthly_payloads)
    return payload


async def build_yearly_payload(
    session: AsyncSession,
    *,
    guild_id: int,
    period_start: dt.datetime,
    period_end: dt.datetime,
    tz: str,
    include_sections: dict[str, bool] | None = None,
) -> dict:
    include = include_sections or {}
    year = period_start.astimezone(ZoneInfo(tz)).year
    expected_periods = {_month_period(year=year, month=month, tz_name=tz) for month in range(1, 13)}

    monthly_rows_result = await session.execute(
        select(GuildReport).where(
            (GuildReport.guild_id == guild_id)
            & (GuildReport.report_type == "monthly")
            & (GuildReport.period_start >= period_start)
            & (GuildReport.period_end <= period_end)
        )
    )
    monthly_rows = monthly_rows_result.scalars().all()

    reusable_payloads: list[dict] = []
    seen_periods: set[tuple[dt.datetime, dt.datetime]] = set()
    for row in monthly_rows:
        period_key = (row.period_start, row.period_end)
        if period_key not in expected_periods:
            continue
        if not isinstance(row.payload_json, dict):
            continue
        payload = row.payload_json
        if any(include.get(section, True) and section not in payload for section in ["activity", "economy", "betting", "pvp", "moderation", "language"]):
            reusable_payloads = []
            break
        reusable_payloads.append(payload)
        seen_periods.add(period_key)

    completed_goals_count = await session.scalar(
        select(func.count()).select_from(GuildMonthlyGoal).where(
            (GuildMonthlyGoal.guild_id == guild_id)
            & (GuildMonthlyGoal.started_at >= period_start)
            & (GuildMonthlyGoal.started_at < period_end)
            & (GuildMonthlyGoal.progress_value >= GuildMonthlyGoal.target_value)
        )
    )

    if len(reusable_payloads) == 12 and seen_periods == expected_periods:
        result_payload = _aggregate_yearly_payload(
            guild_id=guild_id,
            period_start=period_start,
            period_end=period_end,
            tz=tz,
            include_sections=include,
            monthly_payloads=sorted(reusable_payloads, key=lambda p: str(p.get("period_start", ""))),
            source="monthly_cache",
        )
        result_payload["monthly_goals_completed"] = int(completed_goals_count or 0)
        return result_payload

    computed_payloads: list[dict] = []
    for month in range(1, 13):
        month_start, month_end = _month_period(year=year, month=month, tz_name=tz)
        payload = await build_monthly_payload(
            session,
            guild_id=guild_id,
            period_start=month_start,
            period_end=month_end,
            tz=tz,
            include_sections=include,
        )
        computed_payloads.append(payload)

    result_payload = _aggregate_yearly_payload(
        guild_id=guild_id,
        period_start=period_start,
        period_end=period_end,
        tz=tz,
        include_sections=include,
        monthly_payloads=computed_payloads,
        source="direct_db",
    )
    result_payload["monthly_goals_completed"] = int(completed_goals_count or 0)
    return result_payload


def build_yearly_embed(payload: dict) -> discord.Embed:
    year_label = payload.get("year_label") or payload.get("year") or "—"
    embed = discord.Embed(
        title=f"Итоги года: {year_label}",
        color=discord.Color.gold(),
        timestamp=dt.datetime.utcnow(),
    )

    activity = payload.get("activity") or {}
    if activity:
        embed.add_field(
            name="💬 Активность",
            value=(
                f"Сообщений: **{int(activity.get('total_messages', 0))}**\n"
                f"Войс (мин): **{int(activity.get('total_voice_minutes', 0))}**\n"
                f"Пиковый онлайн в чате (уник.): **{int(activity.get('unique_chatters', 0))}**"
            ),
            inline=False,
        )

    economy = payload.get("economy") or {}
    if economy:
        embed.add_field(
            name="💰 Экономика",
            value=(
                f"Заработано: **{int(economy.get('total_currency_earned', 0))}**\n"
                f"Сожжено: **{int(economy.get('total_currency_burned', 0))}**"
            ),
            inline=False,
        )

    betting = payload.get("betting") or {}
    if betting:
        embed.add_field(
            name="🎲 Ставки",
            value=(
                f"Объём ставок: **{int(betting.get('total_volume', 0))}**\n"
                f"Выплачено: **{int(betting.get('total_payout', 0))}**\n"
                f"Профит игроков: **{int(betting.get('users_net_profit', 0))}**\n"
                f"Системный net-sink: **{int(betting.get('system_net_sink', 0))}**\n"
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
                f"Макс. стрик: **{int(pvp.get('longest_streak', 0))}**"
            ),
            inline=False,
        )


    language = payload.get("language") or {}
    if language:
        words = "\n".join([f"• {w['token']}: {w['count']}" for w in language.get("top_words", [])[:10]]) or "—"
        emojis = "\n".join([f"• {e['emoji_key']}: {e['count']}" for e in language.get("top_emojis", [])[:10]]) or "—"
        embed.add_field(name="📝 Топ слов", value=words, inline=False)
        embed.add_field(name="😀 Топ эмодзи", value=emojis, inline=False)

    goals_completed = int(payload.get("monthly_goals_completed", 0) or 0)
    embed.add_field(name="🎯 Цели сообщества", value=f"Выполнено целей за год: **{goals_completed}**", inline=False)

    highlights = payload.get("highlights") or {}
    if highlights:
        best_month = highlights.get("best_month_by_activity") or {}
        best_bet = highlights.get("biggest_bet_win") or {}
        best_streak = highlights.get("biggest_pvp_streak") or {}
        embed.add_field(
            name="🌟 Хайлайты",
            value=(
                f"Самый активный месяц: **{best_month.get('month') or '—'}**\n"
                f"Самый большой выигрыш в ставках: **{int(best_bet.get('amount', 0))}** ({best_bet.get('month') or '—'})\n"
                f"Самый длинный PvP-стрик: **{int(best_streak.get('value', 0))}** ({best_streak.get('month') or '—'})"
            ),
            inline=False,
        )

    source = payload.get("source", "direct_db")
    embed.set_footer(text=f"Сформировано автоматически • AniBot • source={source}")
    return embed
