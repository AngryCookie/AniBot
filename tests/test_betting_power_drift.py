import datetime as dt

from bot.betting.power_drift import _seeded_random
from bot.betting.service import merge_power_drift_settings


def test_merge_power_drift_settings_defaults_and_override():
    merged = merge_power_drift_settings({"timezone": "Europe/Moscow", "momentum": {"enabled": True}})
    assert merged["timezone"] == "Europe/Moscow"
    assert merged["tick"] == "daily"
    assert merged["momentum"]["enabled"] is True
    assert merged["momentum"]["window_matches"] == 10


def test_seeded_random_is_deterministic_per_day():
    day = dt.date(2026, 1, 15)
    a = _seeded_random(1, 2, day).uniform(-1.0, 1.0)
    b = _seeded_random(1, 2, day).uniform(-1.0, 1.0)
    c = _seeded_random(1, 2, dt.date(2026, 1, 16)).uniform(-1.0, 1.0)
    assert a == b
    assert a != c
