"""Re-exported betting core logic."""

from bot.betting_logic import (  # noqa: F401
    Bet,
    Match,
    Team,
    calculate_payout,
    generate_odds,
    has_match_resolved,
    is_betting_open,
    resolve_match,
    validate_bet_amount,
)

__all__ = [
    "Bet",
    "Match",
    "Team",
    "calculate_payout",
    "generate_odds",
    "has_match_resolved",
    "is_betting_open",
    "resolve_match",
    "validate_bet_amount",
]
