"""Core betting logic for AniBot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import random
from typing import Tuple


@dataclass(frozen=True)
class Team:
    """Represents a team with a power rating used for odds and outcomes."""

    id: int
    name: str
    power_rating: float


@dataclass
class Match:
    """Represents a match between two teams with betting metadata."""

    id: int
    team_a: Team
    team_b: Team
    betting_open_at: datetime
    betting_close_at: datetime
    resolved_at: datetime | None
    odds_a: float | None
    odds_b: float | None
    winner: Team | None


@dataclass(frozen=True)
class Bet:
    """Represents a user's bet on a match and team."""

    user_id: int
    match_id: int
    team_id: int
    amount: float


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a value to a specified range."""

    return max(minimum, min(maximum, value))


def generate_odds(
    team_a: Team,
    team_b: Team,
    min_odds: float,
    max_odds: float,
    randomness: float,
    power_influence: float,
) -> Tuple[float, float]:
    """Generate decimal odds for two teams based on power ratings and randomness."""

    if min_odds <= 0 or max_odds <= 0:
        raise ValueError("Odds bounds must be positive.")
    if min_odds > max_odds:
        raise ValueError("min_odds cannot exceed max_odds.")

    influence = max(0.0, power_influence)
    rating_a = max(0.01, team_a.power_rating) ** influence
    rating_b = max(0.01, team_b.power_rating) ** influence

    total = rating_a + rating_b
    prob_a = rating_a / total
    prob_b = rating_b / total

    noise = max(0.0, randomness)
    if noise > 0:
        shift = random.uniform(-noise, noise)
        prob_a = _clamp(prob_a + shift, 0.01, 0.99)
        prob_b = 1.0 - prob_a

    odds_a = 1.0 / prob_a
    odds_b = 1.0 / prob_b

    odds_a = _clamp(odds_a, min_odds, max_odds)
    odds_b = _clamp(odds_b, min_odds, max_odds)

    return odds_a, odds_b


def resolve_match(match: Match) -> Team:
    """Resolve a match by selecting a winner using weighted randomness."""

    weight_a = max(0.01, match.team_a.power_rating)
    weight_b = max(0.01, match.team_b.power_rating)
    choice = random.choices(
        [match.team_a, match.team_b], weights=[weight_a, weight_b], k=1
    )[0]
    match.winner = choice
    match.resolved_at = match.resolved_at or datetime.utcnow()
    return choice


def calculate_payout(bet: Bet, match: Match) -> float:
    """Calculate the payout for a bet based on match outcome and odds."""

    if match.winner is None:
        return 0.0

    if bet.team_id == match.team_a.id:
        odds = match.odds_a
    elif bet.team_id == match.team_b.id:
        odds = match.odds_b
    else:
        return 0.0

    if odds is None:
        return 0.0

    if match.winner.id == bet.team_id:
        return bet.amount * odds
    return 0.0


def is_betting_open(match: Match, now: datetime) -> bool:
    """Check if betting is currently open for a match."""

    if match.resolved_at is not None and now >= match.resolved_at:
        return False
    return match.betting_open_at <= now < match.betting_close_at


def has_match_resolved(match: Match, now: datetime) -> bool:
    """Check if a match has resolved based on its resolved time."""

    return match.resolved_at is not None and now >= match.resolved_at


def validate_bet_amount(
    amount: float, min_amount: float, max_amount: float, user_balance: float
) -> bool:
    """Validate a bet amount against limits and user balance."""

    if amount <= 0:
        return False
    if min_amount < 0 or max_amount < 0:
        return False
    if min_amount > max_amount:
        return False
    if amount < min_amount or amount > max_amount:
        return False
    if amount > user_balance:
        return False
    return True
