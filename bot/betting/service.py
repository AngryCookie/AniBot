from __future__ import annotations

import datetime as dt
import json
import math
import random
from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.betting import core
from bot.betting.enums import BettingBetStatus, BettingMatchStatus
from bot.betting.models import BettingBet, BettingMatch, BettingPayout, BettingTeam
from bot.database.models import ActivityEvent, GuildConfig
from bot.database.operations import get_or_create_user_locked
from bot.services.economy import EconomyService
from bot.ui import EmbedFactory


DEFAULT_BETTING_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "announce_channel_id": None,
    "min_bet_default": 50,
    "max_bet_default": 5000,
    "odds": {
        "min": 1.20,
        "max": 3.50,
        "randomness": 0.35,
        "power_influence": 0.50,
    },
    "resolve": {"power_weight": 0.60},
}


class BettingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def generate_odds(team_a_power: float, team_b_power: float, cfg: dict[str, Any]) -> tuple[float, float]:
        odds_cfg = cfg.get("odds", {}) if isinstance(cfg, dict) else {}
        min_odds = max(1.01, float(odds_cfg.get("min", 1.20)))
        max_odds = max(min_odds, float(odds_cfg.get("max", 3.50)))
        randomness = max(0.0, float(odds_cfg.get("randomness", 0.35)))
        influence = max(0.0, float(odds_cfg.get("power_influence", 0.5)))

        team_a = core.Team(id=1, name="A", power_rating=max(0.01, float(team_a_power)))
        team_b = core.Team(id=2, name="B", power_rating=max(0.01, float(team_b_power)))
        odds_a, odds_b = core.generate_odds(team_a, team_b, min_odds, max_odds, randomness, influence)
        return max(1.01, odds_a), max(1.01, odds_b)

    async def create_match(
        self,
        *,
        guild_id: int,
        team_a_id: int,
        team_b_id: int,
        betting_open_at: dt.datetime,
        betting_close_at: dt.datetime,
        min_bet: int | None = None,
        max_bet: int | None = None,
        announce_channel_id: int | None = None,
        now: dt.datetime | None = None,
    ) -> BettingMatch:
        if team_a_id == team_b_id:
            raise ValueError("Нужны две разные команды.")
        if betting_close_at <= betting_open_at:
            raise ValueError("Время закрытия должно быть позже открытия.")

        team_a = await self._get_team(guild_id, team_a_id)
        team_b = await self._get_team(guild_id, team_b_id)
        cfg = await self._get_betting_settings(guild_id)
        odds_a, odds_b = self.generate_odds(team_a.current_power, team_b.current_power, cfg)

        min_bet = int(min_bet if min_bet is not None else cfg.get("min_bet_default", 50))
        max_bet = int(max_bet if max_bet is not None else cfg.get("max_bet_default", 5000))
        if min_bet <= 0 or max_bet <= 0 or min_bet > max_bet:
            raise ValueError("Некорректные лимиты ставок.")

        now = now or dt.datetime.utcnow()
        match = BettingMatch(
            guild_id=guild_id,
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            odds_a=odds_a,
            odds_b=odds_b,
            betting_open_at=betting_open_at,
            betting_close_at=betting_close_at,
            min_bet=min_bet,
            max_bet=max_bet,
            announce_channel_id=announce_channel_id,
            status=_match_status_for_window(betting_open_at, betting_close_at, now),
        )
        self.session.add(match)
        await self.session.flush()
        return match

    async def list_matches(
        self,
        *,
        guild_id: int,
        status: BettingMatchStatus | None = None,
        start_date: dt.datetime | None = None,
        end_date: dt.datetime | None = None,
    ) -> list[BettingMatch]:
        query = select(BettingMatch).where(BettingMatch.guild_id == guild_id)
        if status:
            query = query.where(BettingMatch.status == status)
        if start_date:
            query = query.where(BettingMatch.betting_open_at >= start_date)
        if end_date:
            query = query.where(BettingMatch.betting_open_at <= end_date)
        result = await self.session.execute(query.order_by(BettingMatch.betting_open_at.desc()))
        return list(result.scalars().all())

    async def place_bet(
        self,
        guild_id: int,
        user_id: int,
        match_id: int,
        team_id: int,
        amount: int,
        now: dt.datetime | None = None,
    ) -> BettingBet:
        if amount <= 0:
            raise ValueError("Ставка должна быть больше 0.")
        match, team_a, team_b = await self._get_match_with_teams(guild_id, match_id, lock_match=True)
        now = now or dt.datetime.utcnow()
        expected_status = _match_status_for_window(match.betting_open_at, match.betting_close_at, now)
        if match.status != BettingMatchStatus.resolved and match.status != expected_status:
            match.status = expected_status

        if expected_status != BettingMatchStatus.open:
            raise ValueError("Ставки на матч закрыты.")
        if team_id not in {team_a.id, team_b.id}:
            raise ValueError("Неверная команда для ставки.")
        if amount < match.min_bet or amount > match.max_bet:
            raise ValueError(f"Сумма ставки должна быть в диапазоне {match.min_bet}-{match.max_bet}.")

        odds = match.odds_a if team_id == team_a.id else match.odds_b
        user = await get_or_create_user_locked(self.session, guild_id, user_id)
        if user.balance < amount:
            raise ValueError("Недостаточно средств.")

        await EconomyService(self.session).place_bet(
            guild_id=guild_id,
            user_id=user_id,
            amount=amount,
            source="betting_bet",
            reference_id=match.id,
            metadata={"team_id": team_id},
        )
        bet = BettingBet(
            guild_id=guild_id,
            user_id=user_id,
            match_id=match.id,
            team_id=team_id,
            amount=amount,
            odds=odds,
            status=BettingBetStatus.pending,
        )
        self.session.add(bet)
        await self.session.flush()
        return bet

    async def resolve_match(
        self,
        *,
        guild_id: int,
        match_id: int,
        now: dt.datetime | None = None,
    ) -> BettingMatch:
        match, team_a, team_b = await self._get_match_with_teams(guild_id, match_id, lock_match=True)
        if match.status == BettingMatchStatus.resolved:
            return match
        now = now or dt.datetime.utcnow()
        if now < match.betting_close_at:
            raise ValueError("Матч еще не завершен.")

        cfg = await self._get_betting_settings(guild_id)
        winner = self._choose_weighted_winner(team_a, team_b, cfg)
        match.resolved_at = now
        match.status = BettingMatchStatus.resolved
        match.winner_team_id = winner.id

        payout_total, volume_total, top_win = await self._settle_bets(guild_id=guild_id, match=match)
        self.session.add(
            ActivityEvent(
                guild_id=guild_id,
                user_id=0,
                event_type="betting_resolve",
                value=int(volume_total),
                metadata_json={
                    "match_id": match.id,
                    "betting_total_volume": int(volume_total),
                    "betting_total_payout": int(payout_total),
                    "betting_net_sink": int(volume_total - payout_total),
                    "top_win": int(top_win),
                },
            )
        )
        await self.session.flush()
        return match

    async def reset_team_ratings(self, *, guild_id: int, delta_min: int = -5, delta_max: int = 5) -> Iterable[BettingTeam]:
        if delta_min > delta_max:
            raise ValueError("Некорректный диапазон для пересчета рейтингов.")
        result = await self.session.execute(
            select(BettingTeam).where(and_(BettingTeam.guild_id == guild_id, BettingTeam.active.is_(True)))
        )
        teams = list(result.scalars().all())
        for team in teams:
            team.current_power = max(1, team.base_power + random.randint(delta_min, delta_max))
        await self.session.flush()
        return teams

    async def _get_team(self, guild_id: int, team_id: int) -> BettingTeam:
        result = await self.session.execute(
            select(BettingTeam).where(
                and_(BettingTeam.id == team_id, BettingTeam.guild_id == guild_id, BettingTeam.active.is_(True))
            )
        )
        team = result.scalars().first()
        if team is None:
            raise ValueError("Команда не найдена или не активна.")
        return team

    async def _get_match_with_teams(
        self,
        guild_id: int,
        match_id: int,
        *,
        lock_match: bool = False,
    ) -> tuple[BettingMatch, BettingTeam, BettingTeam]:
        query = select(BettingMatch).where(and_(BettingMatch.id == match_id, BettingMatch.guild_id == guild_id))
        if lock_match:
            query = query.with_for_update()
        match = (await self.session.execute(query)).scalars().first()
        if match is None:
            raise ValueError("Матч не найден.")
        team_a = await self._get_team(guild_id, match.team_a_id)
        team_b = await self._get_team(guild_id, match.team_b_id)
        return match, team_a, team_b

    async def _get_betting_settings(self, guild_id: int) -> dict[str, Any]:
        row = await self.session.get(GuildConfig, guild_id)
        payload = {}
        if row and row.settings:
            try:
                payload = json.loads(row.settings)
            except json.JSONDecodeError:
                payload = {}
        settings = dict(DEFAULT_BETTING_SETTINGS)
        settings.update(payload.get("betting", {}))
        settings["odds"] = {**DEFAULT_BETTING_SETTINGS["odds"], **settings.get("odds", {})}
        settings["resolve"] = {**DEFAULT_BETTING_SETTINGS["resolve"], **settings.get("resolve", {})}
        return settings

    def _choose_weighted_winner(self, team_a: BettingTeam, team_b: BettingTeam, cfg: dict[str, Any]) -> BettingTeam:
        power_weight = float(cfg.get("resolve", {}).get("power_weight", 0.60))
        diff = (float(team_a.current_power) - float(team_b.current_power)) / 100.0
        weighted = max(-10.0, min(10.0, diff * max(0.0, power_weight) * 5.0))
        p_team_a = math.exp(weighted) / (math.exp(weighted) + math.exp(-weighted))
        return team_a if random.random() < p_team_a else team_b

    async def _settle_bets(self, *, guild_id: int, match: BettingMatch) -> tuple[int, int, int]:
        rows = await self.session.execute(
            select(BettingBet)
            .where(and_(BettingBet.guild_id == guild_id, BettingBet.match_id == match.id, BettingBet.status == BettingBetStatus.pending))
            .with_for_update()
        )
        bets = list(rows.scalars().all())
        economy = EconomyService(self.session)
        payout_total = 0
        volume_total = 0
        top_win = 0
        for bet in bets:
            volume_total += int(bet.amount)
            payout_int = int(float(bet.amount) * float(bet.odds)) if bet.team_id == match.winner_team_id else 0
            if payout_int > 0:
                await economy.bet_win(
                    guild_id=guild_id,
                    user_id=bet.user_id,
                    amount=payout_int,
                    source="betting_win",
                    reference_id=match.id,
                    metadata={"bet_id": bet.id},
                )
                self.session.add(
                    BettingPayout(
                        guild_id=guild_id,
                        match_id=match.id,
                        user_id=bet.user_id,
                        bet_id=bet.id,
                        payout_amount=payout_int,
                    )
                )
                payout_total += payout_int
                top_win = max(top_win, payout_int)
                bet.status = BettingBetStatus.won
            else:
                bet.status = BettingBetStatus.lost
            bet.payout = payout_int
        return payout_total, volume_total, top_win


