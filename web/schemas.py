from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class GuildSettings(BaseModel):
    server_rate: float = Field(1.0, ge=0.1, le=10)
    currency_name: str = Field("Coins", min_length=1, max_length=64)
    prefix: str = Field("!", min_length=1, max_length=5)
    welcome_channel_id: Optional[int] = None
    moderation_enabled: bool = True
    explain_mode_enabled: bool = False


class LevelingSettings(BaseModel):
    enabled: bool = True
    xp_per_message: int = Field(15, ge=1, le=100)
    xp_cooldown_seconds: int = Field(60, ge=0, le=3600)
    announce_level_up: bool = True
    level_up_channel_id: Optional[int] = None
    rewards_roles_enabled: bool = True


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
    allow_temporary_items: bool = True


class LogsSettings(BaseModel):
    enabled: bool = True
    log_channel_id: Optional[int] = None
    log_moderation: bool = True
    log_economy: bool = True
    log_gambling: bool = False


class FeatureToggles(BaseModel):
    leveling_enabled: bool = True
    leveling_roles_enabled: bool = True
    economy_enabled: bool = True
    gambling_enabled: bool = True
    shop_enabled: bool = True
    shop_temporary_items_enabled: bool = True
    logs_enabled: bool = True


class EconomySinkSettings(BaseModel):
    inactivity_tax_percent: float = Field(1.0, ge=0, le=25)
    cooldown_reset_cost: int = Field(250, ge=0, le=100000)
    temp_boost_cost: int = Field(500, ge=0, le=250000)
    role_rename_cost: int = Field(750, ge=0, le=250000)
    admin_sink_enabled: bool = True
    admin_sink_min_amount: int = Field(50, ge=0, le=1000000)


class TrustScoreSettings(BaseModel):
    account_age_weight: float = Field(0.2, ge=0, le=1)
    activity_weight: float = Field(0.2, ge=0, le=1)
    warnings_weight: float = Field(0.05, ge=0, le=1)
    abuse_weight: float = Field(0.1, ge=0, le=1)
    command_rate_weight: float = Field(0.02, ge=0, le=1)
    min_trust_score: float = Field(0.0, ge=0, le=1)
    max_trust_score: float = Field(1.0, ge=0, le=1)


class ShadowPenaltySettings(BaseModel):
    xp_multiplier_min: float = Field(0.5, ge=0, le=1)
    cooldown_multiplier_max: float = Field(2.0, ge=1, le=10)
    gambling_win_multiplier_min: float = Field(0.5, ge=0, le=1)
    auto_apply_enabled: bool = True


class OverviewStats(BaseModel):
    guild_id: int
    member_count: int
    total_balance: int
    average_level: float
    total_warnings: int
    total_shop_items: int


class EconomyAnalyticsOverview(BaseModel):
    total_currency: int
    average_balance: float
    median_balance: int
    active_users: int


class EconomyAnalyticsPoint(BaseModel):
    label: str
    generated: int
    removed: int
    net: int


class EconomyAnalyticsFlow(BaseModel):
    generated: int
    removed: int
    net_flow: int
    series: list[EconomyAnalyticsPoint]


class EconomyAnalyticsTopEntry(BaseModel):
    user_id: int
    user_name: str
    amount: int


class EconomyAnalyticsTopActivity(BaseModel):
    earners: list[EconomyAnalyticsTopEntry]
    spenders: list[EconomyAnalyticsTopEntry]


class EconomyAnalyticsWarning(BaseModel):
    code: str
    message: str
    severity: str


class EconomyAnalyticsHealth(BaseModel):
    inflation_indicator: str
    sink_source_ratio: float
    warnings: list[EconomyAnalyticsWarning]
    interpretation: str


class EconomyAnalyticsResponse(BaseModel):
    period: int
    is_mocked: bool
    overview: EconomyAnalyticsOverview
    flow: EconomyAnalyticsFlow
    top_activity: EconomyAnalyticsTopActivity
    health: EconomyAnalyticsHealth


class PresetOut(BaseModel):
    name: str
    description: str
    settings: dict


class ChangeHistoryEntry(BaseModel):
    id: int
    guild_id: int
    actor_id: Optional[int]
    category: str
    previous_settings: dict
    new_settings: dict
    reason: str
    created_at: str


class FeatureFlagState(BaseModel):
    name: str
    enabled: bool
    description: str = ""


class GuildFeatureFlagState(BaseModel):
    name: str
    enabled: bool


class FeatureFlagUpdate(BaseModel):
    enabled: bool
    description: str = ""


class GuildFeatureFlagUpdate(BaseModel):
    enabled: bool


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
