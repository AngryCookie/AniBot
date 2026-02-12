import datetime as dt

from bot.cogs.leveling import is_on_cooldown, merge_voice_session_minutes
from bot.cogs.utils import merge_leveling_settings, xp_to_next


def test_level_curve_quadratic_thresholds():
    curve = {"type": "quadratic", "a": 50, "b": 50}
    assert xp_to_next(1, curve) == 100
    assert xp_to_next(2, curve) == 300
    assert xp_to_next(3, curve) == 600


def test_message_cooldown_logic():
    now = dt.datetime(2025, 1, 1, 12, 0, 0)
    assert is_on_cooldown(None, now, 45) is False
    assert is_on_cooldown(now - dt.timedelta(seconds=44), now, 45) is True
    assert is_on_cooldown(now - dt.timedelta(seconds=45), now, 45) is False


def test_voice_session_merge_minutes():
    now = dt.datetime(2025, 1, 1, 12, 5, 0)
    join = dt.datetime(2025, 1, 1, 12, 0, 0)
    assert merge_voice_session_minutes(join, now) == 5
    assert merge_voice_session_minutes(None, now) == 0


def test_leveling_defaults_merge():
    merged = merge_leveling_settings({"message_xp": {"cooldown_seconds": 30}})
    assert merged["enabled"] is True
    assert merged["message_xp"]["cooldown_seconds"] == 30
    assert merged["voice_xp"]["xp_per_minute"] == 1
