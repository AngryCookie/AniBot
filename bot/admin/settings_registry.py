from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

import discord

from bot.betting.service import DEFAULT_BETTING_SETTINGS
from bot.goals.service import DEFAULT_MONTHLY_GOALS_SETTINGS
from bot.reports.rituals import DEFAULT_RITUALS_SETTINGS
from bot.reports.service import DEFAULT_REPORTS_SETTINGS
from bot.services.pvp import DEFAULT_PVP_SETTINGS

Validator = Callable[[discord.Interaction, Any], str | None]


@dataclass(frozen=True)
class EditableKey:
    path: str
    type_hint: str
    description: str
    validator: Validator | None = None


@dataclass(frozen=True)
class SettingsCategory:
    key: str
    label: str
    section_path: str
    defaults: dict[str, Any]
    editable_keys: tuple[EditableKey, ...]


def parse_json_literal(value_raw: str) -> Any:
    text = value_raw.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value_raw


def get_nested(data: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        if part not in cur:
            return default
        cur = cur[part]
    return cur


def set_nested(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = data
    for part in parts[:-1]:
        node = cur.get(part)
        if not isinstance(node, dict):
            node = {}
            cur[part] = node
        cur = node
    cur[parts[-1]] = value


def _validate_channel(interaction: discord.Interaction, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, int):
        return "Ожидается ID канала (целое число) или null."
    guild = interaction.guild
    if guild is None:
        return "Команда доступна только на сервере."
    channel = guild.get_channel(value)
    if channel is None:
        return "Канал с таким ID не найден на сервере."
    me = guild.me or guild.get_member(interaction.client.user.id)  # type: ignore[arg-type]
    if me and isinstance(channel, discord.abc.GuildChannel):
        perms = channel.permissions_for(me)
        if not perms.view_channel:
            return "У бота нет доступа к выбранному каналу."
    return None


def _validate_role(interaction: discord.Interaction, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, int):
        return "Ожидается ID роли (целое число) или null."
    guild = interaction.guild
    if guild is None:
        return "Команда доступна только на сервере."
    role = guild.get_role(value)
    if role is None:
        return "Роль с таким ID не найдена."
    me = guild.me or guild.get_member(interaction.client.user.id)  # type: ignore[arg-type]
    if me and role >= me.top_role:
        return "Бот не может управлять этой ролью (она выше или равна моей)."
    return None


def _range(min_v: float, max_v: float) -> Validator:
    def _validate(_: discord.Interaction, value: Any) -> str | None:
        if not isinstance(value, (int, float)):
            return f"Ожидается число в диапазоне {min_v}..{max_v}."
        if value < min_v or value > max_v:
            return f"Значение должно быть в диапазоне {min_v}..{max_v}."
        return None

    return _validate


ADMIN_SETTINGS_CATEGORIES: tuple[SettingsCategory, ...] = (
    SettingsCategory(
        key="passport",
        label="🪪 Passport",
        section_path="passport",
        defaults={"enabled": True, "hide_balance_for_others": True},
        editable_keys=(
            EditableKey("enabled", "bool", "Включить паспорт"),
            EditableKey("hide_balance_for_others", "bool", "Скрывать баланс других"),
        ),
    ),
    SettingsCategory(
        key="betting",
        label="🎲 Betting",
        section_path="betting",
        defaults=DEFAULT_BETTING_SETTINGS,
        editable_keys=(
            EditableKey("enabled", "bool", "Включить беттинг"),
            EditableKey("announce_channel_id", "channel_id|null", "Канал анонсов", _validate_channel),
            EditableKey("min_bet_default", "int", "Мин. ставка", _range(1, 1_000_000)),
            EditableKey("max_bet_default", "int", "Макс. ставка", _range(1, 10_000_000)),
            EditableKey("odds.min", "float", "Минимальный коэффициент", _range(1.01, 10)),
            EditableKey("odds.max", "float", "Максимальный коэффициент", _range(1.01, 20)),
            EditableKey("resolve.power_weight", "float", "Вес силы команды", _range(0, 1)),
        ),
    ),
    SettingsCategory(
        key="scheduling",
        label="📅 Scheduling",
        section_path="betting.scheduling",
        defaults=DEFAULT_BETTING_SETTINGS["scheduling"],
        editable_keys=(
            EditableKey("enabled", "bool", "Включить расписание"),
            EditableKey("auto_apply.enabled", "bool", "Автоприменение"),
            EditableKey("auto_apply.horizon_days", "int", "Горизонт дней", _range(1, 90)),
            EditableKey("auto_apply.run_every_minutes", "int", "Период запуска", _range(1, 720)),
            EditableKey("month_template.matches_per_day", "int", "Матчей в день", _range(1, 10)),
            EditableKey("month_template.start_hour", "int", "Час старта", _range(0, 23)),
        ),
    ),
    SettingsCategory(
        key="power_drift",
        label="🌪 Power Drift",
        section_path="betting.power_drift",
        defaults=DEFAULT_BETTING_SETTINGS["power_drift"],
        editable_keys=(
            EditableKey("enabled", "bool", "Включить drift"),
            EditableKey("max_deviation_percent", "int", "Макс. отклонение %", _range(0, 100)),
            EditableKey("daily_noise_percent", "int", "Дневной шум %", _range(0, 100)),
            EditableKey("mean_reversion", "float", "Сила возврата", _range(0, 1)),
            EditableKey("momentum.enabled", "bool", "Моментум"),
            EditableKey("momentum.win_influence_percent", "int", "Влияние побед %", _range(0, 100)),
        ),
    ),
    SettingsCategory(
        key="jobs",
        label="🛠 Jobs",
        section_path="jobs",
        defaults={"enabled": True, "default_cooldown_seconds": 3600},
        editable_keys=(
            EditableKey("enabled", "bool", "Включить jobs"),
            EditableKey("default_cooldown_seconds", "int", "Кулдаун по умолчанию", _range(1, 86400)),
        ),
    ),
    SettingsCategory(
        key="shop",
        label="🏪 Shop/Buffs",
        section_path="shop",
        defaults={"enabled": True, "max_active_buffs": 5},
        editable_keys=(
            EditableKey("enabled", "bool", "Включить магазин"),
            EditableKey("max_active_buffs", "int", "Макс. активных баффов", _range(1, 100)),
        ),
    ),
    SettingsCategory(
        key="pvp_tavern",
        label="⚔ PvP/Tavern",
        section_path="pvp",
        defaults={**DEFAULT_PVP_SETTINGS, "tavern": {"max_bonus_caps": {"attack": 0.75, "defense": 0.75}}},
        editable_keys=(
            EditableKey("enabled", "bool", "Включить PvP"),
            EditableKey("min_bet", "int", "Мин. ставка PvP", _range(0, 1_000_000)),
            EditableKey("max_bet", "int", "Макс. ставка PvP", _range(1, 10_000_000)),
            EditableKey("cooldown_seconds", "int", "Кулдаун PvP", _range(0, 86400)),
            EditableKey("tavern.max_bonus_caps.attack", "float", "Кап атаки", _range(0, 10)),
            EditableKey("tavern.max_bonus_caps.defense", "float", "Кап защиты", _range(0, 10)),
        ),
    ),
    SettingsCategory(
        key="monthly_goals",
        label="🎯 Monthly Goals",
        section_path="monthly_goals",
        defaults=DEFAULT_MONTHLY_GOALS_SETTINGS,
        editable_keys=(
            EditableKey("enabled", "bool", "Включить цели"),
            EditableKey("timezone", "str", "Таймзона"),
            EditableKey("close_day", "int", "День закрытия", _range(1, 28)),
            EditableKey("close_hour", "int", "Час закрытия", _range(0, 23)),
            EditableKey("reward_role_id", "role_id|null", "Роль награды", _validate_role),
            EditableKey("announce_channel_id", "channel_id|null", "Канал анонса", _validate_channel),
        ),
    ),
    SettingsCategory(
        key="rituals",
        label="🕰 Rituals",
        section_path="rituals",
        defaults=DEFAULT_RITUALS_SETTINGS,
        editable_keys=(
            EditableKey("enabled", "bool", "Включить rituals"),
            EditableKey("timezone", "str", "Таймзона"),
            EditableKey("daily_this_day.channel_id", "channel_id|null", "Канал daily", _validate_channel),
            EditableKey("monthly_highlights.channel_id", "channel_id|null", "Канал monthly", _validate_channel),
        ),
    ),
    SettingsCategory(
        key="presence",
        label="📣 Presence",
        section_path="presence",
        defaults={"enabled": True, "interval_seconds": 300, "mode": "primary_guild", "primary_guild_id": None, "templates": []},
        editable_keys=(
            EditableKey("enabled", "bool", "Включить presence"),
            EditableKey("interval_seconds", "int", "Интервал обновления", _range(30, 3600)),
            EditableKey("mode", "str", "Режим (primary_guild/rotate)"),
            EditableKey("primary_guild_id", "int|null", "ID primary guild"),
            EditableKey("templates", "list", "Шаблоны активности"),
        ),
    ),
    SettingsCategory(
        key="reports",
        label="📊 Reports",
        section_path="reports",
        defaults=DEFAULT_REPORTS_SETTINGS,
        editable_keys=(
            EditableKey("enabled", "bool", "Включить отчёты"),
            EditableKey("timezone", "str", "Таймзона"),
            EditableKey("monthly.channel_id", "channel_id|null", "Канал monthly", _validate_channel),
            EditableKey("quarterly.channel_id", "channel_id|null", "Канал quarterly", _validate_channel),
            EditableKey("yearly.channel_id", "channel_id|null", "Канал yearly", _validate_channel),
        ),
    ),
)


def category_by_key(key: str) -> SettingsCategory | None:
    for category in ADMIN_SETTINGS_CATEGORIES:
        if category.key == key:
            return category
    return None
