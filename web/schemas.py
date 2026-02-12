from __future__ import annotations

from typing import Any, List, Optional

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
    message_xp_enabled: bool = True
    message_xp_min_length: int = Field(6, ge=1, le=2000)
    message_xp_cooldown_seconds: int = Field(45, ge=0, le=3600)
    message_xp_min: int = Field(5, ge=0, le=100)
    message_xp_max: int = Field(10, ge=0, le=100)
    message_ignore_channels: List[int] = Field(default_factory=list)
    voice_xp_enabled: bool = True
    voice_xp_per_minute: int = Field(1, ge=0, le=20)
    voice_ignore_channels: List[int] = Field(default_factory=list)
    voice_ignore_self_deaf: bool = True
    voice_ignore_self_mute: bool = False
    level_curve_type: str = Field("quadratic", pattern="^(quadratic|legacy)$")
    level_curve_a: int = Field(50, ge=0, le=10000)
    level_curve_b: int = Field(50, ge=0, le=10000)
    role_rewards_enabled: bool = True
    announce_level_up: bool = True
    level_up_channel_id: Optional[int] = None
    announce_cooldown_seconds: int = Field(60, ge=0, le=3600)


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


class PvpSettings(BaseModel):
    enabled: bool = True
    min_bet: int = Field(50, ge=1, le=100000)
    max_bet: int = Field(5000, ge=1, le=1000000)
    cooldown_seconds: int = Field(300, ge=0, le=86400)
    max_active_duels_per_user: int = Field(1, ge=1, le=10)
    level_influence_percent: int = Field(10, ge=0, le=100)


class PvpSeasonRewardRoles(BaseModel):
    top1_role_id: Optional[int] = None
    top3_role_id: Optional[int] = None
    top10_role_id: Optional[int] = None


class PvpSeasonSettings(BaseModel):
    enabled: bool = True
    season_duration_days: int = Field(30, ge=1, le=365)
    auto_close_enabled: bool = True
    announce_channel_id: Optional[int] = None
    reset_mode: str = Field("hard", pattern="^(hard|soft)$")
    reward_roles: PvpSeasonRewardRoles = Field(default_factory=PvpSeasonRewardRoles)


class PvpTavernSettings(BaseModel):
    enabled: bool = True
    season_reset_clears_loadout: bool = True


class TavernItemIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=1000)
    slot_type: str = Field(..., pattern="^(attack|defense)$")
    effect_type: str = Field(
        ...,
        pattern="^(attack_bonus_percent|defense_bonus_percent|crit_chance_percent|dodge_chance_percent|elo_protection_percent|win_bonus_elo_flat)$",
    )
    value: float = Field(..., ge=0)
    duration_seconds: int = Field(..., ge=1, le=2592000)
    price: int = Field(..., ge=0, le=10_000_000)
    enabled: bool = True


class TavernItemOut(TavernItemIn):
    id: int
    guild_id: int


class TavernUsageItem(BaseModel):
    item_id: int
    purchases: int


class TavernUsageOut(BaseModel):
    days: int
    active_loadouts_count: int
    most_bought_items: list[TavernUsageItem]


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




class PassportSettings(BaseModel):
    enabled: bool = True
    hide_balance_for_others: bool = True


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


class EconomyRecommendationWarning(BaseModel):
    code: str
    message: str


class EconomyRecommendationMostBoughtItem(BaseModel):
    item_id: int
    name: str
    quantity: int


class EconomyRecommendationJobsMetrics(BaseModel):
    runs_count: int
    unique_workers: int
    total_paid_by_jobs: int
    avg_payout_per_run: float


class EconomyRecommendationShopBuffMetrics(BaseModel):
    purchases_count: int
    unique_buyers: int
    total_spent_on_buffs: int
    avg_price_paid: float
    most_bought_items: list[EconomyRecommendationMostBoughtItem]


class EconomyRecommendationBuffImpact(BaseModel):
    method: str
    estimated_extra_minted: float
    with_buff_avg: float
    without_buff_avg: float


