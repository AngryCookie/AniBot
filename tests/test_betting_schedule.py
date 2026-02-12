import datetime as dt

import pytest

from bot.betting.models import BettingTeam
from bot.betting.schedule import ScheduleGenerationError, generate_month_schedule


def _team(team_id: int, active: bool = True, power: float = 100.0) -> BettingTeam:
    return BettingTeam(id=team_id, guild_id=1, name=f"T{team_id}", description="", base_power=power, current_power=power, active=active)


def _cfg() -> dict:
    return {
        "enabled": True,
        "timezone": "UTC",
        "month_template": {
            "days_of_week": [1, 2, 3, 4, 5, 6, 7],
            "matches_per_day": 1,
            "start_hour": 18,
            "betting_open_minutes_before": 120,
            "betting_close_minutes_before": 10,
        },
        "pairing_rules": {
            "avoid_same_pair_days": 14,
            "prefer_active_teams": True,
            "min_active_teams": 4,
        },
    }


def test_generate_month_schedule_is_deterministic():
    teams = [_team(1), _team(2), _team(3), _team(4), _team(5)]
    cfg = _cfg()
    one = generate_month_schedule(42, 2026, 2, cfg, teams)
    two = generate_month_schedule(42, 2026, 2, cfg, teams)
    assert [m.seed_key for m in one] == [m.seed_key for m in two]


def test_generate_month_schedule_respects_avoid_pair_window():
    teams = [_team(1), _team(2), _team(3), _team(4)]
    cfg = _cfg()
    cfg["month_template"]["days_of_week"] = [1]
    cfg["pairing_rules"]["avoid_same_pair_days"] = 1000

    generated = generate_month_schedule(1, 2026, 1, cfg, teams)
    pairs = [tuple(sorted((m.team_a_id, m.team_b_id))) for m in generated]
    assert len(pairs) == len(set(pairs))


def test_generate_month_schedule_raises_for_not_enough_teams():
    cfg = _cfg()
    teams = [_team(1), _team(2), _team(3, active=False)]
    with pytest.raises(ScheduleGenerationError):
        generate_month_schedule(1, 2026, 1, cfg, teams)


def test_generate_month_schedule_utc_window_ordered():
    teams = [_team(1), _team(2), _team(3), _team(4)]
    cfg = _cfg()
    generated = generate_month_schedule(1, 2026, 3, cfg, teams)
    assert generated
    for match in generated:
        assert isinstance(match.date_time_local, dt.datetime)
        assert match.betting_open_at_utc < match.betting_close_at_utc
