from __future__ import annotations

import datetime as dt
import random
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.betting import core
from bot.betting.enums import BettingBetStatus, BettingMatchStatus
from bot.betting.models import BettingBet, BettingMatch, BettingTeam
from bot.database.operations import get_or_create_user_locked
from bot.services.economy import EconomyService


class BettingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_match(
        self,
        *,
        team_a_id: int,
        team_b_id: int,
        betting_open_at: dt.datetime,
        betting_close_at: dt.datetime,
        min_odds: float = 1.1,
        max_odds: float = 5.0,
        randomness: float = 0.05,
        power_influence: float = 1.0,
        now: dt.datetime | None = None,
    ) -> BettingMatch:
        if team_a_id == team_b_id:
            raise ValueError("Нужны две разные команды.")
        if betting_close_at <= betting_open_at:
            raise ValueError("Время закрытия должно быть позже открытия.")
        team_a = await self._get_team(team_a_id)
        team_b = await self._get_team(team_b_id)
        odds_a, odds_b = core.generate_odds(
            core.Team(team_a.id, team_a.name, float(team_a.current_power)),
            core.Team(team_b.id, team_b.name, float(team_b.current_power)),
            min_odds,
            max_odds,
            randomness,
            power_influence,
        )
        now = now or dt.datetime.utcnow()
        status = _match_status_for_window(betting_open_at, betting_close_at, now)
        match = BettingMatch(
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            odds_a=odds_a,
            odds_b=odds_b,
            betting_open_at=betting_open_at,
            betting_close_at=betting_close_at,
            status=status,
        )
        self.session.add(match)
        await self.session.flush()
        return match

    async def get_active_matches(self, now: dt.datetime) -> list[BettingMatch]:
        result = await self.session.execute(
            select(BettingMatch).where(
                (BettingMatch.betting_open_at <= now)
                & (BettingMatch.betting_close_at > now)
                & (BettingMatch.resolved_at.is_(None))
                & (BettingMatch.status != BettingMatchStatus.resolved)
            )
        )
        return list(result.scalars().all())

    async def place_bet(
        self,
        *,
        guild_id: int,
        user_id: int,
        match_id: int,
        team_id: int,
        amount: int,
        now: dt.datetime | None = None,
    ) -> BettingBet:
        if amount <= 0:
            raise ValueError("Ставка должна быть больше 0.")
        match, team_a, team_b = await self._get_match_with_teams(match_id, lock_match=True)
        now = now or dt.datetime.utcnow()
        expected_status = _match_status_for_window(
            match.betting_open_at, match.betting_close_at, now
        )
        if match.status != BettingMatchStatus.resolved and match.status != expected_status:
            match.status = expected_status
        if not core.is_betting_open(
            core.Match(
                match.id,
                core.Team(team_a.id, team_a.name, float(team_a.current_power)),
                core.Team(team_b.id, team_b.name, float(team_b.current_power)),
                match.betting_open_at,
                match.betting_close_at,
                match.resolved_at,
                match.odds_a,
                match.odds_b,
                None,
            ),
            now,
        ):
            raise ValueError("Ставки на матч закрыты.")
        if team_id not in {team_a.id, team_b.id}:
            raise ValueError("Неверная команда для ставки.")
        odds = match.odds_a if team_id == team_a.id else match.odds_b
        if odds is None:
            raise ValueError("Коэффициенты еще не готовы.")
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
            user_id=user_id,
            match_id=match.id,
            team_id=team_id,
            amount=amount,
            odds_at_bet=odds,
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
        match, team_a, team_b = await self._get_match_with_teams(match_id, lock_match=True)
        if match.status == BettingMatchStatus.resolved:
            return match
        now = now or dt.datetime.utcnow()
        if now < match.betting_close_at:
            raise ValueError("Матч еще не завершен.")
        core_match = core.Match(
            match.id,
            core.Team(team_a.id, team_a.name, float(team_a.current_power)),
            core.Team(team_b.id, team_b.name, float(team_b.current_power)),
            match.betting_open_at,
            match.betting_close_at,
            match.resolved_at,
            match.odds_a,
            match.odds_b,
            None,
        )
        winner = core.resolve_match(core_match)
        match.resolved_at = now
        match.status = BettingMatchStatus.resolved
        match.winner_team_id = winner.id
        await self._settle_bets(guild_id=guild_id, match=match, core_match=core_match)
        await self.session.flush()
        return match

    async def reset_team_ratings(
        self,
        *,
        delta_min: int = -5,
        delta_max: int = 5,
    ) -> Iterable[BettingTeam]:
        if delta_min > delta_max:
            raise ValueError("Некорректный диапазон для пересчета рейтингов.")
        result = await self.session.execute(
            select(BettingTeam).where(BettingTeam.is_active.is_(True))
        )
        teams = list(result.scalars().all())
        for team in teams:
            delta = random.randint(delta_min, delta_max)
            team.current_power = max(1, team.base_power + delta)
        await self.session.flush()
        return teams

    async def _get_team(self, team_id: int) -> BettingTeam:
        result = await self.session.execute(
            select(BettingTeam).where(
                (BettingTeam.id == team_id) & (BettingTeam.is_active.is_(True))
            )
        )
        team = result.scalars().first()
        if team is None:
            raise ValueError("Команда не найдена или не активна.")
        return team

    async def _get_match_with_teams(
        self,
        match_id: int,
        *,
        lock_match: bool = False,
    ) -> tuple[BettingMatch, BettingTeam, BettingTeam]:
        statement = select(BettingMatch).where(BettingMatch.id == match_id)
        if lock_match:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        match = result.scalars().first()
        if match is None:
            raise ValueError("Матч не найден.")
        team_a = await self._get_team(match.team_a_id)
        team_b = await self._get_team(match.team_b_id)
        return match, team_a, team_b

    async def _settle_bets(
        self,
        *,
        guild_id: int,
        match: BettingMatch,
        core_match: core.Match,
    ) -> None:
        result = await self.session.execute(
            select(BettingBet)
            .where(
                (BettingBet.match_id == match.id)
                & (BettingBet.status == BettingBetStatus.pending)
            )
            .with_for_update()
        )
        bets = list(result.scalars().all())
        economy = EconomyService(self.session)
        for bet in bets:
            payout_value = core.calculate_payout(
                core.Bet(
                    user_id=bet.user_id,
                    match_id=bet.match_id,
                    team_id=bet.team_id,
                    amount=float(bet.amount),
                ),
                core_match,
            )
            payout_int = int(payout_value)
            if payout_int > 0:
                await economy.bet_win(
                    guild_id=guild_id,
                    user_id=bet.user_id,
                    amount=payout_int,
                    source="betting_win",
                    reference_id=match.id,
                    metadata={"bet_id": bet.id},
                )
                bet.status = BettingBetStatus.won
            else:
                bet.status = BettingBetStatus.lost
            bet.payout = payout_int


def _match_status_for_window(
    betting_open_at: dt.datetime,
    betting_close_at: dt.datetime,
    now: dt.datetime,
) -> BettingMatchStatus:
    if now < betting_open_at:
        return BettingMatchStatus.scheduled
    if betting_open_at <= now < betting_close_at:
        return BettingMatchStatus.open
    return BettingMatchStatus.closed


async def auto_resolve_finished_matches(
    *,
    session: AsyncSession,
    guild_id: int,
    now: dt.datetime | None = None,
) -> list[BettingMatch]:
    now = now or dt.datetime.utcnow()
    service = BettingService(session)
    result = await session.execute(
        select(BettingMatch.id).where(
            (BettingMatch.status != BettingMatchStatus.resolved)
            & (BettingMatch.betting_close_at <= now)
        )
    )
    match_ids = [match_id for (match_id,) in result.all()]
    resolved_matches: list[BettingMatch] = []
    for match_id in match_ids:
        resolved_matches.append(
            await service.resolve_match(guild_id=guild_id, match_id=match_id, now=now)
        )
    return resolved_matches
