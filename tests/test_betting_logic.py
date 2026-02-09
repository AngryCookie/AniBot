from datetime import datetime, timedelta
import random

from bot.betting_logic import (
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


def _make_match() -> Match:
    now = datetime.utcnow()
    team_a = Team(id=1, name="Alpha", power_rating=100.0)
    team_b = Team(id=2, name="Bravo", power_rating=50.0)
    odds_a, odds_b = generate_odds(team_a, team_b, 1.01, 10.0, 0.0, 1.0)
    return Match(
        id=10,
        team_a=team_a,
        team_b=team_b,
        betting_open_at=now - timedelta(hours=1),
        betting_close_at=now + timedelta(hours=1),
        resolved_at=None,
        odds_a=odds_a,
        odds_b=odds_b,
        winner=None,
    )


def test_generate_odds_respects_bounds():
    team_a = Team(id=1, name="Alpha", power_rating=1000.0)
    team_b = Team(id=2, name="Bravo", power_rating=1.0)
    random.seed(0)
    odds_a, odds_b = generate_odds(team_a, team_b, 1.1, 3.0, 0.5, 1.0)
    assert 1.1 <= odds_a <= 3.0
    assert 1.1 <= odds_b <= 3.0


def test_generate_odds_power_influence_changes_odds():
    team_a = Team(id=1, name="Alpha", power_rating=100.0)
    team_b = Team(id=2, name="Bravo", power_rating=50.0)
    random.seed(0)
    odds_low, _ = generate_odds(team_a, team_b, 1.01, 10.0, 0.0, 0.5)
    odds_high, _ = generate_odds(team_a, team_b, 1.01, 10.0, 0.0, 2.0)
    assert odds_high < odds_low


def test_resolve_match_distribution_favors_stronger_team():
    match = _make_match()
    random.seed(42)
    wins_a = 0
    wins_b = 0
    for _ in range(1000):
        match.winner = None
        winner = resolve_match(match)
        if winner.id == match.team_a.id:
            wins_a += 1
        else:
            wins_b += 1
    assert wins_a > wins_b


def test_calculate_payout_returns_winnings():
    match = _make_match()
    match.winner = match.team_a
    bet = Bet(user_id=1, match_id=match.id, team_id=match.team_a.id, amount=10.0)
    payout = calculate_payout(bet, match)
    assert payout == bet.amount * match.odds_a


def test_calculate_payout_returns_zero_for_losses():
    match = _make_match()
    match.winner = match.team_b
    bet = Bet(user_id=1, match_id=match.id, team_id=match.team_a.id, amount=10.0)
    payout = calculate_payout(bet, match)
    assert payout == 0.0


def test_timing_logic():
    match = _make_match()
    now = datetime.utcnow()
    assert is_betting_open(match, now)
    match.resolved_at = now - timedelta(minutes=1)
    assert not is_betting_open(match, now)
    assert has_match_resolved(match, now)


def test_validate_bet_amount():
    assert validate_bet_amount(10.0, 1.0, 100.0, 50.0)
    assert not validate_bet_amount(0.0, 1.0, 100.0, 50.0)
    assert not validate_bet_amount(200.0, 1.0, 100.0, 1000.0)
    assert not validate_bet_amount(60.0, 1.0, 100.0, 50.0)