class EconomyRecommendationKpis(BaseModel):
    period_days: int
    minted_total: int
    burned_total: int
    net: int
    active_users_economy: int
    jobs: EconomyRecommendationJobsMetrics
    shop_buffs: EconomyRecommendationShopBuffMetrics
    buff_impact: EconomyRecommendationBuffImpact | None


class EconomyRecommendationBuffPriceRange(BaseModel):
    item_id: int
    name: str
    current_price: int
    current_percent: float
    suggested_min: int
    suggested_max: int
    projected_weekly_sink: int
    rationale: str


class EconomyRecommendationPercentWarning(BaseModel):
    item_id: int
    name: str
    value_percent: float
    recommended_cap: float


class EconomyRecommendationTargetSinkRatio(BaseModel):
    min: float
    max: float
    current: float


class EconomyRecommendationJobsBalance(BaseModel):
    avg_payout: float
    suggested_adjustment_hint: str
    target_sink_ratio: EconomyRecommendationTargetSinkRatio


class EconomyRecommendationSuggestions(BaseModel):
    buff_price_ranges: list[EconomyRecommendationBuffPriceRange]
    buff_percent_warnings: list[EconomyRecommendationPercentWarning]
    jobs_balance: EconomyRecommendationJobsBalance


class EconomyRecommendationsResponse(BaseModel):
    kpis: EconomyRecommendationKpis
    warnings: list[EconomyRecommendationWarning]
    suggestions: EconomyRecommendationSuggestions


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






class ReportsIncludeSections(BaseModel):
    messages: bool = True
    voice: bool = True
    economy: bool = True
    betting: bool = True
    pvp: bool = True
    moderation: bool = True
    words: bool = True
    emojis: bool = True
    reactions: bool = True


class ReportsMonthlySettings(BaseModel):
    enabled: bool = True
    channel_id: Optional[int] = None
    post_day: int = Field(1, ge=1, le=28)
    post_hour: int = Field(12, ge=0, le=23)
    include_sections: ReportsIncludeSections = Field(default_factory=ReportsIncludeSections)






class ReportsQuarterlyIncludeSections(BaseModel):
    betting: bool = True


class ReportsQuarterlySettings(BaseModel):
    enabled: bool = False
    channel_id: Optional[int] = None
    post_day: int = Field(1, ge=1, le=28)
    post_hour: int = Field(12, ge=0, le=23)
    include_sections: ReportsQuarterlyIncludeSections = Field(default_factory=ReportsQuarterlyIncludeSections)

class ReportsYearlySettings(BaseModel):
    enabled: bool = True
    channel_id: Optional[int] = None
    post_month: int = Field(12, ge=1, le=12)
    post_day: int = Field(28, ge=1, le=31)
    post_hour: int = Field(12, ge=0, le=23)
    include_sections: ReportsIncludeSections = Field(default_factory=ReportsIncludeSections)

class ReportsSettings(BaseModel):
    enabled: bool = True
    timezone: str = Field("UTC", min_length=1, max_length=64)
    retention_days: Optional[int] = Field(None, ge=30, le=3650)
    monthly: ReportsMonthlySettings = Field(default_factory=ReportsMonthlySettings)
    quarterly: ReportsQuarterlySettings = Field(default_factory=ReportsQuarterlySettings)
    yearly: ReportsYearlySettings = Field(default_factory=ReportsYearlySettings)


class ReportsDryRunOut(BaseModel):
    payload: dict


class RitualsDailyThisDaySettings(BaseModel):
    enabled: bool = True
    channel_id: Optional[int] = None
    post_hour: int = Field(12, ge=0, le=23)
    min_years_ago: int = Field(1, ge=1, le=20)
    max_items: int = Field(3, ge=1, le=10)


class RitualsMonthlyIncludeSettings(BaseModel):
    top_word: bool = True
    top_emoji: bool = True
    top_reaction: bool = True


