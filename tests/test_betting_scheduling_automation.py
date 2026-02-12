import datetime as dt

from bot.betting.scheduler import _month_iter
from bot.betting.service import merge_scheduling_settings


def test_merge_scheduling_settings_has_auto_apply_defaults():
    merged = merge_scheduling_settings({"timezone": "Europe/Moscow"})
    assert merged["timezone"] == "Europe/Moscow"
    assert merged["auto_apply"]["enabled"] is True
    assert merged["auto_apply"]["horizon_days"] == 14
    assert merged["auto_apply"]["run_every_minutes"] == 30


def test_merge_scheduling_settings_auto_apply_overrides():
    merged = merge_scheduling_settings({"auto_apply": {"enabled": False, "horizon_days": 2, "run_every_minutes": 5}})
    assert merged["auto_apply"] == {"enabled": False, "horizon_days": 2, "run_every_minutes": 5}


def test_month_iter_spans_year_boundary():
    months = list(_month_iter(dt.date(2026, 12, 31), dt.date(2027, 1, 1)))
    assert months == [(2026, 12), (2027, 1)]