async def announce_match_result(*, bot, guild_id: int, match: BettingMatch, winner_name: str, volume_total: int, payout_total: int, top_win: int, channel_id: int | None = None) -> None:
    if bot is None:
        return
    target_channel_id = channel_id or match.announce_channel_id
    if not target_channel_id:
        return
    channel = bot.get_channel(int(target_channel_id))
    if channel is None:
        return
    embed = EmbedFactory.success("🎲 Результат матча")
    EmbedFactory.add_kv(embed, "🏆 Победитель", winner_name, inline=False)
    EmbedFactory.add_kv(embed, "💰 Общий пул ставок", str(int(volume_total)))
    EmbedFactory.add_kv(embed, "🎁 Выплачено", str(int(payout_total)))
    if top_win > 0:
        EmbedFactory.add_kv(embed, "🚀 Топ-выигрыш", str(int(top_win)), inline=False)
    try:
        await channel.send(embed=embed)
    except Exception:
        return


def _match_status_for_window(betting_open_at: dt.datetime, betting_close_at: dt.datetime, now: dt.datetime) -> BettingMatchStatus:
    if now < betting_open_at:
        return BettingMatchStatus.scheduled
    if betting_open_at <= now < betting_close_at:
        return BettingMatchStatus.open
    return BettingMatchStatus.closed


async def auto_resolve_finished_matches(*, session: AsyncSession, guild_id: int, now: dt.datetime | None = None) -> list[BettingMatch]:
    now = now or dt.datetime.utcnow()
    service = BettingService(session)
    ids = await session.execute(
        select(BettingMatch.id).where(
            and_(
                BettingMatch.guild_id == guild_id,
                BettingMatch.status != BettingMatchStatus.resolved,
                BettingMatch.betting_close_at <= now,
            )
        )
    )
    resolved_matches: list[BettingMatch] = []
    for (match_id,) in ids.all():
        resolved_matches.append(await service.resolve_match(guild_id=guild_id, match_id=match_id, now=now))
    return resolved_matches