class RitualsMonthlyHighlightsSettings(BaseModel):
    enabled: bool = True
    channel_id: Optional[int] = None
    post_day: int = Field(1, ge=1, le=28)
    post_hour: int = Field(12, ge=0, le=23)
    include: RitualsMonthlyIncludeSettings = Field(default_factory=RitualsMonthlyIncludeSettings)


class RitualsSettings(BaseModel):
    enabled: bool = True
    timezone: str = Field("UTC", min_length=1, max_length=64)
    daily_this_day: RitualsDailyThisDaySettings = Field(default_factory=RitualsDailyThisDaySettings)
    monthly_highlights: RitualsMonthlyHighlightsSettings = Field(default_factory=RitualsMonthlyHighlightsSettings)

class WordEmojiStatsSettings(BaseModel):
    enabled: bool = True
    min_token_length: int = Field(3, ge=1, le=20)
    max_tokens_per_message: int = Field(20, ge=1, le=200)
    ignore_bots: bool = True
    ignore_channels: list[int] = Field(default_factory=list)
    retention_days: int = Field(400, ge=30, le=3650)


class TokenCountItem(BaseModel):
    key: str
    count: int


class DailyCountItem(BaseModel):
    day: str
    count: int


class WordEmojiStatsResponse(BaseModel):
    guild_id: int
    days: int
    top: list[TokenCountItem]
    series: list[DailyCountItem] = Field(default_factory=list)


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




class JobDefinitionIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=500)
    enabled: bool = True
    cooldown_seconds: int = Field(3600, ge=5, le=86_400)
    reward_min: int = Field(10, ge=0, le=1_000_000)
    reward_max: int = Field(50, ge=0, le=1_000_000)
    fail_chance: float = Field(0.1, ge=0.0, le=1.0)
    penalty_min: int = Field(1, ge=0, le=1_000_000)
    penalty_max: int = Field(10, ge=0, le=1_000_000)
    weight: int = Field(1, ge=1, le=1000)


class JobDefinitionOut(JobDefinitionIn):
    id: int
    guild_id: int

class ShopItemIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=500)
    base_price: int = Field(0, ge=0, le=1000000)
    item_type: str = Field("consumable", pattern="^(consumable|buff)$")
    role_id: Optional[int] = None
    is_active: bool = True
    buff_json: Optional[dict[str, Any]] = None
    duration_seconds: Optional[int] = Field(None, ge=60, le=31_536_000)
    max_active_per_user: Optional[int] = Field(1, ge=1, le=20)
    purchase_limit_per_user: Optional[int] = Field(None, ge=1, le=100000)
    purchase_limit_total: Optional[int] = Field(None, ge=1, le=1000000)
    enabled: bool = True


class ShopItemOut(ShopItemIn):
    id: int
    guild_id: int


class ShopPurchaseLogOut(BaseModel):
    id: int
    guild_id: int
    user_id: int
    item_id: int
    quantity: int
    total_price: int
    purchased_at: str


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


class GrowthActivationSettings(BaseModel):
    messages_required: int = Field(20, ge=0, le=1_000_000)
    voice_minutes_required: int = Field(60, ge=0, le=10_000_000)
    first_transaction_required: bool = True
    window_days: int = Field(14, ge=1, le=3650)


class GrowthReferralRewardsSettings(BaseModel):
    referrer_fixed: int = Field(200, ge=0, le=1_000_000_000)
    referred_fixed: int = Field(100, ge=0, le=1_000_000_000)
    percent_of_first_earnings: float = Field(5, ge=0, le=100)
    percent_cap: int = Field(500, ge=0, le=1_000_000_000)
    max_reward_days: int = Field(7, ge=1, le=3650)


class GrowthAntiAbuseSettings(BaseModel):
    min_account_age_days: int = Field(3, ge=0, le=36500)
    cooldown_seconds: int = Field(300, ge=0, le=86400)


