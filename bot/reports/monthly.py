from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import discord
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import (
    ActivityEvent,
    EconomyTransaction,
    EmojiStatDaily,
    ModLog,
    PvpDuel,
    ReactionStatDaily,
    Warning,
    WordStatDaily,
)
from bot.referral.models import PromoRedemptionV2, ReferralAttributionV2, ReferralRewardV2


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

    if include.get("words", True) or include.get("emojis", True) or include.get("reactions", True):
        payload["language"] = await _build_words_emojis(session, guild_id, period_start, period_end)

    payload["growth"] = await _build_growth(session, guild_id, period_start, period_end)
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


async def _build_words_emojis(session: AsyncSession, guild_id: int, start: dt.datetime, end: dt.datetime) -> dict:
    start_day = start.date()
    end_day_exclusive = end.date()

    words_result = await session.execute(
        select(
            WordStatDaily.token.label("key"),
            func.coalesce(func.sum(WordStatDaily.count), 0).label("total"),
        )
        .where(
            (WordStatDaily.guild_id == guild_id)
            & (WordStatDaily.day >= start_day)
            & (WordStatDaily.day < end_day_exclusive)
        )
        .group_by(WordStatDaily.token)
        .order_by(func.sum(WordStatDaily.count).desc())
        .limit(10)
    )
    emojis_result = await session.execute(
        select(
            EmojiStatDaily.emoji_key.label("key"),
            func.coalesce(func.sum(EmojiStatDaily.count), 0).label("total"),
        )
        .where(
            (EmojiStatDaily.guild_id == guild_id)
            & (EmojiStatDaily.day >= start_day)
            & (EmojiStatDaily.day < end_day_exclusive)
        )
        .group_by(EmojiStatDaily.emoji_key)
        .order_by(func.sum(EmojiStatDaily.count).desc())
        .limit(10)
    )
    reactions_result = await session.execute(
        select(
            ReactionStatDaily.emoji_key.label("key"),
            func.coalesce(func.sum(ReactionStatDaily.count), 0).label("total"),
        )
        .where(
            (ReactionStatDaily.guild_id == guild_id)
            & (ReactionStatDaily.day >= start_day)
            & (ReactionStatDaily.day < end_day_exclusive)
        )
        .group_by(ReactionStatDaily.emoji_key)
        .order_by(func.sum(ReactionStatDaily.count).desc())
        .limit(10)
    )

    return {
        "top_words": [{"token": str(r.key), "count": int(r.total or 0)} for r in words_result],
        "top_emojis": [{"emoji_key": str(r.key), "count": int(r.total or 0)} for r in emojis_result],
        "top_reactions": [{"emoji_key": str(r.key), "count": int(r.total or 0)} for r in reactions_result],
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

    language = payload.get("language") or {}
    if language:
        words = "\n".join([f"• {w['token']}: {w['count']}" for w in language.get("top_words", [])[:10]]) or "—"
        emojis = "\n".join([f"• {e['emoji_key']}: {e['count']}" for e in language.get("top_emojis", [])[:10]]) or "—"
        reactions = "\n".join([f"• {e['emoji_key']}: {e['count']}" for e in language.get("top_reactions", [])[:10]]) or "—"
        embed.add_field(name="📝 Топ слов", value=words, inline=False)
        embed.add_field(name="😀 Топ эмодзи", value=emojis, inline=False)
        embed.add_field(name="👍 Топ реакций", value=reactions, inline=False)

    embed.set_footer(text="Сформировано автоматически • AniBot")
    return embed


async def _build_growth(session: AsyncSession, guild_id: int, start: dt.datetime, end: dt.datetime) -> dict:
    promo_total_redemptions = await session.scalar(select(func.count()).select_from(PromoRedemptionV2).where(PromoRedemptionV2.guild_id == guild_id, PromoRedemptionV2.redeemed_at >= start, PromoRedemptionV2.redeemed_at < end))
    promo_total_payout = await session.scalar(select(func.coalesce(func.sum(PromoRedemptionV2.reward_amount), 0)).where(PromoRedemptionV2.guild_id == guild_id, PromoRedemptionV2.redeemed_at >= start, PromoRedemptionV2.redeemed_at < end))
    referrals_pending = await session.scalar(select(func.count()).select_from(ReferralAttributionV2).where(ReferralAttributionV2.guild_id == guild_id, ReferralAttributionV2.status == "pending"))
    referrals_activated = await session.scalar(select(func.count()).select_from(ReferralAttributionV2).where(ReferralAttributionV2.guild_id == guild_id, ReferralAttributionV2.status == "activated"))
    referrals_total_rewards = await session.scalar(select(func.coalesce(func.sum(ReferralRewardV2.reward_amount), 0)).where(ReferralRewardV2.guild_id == guild_id, ReferralRewardV2.rewarded_at >= start, ReferralRewardV2.rewarded_at < end))
    top_rows = await session.execute(select(ReferralAttributionV2.referrer_user_id, func.count(ReferralAttributionV2.id).label("count")).where(ReferralAttributionV2.guild_id == guild_id, ReferralAttributionV2.status == "activated").group_by(ReferralAttributionV2.referrer_user_id).order_by(func.count(ReferralAttributionV2.id).desc()).limit(5))
    return {
        "promo_total_redemptions": int(promo_total_redemptions or 0),
        "promo_total_payout": int(promo_total_payout or 0),
        "referrals_pending": int(referrals_pending or 0),
        "referrals_activated": int(referrals_activated or 0),
        "referrals_total_rewards": int(referrals_total_rewards or 0),
        "top_referrers": [{"user_id": int(r.referrer_user_id), "activations": int(r.count or 0)} for r in top_rows],
    }
