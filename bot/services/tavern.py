from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, case, distinct, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import GuildConfig, PvpDuel, TavernItem, TavernPurchaseLog, UserTavernLoadout
from bot.services.economy import EconomyService

ALLOWED_SLOT_TYPES = {"attack", "defense"}
ALLOWED_EFFECT_TYPES = {
    "attack_bonus_percent",
    "defense_bonus_percent",
    "crit_chance_percent",
    "dodge_chance_percent",
    "elo_protection_percent",
    "win_bonus_elo_flat",
}

DEFAULT_MAX_BONUS_CAPS = {
    "attack_bonus_percent": 15.0,
    "defense_bonus_percent": 15.0,
    "crit_chance_percent": 5.0,
    "dodge_chance_percent": 5.0,
    "elo_protection_percent": 20.0,
    "win_bonus_elo_flat": 5.0,
}


@dataclass
class ActiveTavernEffect:
    slot_type: str
    effect_type: str
    value: float
    item_id: int
    item_name: str


class TavernService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.economy = EconomyService(session)

    @staticmethod
    def clamp_effect_value(effect_type: str, value: float, caps: dict[str, float] | None = None) -> float:
        max_caps = {**DEFAULT_MAX_BONUS_CAPS, **(caps or {})}
        max_value = float(max_caps.get(effect_type, 0.0))
        return max(0.0, min(float(value), max_value)) if effect_type in ALLOWED_EFFECT_TYPES else 0.0

    @classmethod
    def validate_item_payload(
        cls,
        *,
        slot_type: str,
        effect_type: str,
        value: float,
        duration_seconds: int,
        price: int,
        caps: dict[str, float] | None = None,
    ) -> None:
        if slot_type not in ALLOWED_SLOT_TYPES:
            raise ValueError("slot_type должен быть attack или defense")
        if effect_type not in ALLOWED_EFFECT_TYPES:
            raise ValueError("Недопустимый effect_type для Tavern v1")
        if duration_seconds <= 0:
            raise ValueError("duration_seconds должен быть > 0")
        if price < 0:
            raise ValueError("price должен быть >= 0")
        clamped = cls.clamp_effect_value(effect_type, value, caps)
        if clamped != float(value):
            raise ValueError("value превышает допустимый cap для выбранного эффекта")

    async def get_tavern_settings(self, guild_id: int) -> dict[str, Any]:
        config = await self.session.get(GuildConfig, guild_id)
        defaults: dict[str, Any] = {
            "enabled": True,
            "season_reset_clears_loadout": True,
            "stacking_rule": "max",
            "max_bonus_caps": dict(DEFAULT_MAX_BONUS_CAPS),
        }
        if config is None:
            return defaults
        try:
            settings_map = json.loads(config.settings or "{}")
        except json.JSONDecodeError:
            settings_map = {}
        raw = ((settings_map.get("pvp") or {}).get("tavern") or {}) if isinstance(settings_map, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        merged = dict(defaults)
        merged.update(raw)
        merged_caps = dict(DEFAULT_MAX_BONUS_CAPS)
        if isinstance(raw.get("max_bonus_caps"), dict):
            for key, value in raw["max_bonus_caps"].items():
                if key in merged_caps:
                    try:
                        merged_caps[key] = max(0.0, float(value))
                    except (TypeError, ValueError):
                        pass
        merged["max_bonus_caps"] = merged_caps
        if merged.get("stacking_rule") not in {"max", "sum"}:
            merged["stacking_rule"] = "max"
        return merged

    async def get_or_create_loadout(self, guild_id: int, user_id: int) -> UserTavernLoadout:
        result = await self.session.execute(
            select(UserTavernLoadout)
            .where(UserTavernLoadout.guild_id == guild_id, UserTavernLoadout.user_id == user_id)
            .with_for_update()
        )
        loadout = result.scalars().first()
        if loadout is not None:
            return loadout
        loadout = UserTavernLoadout(guild_id=guild_id, user_id=user_id)
        self.session.add(loadout)
        await self.session.flush()
        return loadout

    async def cleanup_expired_loadouts(self, *, now: dt.datetime | None = None, batch_size: int = 500) -> int:
        moment = now or dt.datetime.utcnow()
        total = 0
        while True:
            result = await self.session.execute(
                select(UserTavernLoadout)
                .where(
                    or_(
                        and_(UserTavernLoadout.attack_item_id.is_not(None), UserTavernLoadout.attack_ends_at.is_not(None), UserTavernLoadout.attack_ends_at <= moment),
                        and_(UserTavernLoadout.defense_item_id.is_not(None), UserTavernLoadout.defense_ends_at.is_not(None), UserTavernLoadout.defense_ends_at <= moment),
                    )
                )
                .order_by(UserTavernLoadout.id.asc())
                .limit(batch_size)
                .with_for_update()
            )
            rows = result.scalars().all()
            if not rows:
                break
            for row in rows:
                changed = False
                if row.attack_item_id is not None and row.attack_ends_at and row.attack_ends_at <= moment:
                    row.attack_item_id = None
                    row.attack_ends_at = None
                    changed = True
                if row.defense_item_id is not None and row.defense_ends_at and row.defense_ends_at <= moment:
                    row.defense_item_id = None
                    row.defense_ends_at = None
                    changed = True
                if changed:
                    row.updated_at = moment
                    total += 1
            if len(rows) < batch_size:
                break
        return total

    async def purchase_item(self, *, guild_id: int, user_id: int, item_id: int) -> UserTavernLoadout:
        now = dt.datetime.utcnow()
        item = await self.session.get(TavernItem, item_id)
        if item is None or int(item.guild_id) != guild_id or not bool(item.enabled):
            raise ValueError("Товар таверны недоступен.")

        settings = await self.get_tavern_settings(guild_id)
        self.validate_item_payload(
            slot_type=str(item.slot_type),
            effect_type=str(item.effect_type),
            value=float(item.value or 0.0),
            duration_seconds=int(item.duration_seconds),
            price=int(item.price),
            caps=settings.get("max_bonus_caps") if isinstance(settings.get("max_bonus_caps"), dict) else None,
        )

        loadout = await self.get_or_create_loadout(guild_id, user_id)
        await self.economy.debit(
            guild_id,
            user_id,
            int(item.price),
            "tavern_purchase",
            {
                "item_id": int(item.id),
                "slot_type": str(item.slot_type),
                "effect_type": str(item.effect_type),
            },
            ledger_type="shop_purchase",
        )

        expires_at = now + dt.timedelta(seconds=int(item.duration_seconds))
        if item.slot_type == "attack":
            loadout.attack_item_id = int(item.id)
            loadout.attack_ends_at = expires_at
        else:
            loadout.defense_item_id = int(item.id)
            loadout.defense_ends_at = expires_at
        loadout.updated_at = now

        self.session.add(
            TavernPurchaseLog(
                guild_id=guild_id,
                user_id=user_id,
                item_id=int(item.id),
                purchased_at=now,
                price=int(item.price),
            )
        )
        await self.session.flush()
        return loadout

    async def unequip_slot(self, *, guild_id: int, user_id: int, slot_type: str) -> UserTavernLoadout:
        if slot_type not in ALLOWED_SLOT_TYPES:
            raise ValueError("Некорректный слот")
        loadout = await self.get_or_create_loadout(guild_id, user_id)
        if slot_type == "attack":
            loadout.attack_item_id = None
            loadout.attack_ends_at = None
        else:
            loadout.defense_item_id = None
            loadout.defense_ends_at = None
        loadout.updated_at = dt.datetime.utcnow()
        await self.session.flush()
        return loadout

    async def get_active_effects_for_users(
        self,
        *,
        guild_id: int,
        user_ids: list[int],
        now: dt.datetime | None = None,
    ) -> dict[int, dict[str, ActiveTavernEffect]]:
        moment = now or dt.datetime.utcnow()
        if not user_ids:
            return {}
        await self.cleanup_expired_loadouts(now=moment)
        settings = await self.get_tavern_settings(guild_id)
        caps = settings.get("max_bonus_caps") if isinstance(settings.get("max_bonus_caps"), dict) else None

        result = await self.session.execute(
            select(
                UserTavernLoadout.user_id,
                UserTavernLoadout.attack_item_id,
                UserTavernLoadout.attack_ends_at,
                UserTavernLoadout.defense_item_id,
                UserTavernLoadout.defense_ends_at,
                TavernItem.id,
                TavernItem.slot_type,
                TavernItem.effect_type,
                TavernItem.value,
                TavernItem.name,
            )
            .select_from(UserTavernLoadout)
            .join(
                TavernItem,
                or_(
                    TavernItem.id == UserTavernLoadout.attack_item_id,
                    TavernItem.id == UserTavernLoadout.defense_item_id,
                ),
            )
            .where(UserTavernLoadout.guild_id == guild_id, UserTavernLoadout.user_id.in_(user_ids), TavernItem.enabled.is_(True))
        )

        mapped: dict[int, dict[str, ActiveTavernEffect]] = {uid: {} for uid in user_ids}
        for row in result.all():
            uid = int(row.user_id)
            slot = str(row.slot_type)
            ends_at = row.attack_ends_at if slot == "attack" else row.defense_ends_at
            selected_item_id = row.attack_item_id if slot == "attack" else row.defense_item_id
            if selected_item_id != row.id or ends_at is None or ends_at <= moment:
                continue
            effect_type = str(row.effect_type)
            mapped[uid][slot] = ActiveTavernEffect(
                slot_type=slot,
                effect_type=effect_type,
                value=self.clamp_effect_value(effect_type, float(row.value or 0.0), caps),
                item_id=int(row.id),
                item_name=str(row.name),
            )
        return mapped

    async def get_usage_metrics(self, *, guild_id: int, days: int = 30) -> dict[str, Any]:
        since = dt.datetime.utcnow() - dt.timedelta(days=max(1, days))
        purchases = await self.session.execute(
            select(TavernPurchaseLog.item_id, func.count(TavernPurchaseLog.id).label("cnt"))
            .where(TavernPurchaseLog.guild_id == guild_id, TavernPurchaseLog.purchased_at >= since)
            .group_by(TavernPurchaseLog.item_id)
            .order_by(func.count(TavernPurchaseLog.id).desc())
            .limit(10)
        )

        active_count = await self.session.scalar(
            select(func.coalesce(func.count(UserTavernLoadout.id), 0)).where(
                UserTavernLoadout.guild_id == guild_id,
                or_(
                    and_(UserTavernLoadout.attack_item_id.is_not(None), UserTavernLoadout.attack_ends_at > dt.datetime.utcnow()),
                    and_(UserTavernLoadout.defense_item_id.is_not(None), UserTavernLoadout.defense_ends_at > dt.datetime.utcnow()),
                ),
            )
        )

        return {
            "days": int(days),
            "active_loadouts_count": int(active_count or 0),
            "most_bought_items": [{"item_id": int(r.item_id), "purchases": int(r.cnt or 0)} for r in purchases],
        }

    async def get_analytics_overview(self, *, guild_id: int, days: int) -> dict[str, Any]:
        now = dt.datetime.utcnow()
        since = now - dt.timedelta(days=days)

        pop = await self.session.execute(
            select(TavernItem.id, TavernItem.name, func.count(TavernPurchaseLog.id).label("purchases"))
            .join(TavernPurchaseLog, TavernPurchaseLog.item_id == TavernItem.id)
            .where(TavernPurchaseLog.guild_id == guild_id, TavernPurchaseLog.purchased_at >= since)
            .group_by(TavernItem.id, TavernItem.name)
            .order_by(func.count(TavernPurchaseLog.id).desc(), TavernItem.id.asc())
            .limit(1)
        )
        top = pop.first()

        totals = await self.session.execute(
            select(
                func.coalesce(func.count(TavernPurchaseLog.id), 0).label("purchases"),
                func.coalesce(func.count(distinct(TavernPurchaseLog.user_id)), 0).label("buyers"),
                func.coalesce(func.sum(TavernPurchaseLog.price), 0).label("spent"),
            ).where(TavernPurchaseLog.guild_id == guild_id, TavernPurchaseLog.purchased_at >= since)
        )
        totals_row = totals.one()

        active_now = await self.session.scalar(
            select(func.coalesce(func.count(UserTavernLoadout.id), 0)).where(
                UserTavernLoadout.guild_id == guild_id,
                or_(
                    and_(UserTavernLoadout.attack_item_id.is_not(None), UserTavernLoadout.attack_ends_at > now),
                    and_(UserTavernLoadout.defense_item_id.is_not(None), UserTavernLoadout.defense_ends_at > now),
                ),
            )
        )

        daily = await self.session.execute(
            select(
                func.date(TavernPurchaseLog.purchased_at).label("day"),
                func.count(TavernPurchaseLog.id).label("purchases"),
                func.coalesce(func.sum(TavernPurchaseLog.price), 0).label("spent"),
            )
            .where(TavernPurchaseLog.guild_id == guild_id, TavernPurchaseLog.purchased_at >= since)
            .group_by(func.date(TavernPurchaseLog.purchased_at))
            .order_by(func.date(TavernPurchaseLog.purchased_at).asc())
        )
        day_map = {str(r.day): {"purchases": int(r.purchases or 0), "spent": int(r.spent or 0)} for r in daily}

        series: list[dict[str, Any]] = []
        for i in range(days):
            day = (since + dt.timedelta(days=i)).date().isoformat()
            point = day_map.get(day, {"purchases": 0, "spent": 0})
            series.append({"day": day, "purchases": point["purchases"], "spent": point["spent"], "active_loadouts": int(active_now or 0)})

        return {
            "days": days,
            "kpis": {
                "active_loadouts": int(active_now or 0),
                "purchases": int(totals_row.purchases or 0),
                "unique_buyers": int(totals_row.buyers or 0),
                "total_spent": int(totals_row.spent or 0),
                "most_popular_item": (
                    {"item_id": int(top.id), "name": str(top.name), "purchases": int(top.purchases or 0)} if top else None
                ),
            },
            "timeseries": series,
        }

    async def get_analytics_items(self, *, guild_id: int, days: int) -> list[dict[str, Any]]:
        since = dt.datetime.utcnow() - dt.timedelta(days=days)
        now = dt.datetime.utcnow()
        rows = await self.session.execute(
            select(
                TavernItem.id,
                TavernItem.name,
                TavernItem.slot_type,
                func.count(TavernPurchaseLog.id).label("purchases"),
                func.coalesce(func.count(distinct(TavernPurchaseLog.user_id)), 0).label("buyers"),
                func.coalesce(func.sum(TavernPurchaseLog.price), 0).label("spent"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    TavernItem.slot_type == "attack",
                                    UserTavernLoadout.attack_item_id == TavernItem.id,
                                    UserTavernLoadout.attack_ends_at.is_not(None),
                                    UserTavernLoadout.attack_ends_at > now,
                                ),
                                1,
                            ),
                            (
                                and_(
                                    TavernItem.slot_type == "defense",
                                    UserTavernLoadout.defense_item_id == TavernItem.id,
                                    UserTavernLoadout.defense_ends_at.is_not(None),
                                    UserTavernLoadout.defense_ends_at > now,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("active_now"),
            )
            .select_from(TavernItem)
            .join(TavernPurchaseLog, and_(TavernPurchaseLog.item_id == TavernItem.id, TavernPurchaseLog.purchased_at >= since), isouter=True)
            .join(UserTavernLoadout, UserTavernLoadout.guild_id == TavernItem.guild_id, isouter=True)
            .where(TavernItem.guild_id == guild_id)
            .group_by(TavernItem.id, TavernItem.name, TavernItem.slot_type)
            .order_by(func.count(TavernPurchaseLog.id).desc(), TavernItem.id.asc())
            .limit(25)
        )
        return [
            {
                "item_id": int(r.id),
                "name": str(r.name),
                "slot": str(r.slot_type),
                "purchases": int(r.purchases or 0),
                "unique_buyers": int(r.buyers or 0),
                "spent": int(r.spent or 0),
                "active_now": int(r.active_now or 0),
            }
            for r in rows
        ]

    async def get_analytics_impact(self, *, guild_id: int, days: int) -> dict[str, Any]:
        if not hasattr(PvpDuel, "applied_buffs_json"):
            return {"available": False, "message": "Метрика недоступна: в таблице дуэлей нет applied_buffs_json."}
        since = dt.datetime.utcnow() - dt.timedelta(days=days)
        rows = (
            await self.session.execute(
                select(
                    PvpDuel.winner_id,
                    PvpDuel.challenger_id,
                    PvpDuel.opponent_id,
                    PvpDuel.applied_buffs_json,
                ).where(PvpDuel.guild_id == guild_id, PvpDuel.status == "resolved", PvpDuel.resolved_at >= since)
            )
        ).all()
        if not rows:
            return {
                "available": True,
                "buffed_duels": 0,
                "non_buffed_duels": 0,
                "winrate_buffed": 0.0,
                "winrate_non_buffed": 0.0,
                "avg_elo_delta_buffed": 0.0,
                "avg_elo_delta_non_buffed": 0.0,
            }

        user_ids: set[int] = set()
        buffed_rows: list[tuple[Any, bool]] = []
        for row in rows:
            applied = row.applied_buffs_json if isinstance(row.applied_buffs_json, dict) else {}
            has_buffs = False
            for pid in (str(row.challenger_id), str(row.opponent_id)):
                participant = applied.get(pid, {}) if isinstance(applied, dict) else {}
                if isinstance(participant, dict) and participant:
                    has_buffs = True
                    break
            buffed_rows.append((row, has_buffs))
            user_ids.add(int(row.challenger_id))
            user_ids.add(int(row.opponent_id))

        from bot.database.models import PvpStats

        rating_rows = await self.session.execute(
            select(PvpStats.user_id, PvpStats.rating).where(PvpStats.guild_id == guild_id, PvpStats.user_id.in_(list(user_ids)))
        )
        rating_map = {int(r.user_id): int(r.rating or 1000) for r in rating_rows}

        buffed_duels = non_buffed_duels = 0
        buffed_winner_count = non_buffed_winner_count = 0
        buffed_elo_delta_sum = non_buffed_elo_delta_sum = 0.0
        for row, has_buffs in buffed_rows:
            winner_id = int(row.winner_id or 0)
            loser_id = int(row.opponent_id if winner_id == int(row.challenger_id) else row.challenger_id)
            elo_delta = float((rating_map.get(winner_id, 1000) - rating_map.get(loser_id, 1000)))
            applied = row.applied_buffs_json if isinstance(row.applied_buffs_json, dict) else {}
            winner_has_buff = False
            winner_payload = applied.get(str(winner_id), {}) if isinstance(applied, dict) else {}
            if isinstance(winner_payload, dict) and winner_payload:
                winner_has_buff = True
            if has_buffs:
                buffed_duels += 1
                buffed_winner_count += 1 if winner_has_buff else 0
                buffed_elo_delta_sum += elo_delta
            else:
                non_buffed_duels += 1
                non_buffed_winner_count += 1 if not winner_has_buff else 0
                non_buffed_elo_delta_sum += elo_delta

        return {
            "available": True,
            "buffed_duels": buffed_duels,
            "non_buffed_duels": non_buffed_duels,
            "winrate_buffed": round((buffed_winner_count / buffed_duels) if buffed_duels else 0.0, 4),
            "winrate_non_buffed": round((non_buffed_winner_count / non_buffed_duels) if non_buffed_duels else 0.0, 4),
            "avg_elo_delta_buffed": round((buffed_elo_delta_sum / buffed_duels) if buffed_duels else 0.0, 2),
            "avg_elo_delta_non_buffed": round((non_buffed_elo_delta_sum / non_buffed_duels) if non_buffed_duels else 0.0, 2),
        }

    async def clear_loadouts_for_guild(self, guild_id: int) -> int:
        result = await self.session.execute(
            update(UserTavernLoadout)
            .where(UserTavernLoadout.guild_id == guild_id)
            .values(
                attack_item_id=None,
                defense_item_id=None,
                attack_ends_at=None,
                defense_ends_at=None,
                updated_at=dt.datetime.utcnow(),
            )
        )
        return int(result.rowcount or 0)

    async def monthly_tavern_stats(self, *, guild_id: int, start: dt.datetime, end: dt.datetime) -> dict[str, int]:
        purchases = await self.session.scalar(
            select(func.coalesce(func.count(TavernPurchaseLog.id), 0)).where(
                TavernPurchaseLog.guild_id == guild_id,
                TavernPurchaseLog.purchased_at >= start,
                TavernPurchaseLog.purchased_at < end,
            )
        )
        active = await self.session.scalar(
            select(func.coalesce(func.count(UserTavernLoadout.id), 0)).where(
                UserTavernLoadout.guild_id == guild_id,
                or_(
                    and_(UserTavernLoadout.attack_item_id.is_not(None), UserTavernLoadout.attack_ends_at >= start),
                    and_(UserTavernLoadout.defense_item_id.is_not(None), UserTavernLoadout.defense_ends_at >= start),
                ),
            )
        )
        return {
            "tavern_active_buffs": int(active or 0),
            "tavern_purchases": int(purchases or 0),
        }