class GrowthSettings(BaseModel):
    enabled: bool = True
    promo_enabled: bool = True
    referrals_enabled: bool = True
    referral_activation: GrowthActivationSettings = Field(default_factory=GrowthActivationSettings)
    referral_rewards: GrowthReferralRewardsSettings = Field(default_factory=GrowthReferralRewardsSettings)
    anti_abuse: GrowthAntiAbuseSettings = Field(default_factory=GrowthAntiAbuseSettings)


class PromoCampaignIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    status: str = Field("active", pattern="^(active|paused|ended)$")
    starts_at: str | None = None
    ends_at: str | None = None


class PromoCampaignOut(PromoCampaignIn):
    id: int
    guild_id: int
    created_at: str
    updated_at: str


class PromoCodeV2In(BaseModel):
    campaign_id: int | None = None
    code: str = Field(..., min_length=3, max_length=64)
    reward_type: str = Field(..., pattern="^(balance_fixed|balance_percent)$")
    reward_value: float = Field(..., gt=0, le=1_000_000_000)
    currency_cap: int | None = Field(None, ge=0, le=1_000_000_000)
    total_uses_limit: int | None = Field(None, ge=1, le=10_000_000)
    per_user_uses_limit: int = Field(1, ge=1, le=1000)
    min_account_age_days: int | None = Field(None, ge=0, le=36500)
    only_new_users: bool = False
    allowed_role_ids_json: str | None = None
    enabled: bool = True


class PromoCodeV2Out(PromoCodeV2In):
    id: int
    guild_id: int
    created_at: str
    updated_at: str


class GrowthOverviewV2(BaseModel):
    days: int
    promo_total_redemptions: int
    promo_total_payout: int
    referrals_pending: int
    referrals_activated: int
    referrals_total_rewards: int
    top_referrers: list[GrowthTopReferrer]


class MonthlyGoalsSettings(BaseModel):
    enabled: bool = True
    auto_generate: bool = True
    announce_channel_id: Optional[int] = None
    reward_role_id: Optional[int] = None
    close_day: int = Field(1, ge=1, le=28)
    close_hour: int = Field(12, ge=0, le=23)
    timezone: str = Field("UTC", min_length=1, max_length=64)
    default_template_id: Optional[int] = None


class MonthlyGoalTemplateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=1000)
    goal_type: str = Field(..., pattern="^(voice_minutes|messages|economy_earned|betting_volume|pvp_volume)$")
    target_value: int = Field(..., ge=1, le=1_000_000_000)
    eligibility_type: str = Field(..., pattern="^(voice_minutes|messages|economy_activity)$")
    eligibility_min_value: int = Field(0, ge=0, le=1_000_000_000)
    enabled: bool = True


class MonthlyGoalTemplateOut(MonthlyGoalTemplateIn):
    id: int
    guild_id: int
    created_at: str
    updated_at: str


class MonthlyGoalCurrentOut(BaseModel):
    id: int
    guild_id: int
    month: str
    template_id: Optional[int] = None
    goal_type: str
    target_value: int
    progress_value: int
    status: str
    started_at: str
    ends_at: str
    closed_at: Optional[str] = None
    reward_role_id: Optional[int] = None
    announce_channel_id: Optional[int] = None
    summary_message_id: Optional[int] = None
    percent_completed: float = 0.0
    days_left: int = 0
    eligible_count: int = 0


class PresenceTemplate(BaseModel):
    type: str = Field("playing", pattern="^(playing|watching|listening)$")
    text: str = Field(..., min_length=1, max_length=128)


class PresenceSettings(BaseModel):
    enabled: bool = True
    mode: str = Field("primary_guild", pattern="^(primary_guild|rotate_guilds)$")
    primary_guild_id: Optional[int] = None
    interval_seconds: int = Field(300, ge=60, le=86400)
    templates: List[PresenceTemplate] = Field(default_factory=list)


class PresencePreviewOut(BaseModel):
    guild_id: int
    rendered: List[str] = Field(default_factory=list)
