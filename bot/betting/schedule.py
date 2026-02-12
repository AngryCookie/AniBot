from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import itertools
import random
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from bot.betting.models import BettingTeam


class ScheduleGenerationError(ValueError):
    pass


@dataclass(frozen=True)
class GeneratedMatch:
    date_time_local: dt.datetime
    betting_open_at_utc: dt.datetime
    betting_close_at_utc: dt.datetime
    team_a_id: int
    team_b_id: int
    seed_key: str


def _stable_seed(guild_id: int, year: int, month: int, cfg: dict, teams: list[BettingTeam]) -> int:
    team_fingerprint = [f"{team.id}:{int(team.active)}:{team.current_power:.4f}" for team in sorted(teams, key=lambda item: item.id)]
    raw = "|".join([str(guild_id), str(year), str(month), repr(cfg), ";".join(team_fingerprint)])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def generate_month_schedule(
    guild_id: int,
    year: int,
    month: int,
    cfg: dict,
    teams: list[BettingTeam],
) -> list[GeneratedMatch]:
    scheduling_cfg = cfg.get("month_template", {})
    pairing_cfg = cfg.get("pairing_rules", {})

    timezone_name = str(cfg.get("timezone", "UTC"))
    try:
        tz = ZoneInfo(timezone_name)
    except Exception as exc:  # pragma: no cover
        raise ScheduleGenerationError(f"Некорректный timezone: {timezone_name}") from exc

    matches_per_day = int(scheduling_cfg.get("matches_per_day", 1))
    start_hour = int(scheduling_cfg.get("start_hour", 18))
    open_before = int(scheduling_cfg.get("betting_open_minutes_before", 120))
    close_before = int(scheduling_cfg.get("betting_close_minutes_before", 10))
    allowed_days = {int(day) for day in scheduling_cfg.get("days_of_week", [1, 2, 3, 4, 5, 6, 7])}
    avoid_same_pair_days = max(0, int(pairing_cfg.get("avoid_same_pair_days", 14)))
    min_active_teams = max(2, int(pairing_cfg.get("min_active_teams", 4)))

    if matches_per_day < 1:
        raise ScheduleGenerationError("matches_per_day должен быть >= 1")
    if start_hour < 0 or start_hour > 23:
        raise ScheduleGenerationError("start_hour должен быть в диапазоне 0..23")
    if close_before < 0 or open_before < 0 or open_before <= close_before:
        raise ScheduleGenerationError("Некорректные интервалы betting_open/close_minutes_before")

    active_teams = [team for team in teams if team.active]
    if len(active_teams) < min_active_teams:
        raise ScheduleGenerationError(
            f"Недостаточно активных команд: нужно минимум {min_active_teams}, доступно {len(active_teams)}"
        )

    _, days_in_month = calendar.monthrange(year, month)
    target_dates: list[dt.date] = []
    for day in range(1, days_in_month + 1):
        date_value = dt.date(year, month, day)
        if date_value.isoweekday() in allowed_days:
            target_dates.append(date_value)

    if not target_dates:
        return []

    rnd = random.Random(_stable_seed(guild_id, year, month, cfg, active_teams))
    team_ids = sorted(team.id for team in active_teams)
    appearances = {team_id: 0 for team_id in team_ids}
    pair_last_seen: dict[tuple[int, int], dt.date] = {}

    generated: list[GeneratedMatch] = []

    for date_value in target_dates:
        for slot in range(matches_per_day):
            local_dt = dt.datetime(year, month, date_value.day, start_hour, 0, tzinfo=tz) + dt.timedelta(minutes=slot)
            close_at_utc = (local_dt - dt.timedelta(minutes=close_before)).astimezone(dt.timezone.utc).replace(tzinfo=None)
            open_at_utc = (local_dt - dt.timedelta(minutes=open_before)).astimezone(dt.timezone.utc).replace(tzinfo=None)

            all_pairs = [tuple(sorted(pair)) for pair in itertools.combinations(team_ids, 2)]
            eligible: list[tuple[int, int]] = []
            fallback: list[tuple[int, int]] = []
            for pair in all_pairs:
                last_seen = pair_last_seen.get(pair)
                if last_seen is None:
                    eligible.append(pair)
                    continue
                days_since = (date_value - last_seen).days
                if days_since >= avoid_same_pair_days:
                    eligible.append(pair)
                else:
                    fallback.append(pair)

            candidates = eligible or fallback
            if not candidates:
                raise ScheduleGenerationError("Не удалось подобрать пары для генерации расписания")

            def _score(pair: tuple[int, int]) -> tuple[int, int, float]:
                a_id, b_id = pair
                return (
                    max(appearances[a_id], appearances[b_id]),
                    abs(appearances[a_id] - appearances[b_id]),
                    rnd.random(),
                )

            selected_a, selected_b = min(candidates, key=_score)
            if rnd.random() < 0.5:
                team_a_id, team_b_id = selected_a, selected_b
            else:
                team_a_id, team_b_id = selected_b, selected_a

            ordered_pair = tuple(sorted((team_a_id, team_b_id)))
            pair_last_seen[ordered_pair] = date_value
            appearances[team_a_id] += 1
            appearances[team_b_id] += 1

            seed_payload = f"{guild_id}:{year:04d}-{month:02d}:{local_dt.isoformat()}:{team_a_id}:{team_b_id}"
            seed_key = hashlib.sha256(seed_payload.encode("utf-8")).hexdigest()
            generated.append(
                GeneratedMatch(
                    date_time_local=local_dt,
                    betting_open_at_utc=open_at_utc,
                    betting_close_at_utc=close_at_utc,
                    team_a_id=team_a_id,
                    team_b_id=team_b_id,
                    seed_key=seed_key,
                )
            )

    return generated
