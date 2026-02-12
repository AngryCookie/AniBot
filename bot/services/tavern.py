from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import GuildConfig, TavernItem, TavernPurchaseLog, UserTavernLoadout
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

MAX_ATTACK_DEFENSE_PERCENT = 15.0
MAX_CRIT_DODGE_PERCENT = 5.0
MAX_ELO_PROTECTION_PERCENT = 20.0
MAX_WIN_BONUS_ELO_FLAT = 5.0


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
    def clamp_effect_value(effect_type: str, value: float) -> float:
        if effect_type in {"attack_bonus_percent", "defense_bonus_percent"}:
            return max(0.0, min(float(value), MAX_ATTACK_DEFENSE_PERCENT))
        if effect_type in {"crit_chance_percent", "dodge_chance_percent"}:
            return max(0.0, min(float(value), MAX_CRIT_DODGE_PERCENT))
        if effect_type == "elo_protection_percent":
            return max(0.0, min(float(value), MAX_ELO_PROTECTION_PERCENT))
        if effect_type == "win_bonus_elo_flat":
            return max(0.0, min(float(value), MAX_WIN_BONUS_ELO_FLAT))
        return 0.0

    @classmethod
    def validate_item_payload(
        cls,
        *,
        slot_type: str,
        effect_type: str,
        value: float,
        duration_seconds: int,
        price: int,
    ) -> None:
        if slot_type not in ALLOWED_SLOT_TYPES:
            raise ValueError("slot_type должен быть attack или defense")
        if effect_type not in ALLOWED_EFFECT_TYPES:
            raise ValueError("Недопустимый effect_type для Tavern v1")
        if duration_seconds <= 0:
            raise ValueError("duration_seconds должен быть > 0")
        if price < 0:
            raise ValueError("price должен быть >= 0")
        clamped = cls.clamp_effect_value(effect_type, value)
        if clamped != float(value):
            raise ValueError("value превышает допустимый cap для выбранного эффекта")

    async def get_tavern_settings(self, guild_id: int) -> dict[str, Any]:
        config = await self.session.get(GuildConfig, guild_id)
        defaults = {
            "enabled": True,
            "season_reset_clears_loadout": True,
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

        # Поведение v1: при замене слота остаток сгорает.
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
                value=self.clamp_effect_value(effect_type, float(row.value or 0.0)),
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
