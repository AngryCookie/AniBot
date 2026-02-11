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


class EconomyAnalyticsDistributionSummary(BaseModel):
    average_balance: float
    median_balance: float
    top_10_percent_share: float


class EconomyAnalyticsActivitySummary(BaseModel):
    active_users: int
    active_users_percent: float


class EconomyAnalyticsHealthSummary(BaseModel):
    sink_ratio: float
    inflation_flag: bool


class EconomyAnalyticsSummaryResponse(BaseModel):
    period_days: int
    created: float
    spent: float
    net_flow: int
    distribution: EconomyAnalyticsDistributionSummary
    activity: EconomyAnalyticsActivitySummary
    health: EconomyAnalyticsHealthSummary


class EconomyInsight(BaseModel):
    id: str
    severity: str
    title: str
    description: str
    affected_metric: str
    period: int


class BehaviorAnalyticsSegments(BaseModel):
    new_users: Optional[int]
    new_users_active: Optional[int]
    new_users_inactive: Optional[int]
    rich_but_inactive: Optional[int]
    active_but_poor: Optional[int]


class BehaviorAnalyticsDistribution(BaseModel):
    median_balance: Optional[float]
    average_balance: Optional[float]
    top_10_balance_share: Optional[float]
    top_10_activity_share: Optional[float]


class BehaviorAnalyticsResponse(BaseModel):
    period: str
    users_total: int
    active_users: int
    inactive_users: int
    activity_rate: float
    segments: BehaviorAnalyticsSegments
    retention_rate: Optional[float]
    distribution: BehaviorAnalyticsDistribution


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




class AnalyticsMonthlySettings(BaseModel):
    monthly_reports_enabled: bool = False
    monthly_reports_autopost: bool = False
    analytics_channel_id: Optional[int] = None


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


class CommunityGoalBase(BaseModel):
    metric_type: str = Field(..., pattern="^(voice_hours|messages)$")
    target_value: int = Field(..., ge=1, le=10_000_000)
    starts_at: str
    ends_at: str
    reward_role_id: Optional[int] = None
    min_participation_threshold: int = Field(0, ge=0, le=1_000_000)


class CommunityGoalIn(CommunityGoalBase):
    pass


class CommunityGoalUpdate(BaseModel):
    metric_type: str = Field(..., pattern="^(voice_hours|messages)$")
    target_value: int = Field(..., ge=1, le=10_000_000)
    starts_at: str
    ends_at: str
    reward_role_id: Optional[int] = None
    min_participation_threshold: int = Field(0, ge=0, le=1_000_000)
    status: str = Field("active", pattern="^(active|completed|failed)$")


class CommunityGoalOut(CommunityGoalBase):
    id: int
    guild_id: int
    current_value: int
    status: str
    created_at: str
    updated_at: str


class MonthlyGoalBase(BaseModel):
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    metric_type: str = Field(..., pattern="^(voice_hours|messages|bets_volume)$")
    target_value: float = Field(..., ge=0.01, le=1_000_000_000)
    reward_role_id: int
    min_user_contribution: float = Field(0, ge=0, le=1_000_000_000)
    is_active: bool = True


class MonthlyGoalIn(MonthlyGoalBase):
    pass


class MonthlyGoalUpdate(BaseModel):
    metric_type: str = Field(..., pattern="^(voice_hours|messages|bets_volume)$")
    target_value: float = Field(..., ge=0.01, le=1_000_000_000)
    reward_role_id: int
    min_user_contribution: float = Field(0, ge=0, le=1_000_000_000)
    is_active: bool = True


class MonthlyGoalOut(MonthlyGoalBase):
    id: int
    guild_id: int
    completed_at: Optional[str] = None
    created_at: str
    progress: float = 0.0
    percent_completed: float = 0.0


class ReferralPromoCodeIn(BaseModel):
    code: str = Field(..., min_length=3, max_length=64)
    reward_amount: int = Field(..., ge=1, le=1_000_000)
    max_uses: Optional[int] = Field(None, ge=1, le=10_000_000)
    expires_at: Optional[str] = None
    is_active: bool = True


