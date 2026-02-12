from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import discord
from sqlalchemy.ext.asyncio import AsyncSession

from bot.reports.betting import build_betting_report_metrics


@dataclass(frozen=True)
class QuarterlyPeriod:
    period_start_utc: dt.datetime
    period_end_utc: dt.datetime
    year: int
    quarter: int


def _quarter_bounds_local(*, year: int, quarter: int, tz_name: str) -> tuple[dt.datetime, dt.datetime]:
    tz = ZoneInfo(tz_name)
    start_month = ((quarter - 1) * 3) + 1
    start_local = dt.datetime(year, start_month, 1, tzinfo=tz)
    end_month = start_month + 3
    end_year = year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    end_local = dt.datetime(end_year, end_month, 1, tzinfo=tz)
    return start_local, end_local


def calculate_quarter_period(*, tz_name: str, spec: str = "prev", now_utc: dt.datetime | None = None) -> QuarterlyPeriod:
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    local_now = now.astimezone(ZoneInfo(tz_name))

    if spec == "current":
        year = local_now.year
        quarter = ((local_now.month - 1) // 3) + 1
    elif spec == "prev":
        current_q = ((local_now.month - 1) // 3) + 1
        if current_q == 1:
            year = local_now.year - 1
            quarter = 4
        else:
            year = local_now.year
            quarter = current_q - 1
    else:
        try:
            year_str, quarter_str = spec.split("-", 1)
            year = int(year_str)
            quarter = int(quarter_str.removeprefix("Q"))
        except Exception as exc:
            raise ValueError("quarter must be prev|current|YYYY-Qn") from exc
        if quarter not in {1, 2, 3, 4}:
            raise ValueError("quarter must be prev|current|YYYY-Qn")

    start_local, end_local = _quarter_bounds_local(year=year, quarter=quarter, tz_name=tz_name)
    return QuarterlyPeriod(
        period_start_utc=start_local.astimezone(dt.timezone.utc).replace(tzinfo=None),
        period_end_utc=end_local.astimezone(dt.timezone.utc).replace(tzinfo=None),
        year=year,
        quarter=quarter,
    )


async def build_quarterly_payload(
    session: AsyncSession,
    *,
    guild_id: int,
    period_start: dt.datetime,
    period_end: dt.datetime,
    tz: str,
    include_sections: dict[str, bool] | None = None,
) -> dict:
    include = include_sections or {}
    local_start = period_start.replace(tzinfo=dt.timezone.utc).astimezone(ZoneInfo(tz))
    quarter = ((local_start.month - 1) // 3) + 1
    payload: dict[str, object] = {
        "guild_id": guild_id,
        "timezone": tz,
        "period_start": period_start.isoformat() + "Z",
        "period_end": period_end.isoformat() + "Z",
        "year": local_start.year,
        "quarter": quarter,
        "quarter_label": f"Q{quarter} {local_start.year}",
    }
    if include.get("betting", True):
        payload["betting"] = await build_betting_report_metrics(
            session,
            guild_id=guild_id,
            period_start=period_start,
            period_end=period_end,
        )
    return payload


def build_quarterly_embed(payload: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"Итоги квартала: {payload.get('quarter_label', '—')}",
        color=discord.Color.blurple(),
        timestamp=dt.datetime.utcnow(),
    )
    betting = payload.get("betting") or {}
    if betting:
        biggest = betting.get("biggest_win") or {}
        top_bettors = "\n".join([f"• <@{row['user_id']}> — {int(row['volume'])}" for row in betting.get("top_bettors_by_volume", [])[:5]]) or "—"
        embed.add_field(
            name="🎲 Ставки",
            value=(
                f"Объём ставок: **{int(betting.get('total_volume', 0))}**\n"
                f"Выплачено: **{int(betting.get('total_payout', 0))}**\n"
                f"Профит игроков: **{int(betting.get('users_net_profit', 0))}**\n"
                f"Системный net-sink: **{int(betting.get('system_net_sink', 0))}**\n"
                f"Biggest win: **{int(biggest.get('payout', 0))}** (<@{biggest.get('user_id') or '—'}>)\n"
                f"Топ по объёму:\n{top_bettors}"
            ),
            inline=False,
        )
    embed.set_footer(text="Сформировано автоматически • AniBot")
    return embed
