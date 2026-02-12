from bot.betting.service import merge_automation_settings


def test_merge_automation_defaults_and_overrides():
    merged = merge_automation_settings({"announce_on_open": False, "auto_resolve": {"enabled": True, "delay_seconds": 42}})
    assert merged["announce_on_open"] is False
    assert merged["announce_on_close"] is True
    assert merged["auto_resolve"]["enabled"] is True
    assert merged["auto_resolve"]["delay_seconds"] == 42
    assert merged["auto_resolve"]["require_min_bets"] == 1