class ReferralPromoCodeOut(ReferralPromoCodeIn):
    id: int
    guild_id: int
    current_uses: int
    created_at: str


class ReferralDashboardStats(BaseModel):
    total_uses: int
    total_currency_distributed: int
    top_inviters: list[dict]


class ReferralRedeemSummary(BaseModel):
    monthly_referral_volume: int
    total_referral_payout: int
    top_inviters: list[dict]


class GrowthReferralCampaignSettings(BaseModel):
    enabled: bool = True
    reward_percent_referrer: float = Field(5.0, ge=0, le=100)
    reward_percent_invited: float = Field(2.0, ge=0, le=100)
    active_threshold_messages: int = Field(20, ge=0, le=1_000_000)
    season_duration_days: int = Field(30, ge=1, le=3650)
    max_rewards_per_user: int = Field(0, ge=0, le=1_000_000)
    referral_min_account_age_days: int = Field(0, ge=0, le=36500)
    referral_min_messages: int = Field(0, ge=0, le=1_000_000)
    promo_cooldown_hours: int = Field(0, ge=0, le=8760)


class GrowthPromoUserReward(BaseModel):
    user_id: int
    total_reward: int


class GrowthPromoRoi(BaseModel):
    promo_id: int
    total_issued_currency: int
    net_new_users: int
    roi_indicator: str = Field(..., pattern="^(low|balanced|aggressive)$")
    suggestion: str


class GrowthPromoStats(BaseModel):
    total_uses: int
    unique_users: int
    total_currency_issued: int
    average_reward: float
    top_5_users_by_reward: list[GrowthPromoUserReward]
    roi: GrowthPromoRoi


class GrowthReferrerStatsRow(BaseModel):
    user_id: int
    total_referrals: int
    total_currency_paid: int


class GrowthReferralStats(BaseModel):
    total_referrals: int
    successful_referrals: int
    pending_referrals: int
    total_currency_paid: int
    average_reward: float
    top_10_referrers: list[GrowthReferrerStatsRow]


class GrowthPromoCodeIn(BaseModel):
    code: str = Field(..., min_length=3, max_length=64)
    reward_type: str = Field(..., pattern="^(fixed|percent|multiplier)$")
    reward_value: float = Field(..., gt=0, le=1_000_000)
    max_uses: Optional[int] = Field(None, ge=1, le=10_000_000)
    per_user_limit: Optional[int] = Field(None, ge=1, le=10_000_000)
    expires_at: Optional[str] = None
    enabled: bool = True


class GrowthPromoCodeOut(GrowthPromoCodeIn):
    id: int
    guild_id: int
    total_uses: int
    created_at: str


class GrowthTopReferrer(BaseModel):
    user_id: int
    total_referrals: int
    active_referrals: int
    total_rewards_paid: int


class GrowthMostUsedPromo(BaseModel):
    id: int
    code: str
    total_uses: int


class GrowthDailyMetricPoint(BaseModel):
    day: str
    value: int


class GrowthRecommendation(BaseModel):
    level: str = Field(..., pattern="^(info|warning)$")
    text: str


class GrowthOverviewResponse(BaseModel):
    range: str
    total_referrals: int
    active_referrals: int
    total_rewards_paid: int
    total_promo_redemptions: int
    registrations_per_day: list[GrowthDailyMetricPoint]
    active_referrals_per_day: list[GrowthDailyMetricPoint]
    promo_redemptions_per_day: list[GrowthDailyMetricPoint]
    rewards_paid_per_day: list[GrowthDailyMetricPoint]
    net_growth_value: int
    referral_conversion_rate: float
    avg_revenue_per_referral: float
    roi_ratio: float
    recommendations: list[GrowthRecommendation]
    top_referrers: list[GrowthTopReferrer]
    most_used_promo: Optional[GrowthMostUsedPromo] = None
