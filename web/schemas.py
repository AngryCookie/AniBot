from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class GuildSettings(BaseModel):
    server_rate: float = Field(1.0, ge=0.1, le=10)
    currency_name: str = Field("Coins", min_length=1, max_length=64)
    prefix: str = Field("!", min_length=1, max_length=5)
    welcome_channel_id: Optional[int] = None
    moderation_enabled: bool = True


class LevelingSettings(BaseModel):
    enabled: bool = True
    xp_per_message: int = Field(15, ge=1, le=100)
    xp_cooldown_seconds: int = Field(60, ge=0, le=3600)
    announce_level_up: bool = True
    level_up_channel_id: Optional[int] = None


class EconomySettings(BaseModel):
    enabled: bool = True
    daily_amount: int = Field(100, ge=0, le=100000)
    max_daily_claims: int = Field(1, ge=1, le=5)
    allow_transfers: bool = True
    tax_rate_percent: float = Field(2.5, ge=0, le=25)


class GamblingSettings(BaseModel):
    enabled: bool = True
    min_bet: int = Field(10, ge=1, le=100000)
    max_bet: int = Field(5000, ge=1, le=1000000)
    house_edge_percent: float = Field(5.0, ge=0, le=25)
    streak_bonus: bool = False


class ShopSettings(BaseModel):
    enabled: bool = True
    show_out_of_stock: bool = True
    highlight_discounts: bool = True


class LogsSettings(BaseModel):
    enabled: bool = True
    log_channel_id: Optional[int] = None
    log_moderation: bool = True
    log_economy: bool = True
    log_gambling: bool = False


class OverviewStats(BaseModel):
    guild_id: int
    member_count: int
    total_balance: int
    average_level: float
    total_warnings: int
    total_shop_items: int


class ShopItemIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=500)
    base_price: int = Field(0, ge=0, le=1000000)
    item_type: str = Field("role", max_length=32)
    role_id: Optional[int] = None
    is_active: bool = True


class ShopItemOut(ShopItemIn):
    id: int
    guild_id: int
