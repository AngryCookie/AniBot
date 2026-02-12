from __future__ import annotations

from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

import json
import secrets
import datetime as dt
import time
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from sqlalchemy import case, func, select, desc
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from bot.analytics.economy import build_economy_analytics
from bot.analytics.insights import build_economy_insights
from bot.analytics.recommendations import build_economy_recommendations
from bot.analytics.service import AnalyticsService
from bot.database.migrations import MIGRATIONS
from bot.database.models import (
    Base,
    CommunityGoal,
    ServerMonthlyGoal,
    FeatureFlag,
    GuildConfig,
    GuildGoalTemplate,
    GuildMonthlyGoal,
    GuildMonthlyGoalContribution,
    ReferralCode,
    ReferralUsage,
    ReferralReward,
    GuildConfigHistory,
    GuildFeatureFlag,
    ShopItem,
    ShopPurchaseLog,
    JobDefinition,
    UserProfile,
    Warning,
    WordStatDaily,
    EmojiStatDaily,
)
from bot.referral.models import PromoCodeExtended, PromoCodeUsage, PromoRewardType, ReferralRelationship, PromoCampaignV2, PromoCodeV2, PromoRedemptionV2, ReferralLinkV2, ReferralAttributionV2, ReferralRewardV2
from bot.community_goals import CommunityGoalService
from bot.monthly_goals import MonthlyGoalService
from bot.goals.service import MonthlyCommunityGoalService
from bot.reports.monthly import calculate_previous_month_period, build_monthly_payload
from bot.reports.quarterly import calculate_quarter_period, build_quarterly_payload
from bot.reports.yearly import calculate_previous_year_period, build_yearly_payload
from bot.reports.service import DEFAULT_REPORTS_SETTINGS
from bot.presence import PresenceDataProvider, PresenceSettingsService, render_presence_text

from .analytics.behavior import build_behavior_analytics
from .config import settings
from .database import database
from .betting import router as betting_router
from .schemas import (
    AnalyticsMonthlySettings,
    BehaviorAnalyticsResponse,
    ChangeHistoryEntry,
    CommunityGoalIn,
    CommunityGoalOut,
    CommunityGoalUpdate,
    MonthlyGoalIn,
    MonthlyGoalOut,
    MonthlyGoalUpdate,
    MonthlyGoalsSettings,
    MonthlyGoalTemplateIn,
    MonthlyGoalTemplateOut,
    MonthlyGoalCurrentOut,
    EconomyAnalyticsSummaryResponse,
    EconomyInsight,
    EconomySettings,
    EconomyRecommendationsResponse,
    EconomySinkSettings,
    FeatureFlagState,
    FeatureFlagUpdate,
    FeatureToggles,
    GuildFeatureFlagState,
    GuildFeatureFlagUpdate,
    GamblingSettings,
    GuildSettings,
    LevelingSettings,
    LogsSettings,
    PassportSettings,
    OverviewStats,
    PvpSeasonSettings,
    PvpSettings,
    PresetOut,
    ReferralDashboardStats,
    ReferralPromoCodeIn,
    ReferralPromoCodeOut,
    ReferralRedeemSummary,
    GrowthDailyMetricPoint,
    GrowthMostUsedPromo,
    GrowthOverviewResponse,
    GrowthPromoRoi,
    GrowthPromoStats,
    GrowthPromoUserReward,
    GrowthRecommendation,
    GrowthReferralStats,
    GrowthPromoCodeIn,
    GrowthPromoCodeOut,
    GrowthReferrerStatsRow,
    GrowthReferralCampaignSettings,
    GrowthTopReferrer,
    GrowthSettings,
    PromoCampaignIn,
    PromoCampaignOut,
    PromoCodeV2In,
    PromoCodeV2Out,
    GrowthOverviewV2,
    ShopItemIn,
    ShopItemOut,
    JobDefinitionIn,
    JobDefinitionOut,
    ShopPurchaseLogOut,
    ShopSettings,
    ShadowPenaltySettings,
    TrustScoreSettings,
    ReportsSettings,
    ReportsDryRunOut,
    RitualsSettings,
    WordEmojiStatsSettings,
    WordEmojiStatsResponse,
)
from .security import (
    DISCORD_API_BASE,
    encrypt_token,
    ensure_guild_access,
    fetch_user,
    fetch_user_guilds,
    get_access_token,
    has_guild_permission,
)
from .observability import request_logger, setup_logging

setup_logging()

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AniBot Web Admin", version="2.0")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.middleware("http")(request_logger())


_readonly_requests: Dict[str, List[float]] = {}
READONLY_RATE_LIMIT = 60
ALLOWED_ANALYTICS_PERIODS = {7, 30, 90}
MONTHLY_REPORTS_ENABLED_FLAG = "monthly_reports_enabled"
MONTHLY_REPORTS_AUTOPOST_FLAG = "monthly_reports_autopost"
GROWTH_ENABLED_FLAG = "growth_enabled"


@app.on_event("startup")
async def startup() -> None:
    if not settings.session_secret:
        raise RuntimeError("SESSION_SECRET is required")
    await database.apply_migrations(MIGRATIONS)




@app.exception_handler(HTTPException)
@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Ошибка запроса."
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": f"HTTP_{exc.status_code}", "message": detail, "details": {"path": request.url.path}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "Проверьте корректность параметров запроса.",
            "details": {"path": request.url.path, "errors": exc.errors()},
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_ERROR",
            "message": "Внутренняя ошибка сервера. Повторите попытку позже.",
            "details": {"path": request.url.path},
        },
    )

@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/login.html")


@app.get("/auth/login")
async def login(request: Request) -> RedirectResponse:
    if not settings.discord_client_id or not settings.discord_redirect_uri:
        raise HTTPException(status_code=500, detail="Discord OAuth not configured")
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
    }
    query = httpx.QueryParams(params)
    return RedirectResponse(
        url=f"https://discord.com/oauth2/authorize?{query}", status_code=302
    )


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str, state: str = "") -> RedirectResponse:
    if not settings.discord_client_secret or not settings.discord_redirect_uri:
        raise HTTPException(status_code=500, detail="Discord OAuth not configured")
    expected_state = request.session.pop("oauth_state", None)
    if not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    data = {
        "client_id": settings.discord_client_id,
        "client_secret": settings.discord_client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.discord_redirect_uri,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{DISCORD_API_BASE}/oauth2/token", data=data, headers=headers
        )
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="OAuth exchange failed")
    payload = response.json()
    request.session["access_token"] = encrypt_token(payload["access_token"])
    request.session["refresh_token"] = encrypt_token(payload.get("refresh_token", ""))
    request.session["expires_in"] = payload.get("expires_in", 0)
    return RedirectResponse(url="/servers.html", status_code=302)


@app.get("/auth/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login.html", status_code=302)


@app.get("/api/me")
async def get_me(access_token: str = Depends(get_access_token)) -> Dict[str, Any]:
    return await fetch_user(access_token)


@app.get("/api/guilds")
async def get_guilds(access_token: str = Depends(get_access_token)) -> Dict[str, Any]:
    guilds = await fetch_user_guilds(access_token)
    filtered = [guild for guild in guilds if guild.get("permissions")]
    allowed = [guild for guild in filtered if int(guild.get("permissions", 0)) & 0x28]
    return {"guilds": allowed}


def _load_settings(config: GuildConfig) -> Dict[str, Any]:
    try:
        return json.loads(config.settings or "{}")
    except json.JSONDecodeError:
        return {}


def _save_settings(config: GuildConfig, settings_map: Dict[str, Any]) -> None:
    config.settings = json.dumps(settings_map)


def _parse_iso_datetime(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def _community_goal_to_schema(goal: CommunityGoal) -> CommunityGoalOut:
    return CommunityGoalOut(
        id=goal.id,
        guild_id=int(goal.guild_id),
        metric_type=goal.metric_type,
        target_value=goal.target_value,
        current_value=goal.current_value,
        starts_at=goal.starts_at.isoformat() + "Z",
        ends_at=goal.ends_at.isoformat() + "Z",
        reward_role_id=goal.reward_role_id,
        min_participation_threshold=goal.min_participation_threshold,
        status=goal.status,
        created_at=goal.created_at.isoformat() + "Z",
        updated_at=goal.updated_at.isoformat() + "Z",
    )




def _monthly_goal_to_schema(goal: ServerMonthlyGoal, progress: float = 0.0) -> MonthlyGoalOut:
    percent = (progress / float(goal.target_value) * 100.0) if goal.target_value > 0 else 0.0
    return MonthlyGoalOut(
        id=goal.id,
        guild_id=int(goal.guild_id),
        month=goal.month,
        metric_type=goal.metric_type,
        target_value=float(goal.target_value),
        reward_role_id=int(goal.reward_role_id),
        min_user_contribution=float(goal.min_user_contribution),
        is_active=bool(goal.is_active),
        completed_at=goal.completed_at.isoformat() + "Z" if goal.completed_at else None,
        created_at=goal.created_at.isoformat() + "Z",
        progress=progress,
        percent_completed=max(0.0, min(100.0, percent)),
    )

async def _get_or_create_config(guild_id: int) -> GuildConfig:
    async with database.session() as session:
        result = await session.execute(
            select(GuildConfig).where(GuildConfig.guild_id == guild_id)
        )
        config = result.scalars().first()
        if config:
            return config
        config = GuildConfig(guild_id=guild_id)
        session.add(config)
        await session.commit()
        await session.refresh(config)
        return config




async def _ensure_global_admin(access_token: str) -> None:
    guilds = await fetch_user_guilds(access_token)
    if not any(has_guild_permission(guild) for guild in guilds):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

async def _get_actor_id(access_token: str) -> int | None:
    try:
        user = await fetch_user(access_token)
    except HTTPException:
        return None
    try:
        return int(user.get("id"))
    except (TypeError, ValueError):
        return None


async def _record_config_change(
    *,
    guild_id: int,
    category: str,
    previous_settings: Dict[str, Any],
    new_settings: Dict[str, Any],
    reason: str,
    access_token: str,
) -> None:
    actor_id = await _get_actor_id(access_token)
    change = GuildConfigHistory(
        guild_id=guild_id,
        actor_id=actor_id,
        category=category,
        previous_settings=json.dumps(previous_settings),
        new_settings=json.dumps(new_settings),
        reason=reason,
    )
    async with database.session() as session:
        session.add(change)
        await session.commit()




async def _upsert_guild_feature_flag(
    session,
    *,
    guild_id: int,
    flag_name: str,
    enabled: bool,
) -> None:
    result = await session.execute(
        select(GuildFeatureFlag).where(
            GuildFeatureFlag.guild_id == guild_id,
            GuildFeatureFlag.flag_name == flag_name,
        )
    )
    entry = result.scalars().first()
    if entry is None:
        entry = GuildFeatureFlag(guild_id=guild_id, flag_name=flag_name, enabled=enabled)
        session.add(entry)
        return
    entry.enabled = enabled


async def _ensure_feature_flag_exists(session, *, flag_name: str, description: str) -> None:
    result = await session.execute(select(FeatureFlag).where(FeatureFlag.name == flag_name))
    flag = result.scalars().first()
    if flag is None:
        session.add(FeatureFlag(name=flag_name, enabled=False, description=description))


async def _is_growth_enabled(guild_id: int) -> bool:
    async with database.session() as session:
        override = await session.scalar(
            select(GuildFeatureFlag.enabled).where(
                GuildFeatureFlag.guild_id == guild_id,
                GuildFeatureFlag.flag_name == GROWTH_ENABLED_FLAG,
            )
        )
        if override is not None:
            return bool(override)
        global_flag = await session.scalar(
            select(FeatureFlag.enabled).where(FeatureFlag.name == GROWTH_ENABLED_FLAG)
        )
    if global_flag is None:
        return True
    return bool(global_flag)


async def _require_growth_enabled(guild_id: int) -> None:
    if not await _is_growth_enabled(guild_id):
        raise HTTPException(status_code=403, detail="Growth system is disabled for this guild")

def _diff_settings(current: Dict[str, Any], updated: Dict[str, Any]) -> List[Dict[str, Any]]:
    changes = []
    keys = set(current.keys()) | set(updated.keys())
    for key in sorted(keys):
        if current.get(key) != updated.get(key):
            changes.append(
                {"field": key, "from": current.get(key), "to": updated.get(key)}
            )
    return changes


PRESETS: Dict[str, Dict[str, Any]] = {
    "small community": {
        "description": "Compact server with gentle leveling and economy pace.",
        "settings": {
            "leveling": {
                "enabled": True,
                "message_xp": {"enabled": True, "min_length": 6, "cooldown_seconds": 75, "xp_min": 5, "xp_max": 12, "ignore_channels": []},
                "voice_xp": {"enabled": True, "xp_per_minute": 1, "ignore_channels": [], "ignore_self_deaf": True},
                "level_curve": {"type": "quadratic", "a": 50, "b": 50},
                "announce_level_up": True,
                "role_rewards": {"enabled": True},
            },
            "economy": {
                "enabled": True,
                "daily_amount": 75,
                "max_daily_claims": 1,
                "allow_transfers": True,
                "tax_rate_percent": 3.0,
            },
            "economy_sinks": {
                "cooldown_reset_cost": 200,
                "temp_boost_cost": 400,
                "inactivity_tax_percent": 1.0,
                "role_rename_cost": 600,
                "admin_sink_enabled": True,
                "admin_sink_min_amount": 50,
            },
            "gambling": {
                "enabled": False,
                "min_bet": 25,
                "max_bet": 1000,
                "house_edge_percent": 6.0,
                "streak_bonus": False,
            },
            "shop": {
                "enabled": True,
                "show_out_of_stock": True,
                "highlight_discounts": True,
                "allow_temporary_items": True,
            },
            "logs": {
                "enabled": True,
                "log_channel_id": None,
                "log_moderation": True,
                "log_economy": True,
                "log_gambling": False,
            },
        },
    },
    "RP server": {
        "description": "Roleplay-focused server with softer economy sinks.",
        "settings": {
            "leveling": {
                "enabled": True,
                "message_xp": {"enabled": True, "min_length": 6, "cooldown_seconds": 90, "xp_min": 4, "xp_max": 10, "ignore_channels": []},
                "voice_xp": {"enabled": True, "xp_per_minute": 1, "ignore_channels": [], "ignore_self_deaf": True},
                "level_curve": {"type": "quadratic", "a": 50, "b": 50},
                "announce_level_up": False,
                "role_rewards": {"enabled": True},
            },
            "economy": {
                "enabled": True,
                "daily_amount": 120,
                "max_daily_claims": 1,
                "allow_transfers": True,
                "tax_rate_percent": 2.0,
            },
            "economy_sinks": {
                "cooldown_reset_cost": 150,
                "temp_boost_cost": 350,
                "inactivity_tax_percent": 0.5,
                "role_rename_cost": 500,
                "admin_sink_enabled": True,
                "admin_sink_min_amount": 50,
            },
            "gambling": {
                "enabled": False,
                "min_bet": 50,
                "max_bet": 1500,
                "house_edge_percent": 7.0,
                "streak_bonus": False,
            },
            "shop": {
                "enabled": True,
                "show_out_of_stock": True,
                "highlight_discounts": True,
                "allow_temporary_items": True,
            },
            "logs": {
                "enabled": True,
                "log_channel_id": None,
                "log_moderation": True,
                "log_economy": True,
                "log_gambling": False,
            },
        },
    },
    "gaming clan": {
        "description": "Competitive settings with active economy and gambling.",
        "settings": {
            "leveling": {
                "enabled": True,
                "message_xp": {"enabled": True, "min_length": 6, "cooldown_seconds": 45, "xp_min": 7, "xp_max": 18, "ignore_channels": []},
                "voice_xp": {"enabled": True, "xp_per_minute": 2, "ignore_channels": [], "ignore_self_deaf": True},
                "level_curve": {"type": "quadratic", "a": 50, "b": 50},
                "announce_level_up": True,
                "role_rewards": {"enabled": True},
            },
            "economy": {
                "enabled": True,
                "daily_amount": 150,
                "max_daily_claims": 2,
                "allow_transfers": True,
                "tax_rate_percent": 4.5,
            },
            "economy_sinks": {
                "cooldown_reset_cost": 300,
                "temp_boost_cost": 600,
                "inactivity_tax_percent": 1.5,
                "role_rename_cost": 900,
                "admin_sink_enabled": True,
                "admin_sink_min_amount": 75,
            },
            "gambling": {
                "enabled": True,
                "min_bet": 25,
                "max_bet": 5000,
                "house_edge_percent": 5.0,
                "streak_bonus": True,
            },
            "shop": {
                "enabled": True,
                "show_out_of_stock": True,
                "highlight_discounts": True,
                "allow_temporary_items": False,
            },
            "logs": {
                "enabled": True,
                "log_channel_id": None,
                "log_moderation": True,
                "log_economy": True,
                "log_gambling": True,
            },
        },
    },
    "creator server": {
        "description": "Creator-centric server with moderated economy and logs.",
        "settings": {
            "leveling": {
                "enabled": True,
                "message_xp": {"enabled": True, "min_length": 6, "cooldown_seconds": 60, "xp_min": 5, "xp_max": 14, "ignore_channels": []},
                "voice_xp": {"enabled": True, "xp_per_minute": 1, "ignore_channels": [], "ignore_self_deaf": True},
                "level_curve": {"type": "quadratic", "a": 50, "b": 50},
                "announce_level_up": True,
                "role_rewards": {"enabled": False},
            },
            "economy": {
                "enabled": True,
                "daily_amount": 100,
                "max_daily_claims": 1,
                "allow_transfers": True,
                "tax_rate_percent": 3.5,
            },
            "economy_sinks": {
                "cooldown_reset_cost": 250,
                "temp_boost_cost": 500,
                "inactivity_tax_percent": 1.0,
                "role_rename_cost": 700,
                "admin_sink_enabled": True,
                "admin_sink_min_amount": 50,
            },
            "gambling": {
                "enabled": True,
                "min_bet": 50,
                "max_bet": 2500,
                "house_edge_percent": 6.0,
                "streak_bonus": False,
            },
            "pvp": {
                "enabled": True,
                "min_bet": 50,
                "max_bet": 2500,
                "cooldown_seconds": 300,
                "max_active_duels_per_user": 1,
                "level_influence_percent": 10,
            },
            "shop": {
                "enabled": True,
                "show_out_of_stock": True,
                "highlight_discounts": True,
                "allow_temporary_items": True,
            },
            "logs": {
                "enabled": True,
                "log_channel_id": None,
                "log_moderation": True,
                "log_economy": True,
                "log_gambling": True,
            },
        },
    },
}


def _settings_dependency(category: str):
    async def dependency(
        guild_id: int, access_token: str = Depends(get_access_token)
    ) -> Dict[str, Any]:
        guilds = await fetch_user_guilds(access_token)
        ensure_guild_access(guilds, guild_id)
        config = await _get_or_create_config(guild_id)
        settings_map = _load_settings(config)
        return {
            "guild_id": guild_id,
            "config": config,
            "settings_map": settings_map,
            "category": category,
        }

    return dependency


def _require_readonly_access(request: Request) -> None:
    api_key = request.headers.get("X-Read-Only-Token", "")
    if not settings.readonly_api_key or api_key != settings.readonly_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    now = time.monotonic()
    identity = request.client.host if request.client else "unknown"
    window = _readonly_requests.setdefault(identity, [])
    window[:] = [ts for ts in window if now - ts < 60]
    if len(window) >= READONLY_RATE_LIMIT:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    window.append(now)




def _passport_settings_from_map(settings_map: Dict[str, Any]) -> PassportSettings:
    raw = settings_map.get("passport", {}) if isinstance(settings_map, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    return PassportSettings(
        enabled=bool(raw.get("enabled", True)),
        hide_balance_for_others=bool(raw.get("hide_balance_for_others", True)),
    )


@app.get("/api/guilds/{guild_id}/passport", response_model=PassportSettings)
async def get_passport_settings(context: Dict[str, Any] = Depends(_settings_dependency("passport"))):
    return _passport_settings_from_map(context["settings_map"])


@app.put("/api/guilds/{guild_id}/passport", response_model=PassportSettings)
async def update_passport_settings(
    payload: PassportSettings,
    request: Request,
    context: Dict[str, Any] = Depends(_settings_dependency("passport")),
    access_token: str = Depends(get_access_token),
):
    config = context["config"]
    settings_map = context["settings_map"]
    previous_settings = dict(settings_map.get("passport", {}))
    settings_map["passport"] = payload.dict()
    _save_settings(config, settings_map)
    async with database.session() as session:
        session.add(config)
        await session.commit()
    await _record_config_change(
        guild_id=config.guild_id,
        category="passport",
        previous_settings=previous_settings,
        new_settings=payload.dict(),
        reason=request.headers.get("X-Change-Reason", ""),
        access_token=access_token,
    )
    return payload


@app.get("/api/guilds/{guild_id}/settings", response_model=GuildSettings)
async def get_guild_settings(context: Dict[str, Any] = Depends(_settings_dependency("guild"))):
    config = context["config"]
    settings_map = context["settings_map"]
    guild_settings = settings_map.get("guild", {})
    return GuildSettings(
        server_rate=config.server_rate,
        currency_name=config.currency_name,
        **guild_settings,
    )


@app.put("/api/guilds/{guild_id}/settings", response_model=GuildSettings)
async def update_guild_settings(
    payload: GuildSettings,
    request: Request,
    context: Dict[str, Any] = Depends(_settings_dependency("guild")),
    access_token: str = Depends(get_access_token),
):
    config = context["config"]
    settings_map = context["settings_map"]
    previous_settings = settings_map.get("guild", {}).copy()
    previous_settings["server_rate"] = config.server_rate
    previous_settings["currency_name"] = config.currency_name
    config.server_rate = payload.server_rate
    config.currency_name = payload.currency_name
    settings_map["guild"] = payload.dict(exclude={"server_rate", "currency_name"})
    _save_settings(config, settings_map)
    async with database.session() as session:
        session.add(config)
        await session.commit()
    await _record_config_change(
        guild_id=config.guild_id,
        category="guild",
        previous_settings=previous_settings,
        new_settings={
            **settings_map["guild"],
            "server_rate": payload.server_rate,
            "currency_name": payload.currency_name,
        },
        reason=request.headers.get("X-Change-Reason", ""),
        access_token=access_token,
    )
    return payload




def _leveling_settings_from_map(settings_map: Dict[str, Any]) -> LevelingSettings:
    raw = settings_map.get("leveling", {}) if isinstance(settings_map, dict) else {}
    if not isinstance(raw, dict):
        raw = {}

    message = raw.get("message_xp", {}) if isinstance(raw.get("message_xp"), dict) else {}
    voice = raw.get("voice_xp", {}) if isinstance(raw.get("voice_xp"), dict) else {}
    curve = raw.get("level_curve", {}) if isinstance(raw.get("level_curve"), dict) else {}
    role_rewards = raw.get("role_rewards", {}) if isinstance(raw.get("role_rewards"), dict) else {}

    legacy_xp_per_message = raw.get("xp_per_message", 10)
    return LevelingSettings(
        enabled=bool(raw.get("enabled", True)),
        message_xp_enabled=bool(message.get("enabled", True)),
        message_xp_min_length=int(message.get("min_length", 6)),
        message_xp_cooldown_seconds=int(message.get("cooldown_seconds", raw.get("xp_cooldown_seconds", 45))),
        message_xp_min=int(message.get("xp_min", max(1, int(legacy_xp_per_message) - 2))),
        message_xp_max=int(message.get("xp_max", max(2, int(legacy_xp_per_message)))),
        message_ignore_channels=[int(v) for v in message.get("ignore_channels", []) if str(v).isdigit()],
        voice_xp_enabled=bool(voice.get("enabled", True)),
        voice_xp_per_minute=int(voice.get("xp_per_minute", 1)),
        voice_ignore_channels=[int(v) for v in voice.get("ignore_channels", []) if str(v).isdigit()],
        voice_ignore_self_deaf=bool(voice.get("ignore_self_deaf", True)),
        voice_ignore_self_mute=bool(voice.get("ignore_self_mute", False)),
        level_curve_type=str(curve.get("type", "quadratic")),
        level_curve_a=int(curve.get("a", 50)),
        level_curve_b=int(curve.get("b", 50)),
        role_rewards_enabled=bool(role_rewards.get("enabled", raw.get("rewards_roles_enabled", True))),
        announce_level_up=bool(raw.get("announce_level_up", True)),
        level_up_channel_id=raw.get("level_up_channel_id"),
        announce_cooldown_seconds=int(raw.get("announce_cooldown_seconds", 60)),
    )


def _leveling_settings_to_map(payload: LevelingSettings) -> Dict[str, Any]:
    return {
        "enabled": payload.enabled,
        "message_xp": {
            "enabled": payload.message_xp_enabled,
            "min_length": payload.message_xp_min_length,
            "cooldown_seconds": payload.message_xp_cooldown_seconds,
            "xp_min": payload.message_xp_min,
            "xp_max": payload.message_xp_max,
            "ignore_channels": [int(v) for v in payload.message_ignore_channels],
            "ignore_commands": True,
        },
        "voice_xp": {
            "enabled": payload.voice_xp_enabled,
            "xp_per_minute": payload.voice_xp_per_minute,
            "ignore_channels": [int(v) for v in payload.voice_ignore_channels],
            "ignore_self_deaf": payload.voice_ignore_self_deaf,
            "ignore_self_mute": payload.voice_ignore_self_mute,
            "require_multiple_users": True,
        },
        "level_curve": {
            "type": payload.level_curve_type,
            "a": payload.level_curve_a,
            "b": payload.level_curve_b,
        },
        "role_rewards": {"enabled": payload.role_rewards_enabled},
        "announce_level_up": payload.announce_level_up,
        "level_up_channel_id": payload.level_up_channel_id,
        "announce_cooldown_seconds": payload.announce_cooldown_seconds,
        "xp_per_message": payload.message_xp_max,
        "xp_cooldown_seconds": payload.message_xp_cooldown_seconds,
        "rewards_roles_enabled": payload.role_rewards_enabled,
    }


def _category_routes(category: str, model):
    async def get_category(context: Dict[str, Any] = Depends(_settings_dependency(category))):
        settings_map = context["settings_map"]
        return model(**settings_map.get(category, {}))

    async def update_category(
        payload: model,
        request: Request,
        context: Dict[str, Any] = Depends(_settings_dependency(category)),
        access_token: str = Depends(get_access_token),
    ):
        config = context["config"]
        settings_map = context["settings_map"]
        previous_settings = settings_map.get(category, {}).copy()
        settings_map[category] = payload.dict()
        _save_settings(config, settings_map)
        async with database.session() as session:
            session.add(config)
            await session.commit()
        await _record_config_change(
            guild_id=config.guild_id,
            category=category,
            previous_settings=previous_settings,
            new_settings=settings_map[category],
            reason=request.headers.get("X-Change-Reason", ""),
            access_token=access_token,
        )
        return payload

    async def reset_category(
        request: Request,
        context: Dict[str, Any] = Depends(_settings_dependency(category)),
        access_token: str = Depends(get_access_token),
    ):
        config = context["config"]
        settings_map = context["settings_map"]
        previous_settings = settings_map.get(category, {}).copy()
        settings_map[category] = model().dict()
        _save_settings(config, settings_map)
        async with database.session() as session:
            session.add(config)
            await session.commit()
        await _record_config_change(
            guild_id=config.guild_id,
            category=category,
            previous_settings=previous_settings,
            new_settings=settings_map[category],
            reason=request.headers.get("X-Change-Reason", ""),
            access_token=access_token,
        )
        return model()

    return get_category, update_category, reset_category



async def leveling_get(context: Dict[str, Any] = Depends(_settings_dependency("leveling"))):
    settings_map = context["settings_map"]
    return _leveling_settings_from_map(settings_map)


async def leveling_put(
    payload: LevelingSettings,
    request: Request,
    context: Dict[str, Any] = Depends(_settings_dependency("leveling")),
    access_token: str = Depends(get_access_token),
):
    config = context["config"]
    settings_map = context["settings_map"]
    previous_settings = settings_map.get("leveling", {}).copy()
    settings_map["leveling"] = _leveling_settings_to_map(payload)
    _save_settings(config, settings_map)
    async with database.session() as session:
        session.add(config)
        await session.commit()
    await _record_config_change(
        guild_id=config.guild_id,
        category="leveling",
        previous_settings=previous_settings,
        new_settings=settings_map["leveling"],
        reason=request.headers.get("X-Change-Reason", ""),
        access_token=access_token,
    )
    return payload


async def leveling_reset(
    request: Request,
    context: Dict[str, Any] = Depends(_settings_dependency("leveling")),
    access_token: str = Depends(get_access_token),
):
    config = context["config"]
    settings_map = context["settings_map"]
    previous_settings = settings_map.get("leveling", {}).copy()
    payload = LevelingSettings()
    settings_map["leveling"] = _leveling_settings_to_map(payload)
    _save_settings(config, settings_map)
    async with database.session() as session:
        session.add(config)
        await session.commit()
    await _record_config_change(
        guild_id=config.guild_id,
        category="leveling",
        previous_settings=previous_settings,
        new_settings=settings_map["leveling"],
        reason=request.headers.get("X-Change-Reason", ""),
        access_token=access_token,
    )
    return payload

economy_get, economy_put, economy_reset = _category_routes("economy", EconomySettings)
gambling_get, gambling_put, gambling_reset = _category_routes(
    "gambling", GamblingSettings
)
shop_get, shop_put, shop_reset = _category_routes("shop", ShopSettings)
logs_get, logs_put, logs_reset = _category_routes("logs", LogsSettings)
pvp_get, pvp_put, pvp_reset = _category_routes("pvp", PvpSettings)
pvp_season_get, pvp_season_put, _ = _category_routes("pvp_season", PvpSeasonSettings)
feature_get, feature_put, feature_reset = _category_routes(
    "feature_toggles", FeatureToggles
)
economy_sinks_get, economy_sinks_put, economy_sinks_reset = _category_routes(
    "economy_sinks", EconomySinkSettings
)
trust_get, trust_put, trust_reset = _category_routes(
    "trust_score", TrustScoreSettings
)
shadow_get, shadow_put, shadow_reset = _category_routes(
    "shadow_penalties", ShadowPenaltySettings
)
reports_get, reports_put, reports_reset = _category_routes("reports", ReportsSettings)
rituals_get, rituals_put, _ = _category_routes("rituals", RitualsSettings)
word_emoji_get, word_emoji_put, _ = _category_routes("word_emoji_stats", WordEmojiStatsSettings)

app.get("/api/guilds/{guild_id}/leveling", response_model=LevelingSettings)(
    leveling_get
)
app.put("/api/guilds/{guild_id}/leveling", response_model=LevelingSettings)(
    leveling_put
)
app.post("/api/guilds/{guild_id}/leveling/reset", response_model=LevelingSettings)(
    leveling_reset
)

app.get("/api/guilds/{guild_id}/economy", response_model=EconomySettings)(economy_get)
app.put("/api/guilds/{guild_id}/economy", response_model=EconomySettings)(economy_put)
app.post("/api/guilds/{guild_id}/economy/reset", response_model=EconomySettings)(
    economy_reset
)


@app.get(
    "/api/guilds/{guild_id}/economy/analytics",
    response_model=EconomyAnalyticsSummaryResponse,
)
async def get_economy_analytics(
    guild_id: int,
    period: int = 7,
    access_token: str = Depends(get_access_token),
) -> EconomyAnalyticsSummaryResponse:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    try:
        return await build_economy_analytics(
            database=database,
            guild_id=guild_id,
            period_days=period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(
    "/api/guilds/{guild_id}/economy/insights",
    response_model=list[EconomyInsight],
)
async def get_economy_insights(
    guild_id: int,
    period: int = 7,
    access_token: str = Depends(get_access_token),
) -> list[EconomyInsight]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    try:
        analytics = await build_economy_analytics(
            database=database,
            guild_id=guild_id,
            period_days=period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_economy_insights(analytics=analytics, period_days=period)


@app.get(
    "/api/guilds/{guild_id}/economy/recommendations",
    response_model=EconomyRecommendationsResponse,
)
async def get_economy_recommendations(
    guild_id: int,
    days: int = 7,
    access_token: str = Depends(get_access_token),
) -> EconomyRecommendationsResponse:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    try:
        return await build_economy_recommendations(
            database=database,
            guild_id=guild_id,
            days=days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_analytics_period(period: int) -> int:
    if period not in ALLOWED_ANALYTICS_PERIODS:
        raise HTTPException(
            status_code=400,
            detail="Допустимые значения period: 7, 30, 90.",
        )
    return period


@app.get("/api/guilds/{guild_id}/analytics/overview")
async def get_guild_analytics_overview(
    guild_id: int,
    period: int = 30,
    access_token: str = Depends(get_access_token),
) -> Dict[str, Any]:
    period_days = _validate_analytics_period(period)
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    analytics_service = AnalyticsService(database)
    analytics = await analytics_service.get_full_analytics(
        guild_id=guild_id,
        period_days=period_days,
    )
    return {
        "economy": analytics["economy"],
        "betting": analytics["betting"],
        "activity": analytics["activity"],
        "pvp": analytics.get("pvp", {}),
    }


@app.get("/api/guilds/{guild_id}/analytics/timeseries")
async def get_guild_analytics_timeseries(
    guild_id: int,
    period: int = 30,
    access_token: str = Depends(get_access_token),
) -> Dict[str, Any]:
    period_days = _validate_analytics_period(period)
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    analytics_service = AnalyticsService(database)
    analytics = await analytics_service.get_full_analytics(
        guild_id=guild_id,
        period_days=period_days,
    )
    return analytics["timeseries"]


@app.get("/api/guilds/{guild_id}/community-goal", response_model=CommunityGoalOut | None)
async def get_community_goal(
    guild_id: int,
    access_token: str = Depends(get_access_token),
) -> CommunityGoalOut | None:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        service = CommunityGoalService(session)
        goal = await service.get_active_goal(guild_id)
        if goal is None:
            result = await session.execute(
                select(CommunityGoal)
                .where(CommunityGoal.guild_id == guild_id)
                .order_by(CommunityGoal.created_at.desc())
                .limit(1)
            )
            goal = result.scalars().first()
        if goal is None:
            return None
        if goal.status == "active":
            await service.update_goal_progress(guild_id)
            await session.commit()
            await session.refresh(goal)
        return _community_goal_to_schema(goal)


@app.post("/api/guilds/{guild_id}/community-goal", response_model=CommunityGoalOut)
async def create_community_goal(
    guild_id: int,
    payload: CommunityGoalIn,
    access_token: str = Depends(get_access_token),
) -> CommunityGoalOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    starts_at = _parse_iso_datetime(payload.starts_at)
    ends_at = _parse_iso_datetime(payload.ends_at)
    if ends_at <= starts_at:
        raise HTTPException(status_code=400, detail="Дата окончания должна быть позже даты начала.")

    async with database.session() as session:
        service = CommunityGoalService(session)
        try:
            goal = await service.create_goal(
                guild_id=guild_id,
                metric_type=payload.metric_type,
                target_value=payload.target_value,
                starts_at=starts_at,
                ends_at=ends_at,
                reward_role_id=payload.reward_role_id,
                min_participation_threshold=payload.min_participation_threshold,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await session.commit()
        await session.refresh(goal)
        return _community_goal_to_schema(goal)


@app.put("/api/guilds/{guild_id}/community-goal", response_model=CommunityGoalOut)
async def update_community_goal(
    guild_id: int,
    payload: CommunityGoalUpdate,
    access_token: str = Depends(get_access_token),
) -> CommunityGoalOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    starts_at = _parse_iso_datetime(payload.starts_at)
    ends_at = _parse_iso_datetime(payload.ends_at)
    if ends_at <= starts_at:
        raise HTTPException(status_code=400, detail="Дата окончания должна быть позже даты начала.")

    async with database.session() as session:
        result = await session.execute(
            select(CommunityGoal)
            .where(CommunityGoal.guild_id == guild_id)
            .order_by(CommunityGoal.created_at.desc())
            .limit(1)
        )
        goal = result.scalars().first()
        if goal is None:
            raise HTTPException(status_code=404, detail="Цель сообщества не найдена.")

        overlap = await session.execute(
            select(CommunityGoal).where(
                (CommunityGoal.guild_id == guild_id)
                & (CommunityGoal.id != goal.id)
                & (CommunityGoal.starts_at <= ends_at)
                & (CommunityGoal.ends_at >= starts_at)
            )
        )
        if overlap.scalars().first() is not None:
            raise HTTPException(status_code=400, detail="Период цели пересекается с существующей целью.")

        if payload.status == "active":
            active = await session.execute(
                select(CommunityGoal).where(
                    (CommunityGoal.guild_id == guild_id)
                    & (CommunityGoal.status == "active")
                    & (CommunityGoal.id != goal.id)
                )
            )
            if active.scalars().first() is not None:
                raise HTTPException(status_code=400, detail="У сервера уже есть активная цель сообщества.")

        goal.metric_type = payload.metric_type
        goal.target_value = payload.target_value
        goal.starts_at = starts_at
        goal.ends_at = ends_at
        goal.reward_role_id = payload.reward_role_id
        goal.min_participation_threshold = payload.min_participation_threshold
        goal.status = payload.status

        service = CommunityGoalService(session)
        if goal.status == "active":
            await service.update_goal_progress(guild_id)

        await session.commit()
        await session.refresh(goal)
        return _community_goal_to_schema(goal)


@app.post("/api/guilds/{guild_id}/community-goal/evaluate", response_model=CommunityGoalOut | None)
async def evaluate_community_goal(
    guild_id: int,
    access_token: str = Depends(get_access_token),
) -> CommunityGoalOut | None:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        service = CommunityGoalService(session)
        goal = await service.evaluate_goal(guild_id)
        if goal is None:
            return None
        await session.commit()
        await session.refresh(goal)
        return _community_goal_to_schema(goal)


@app.get("/api/guilds/{guild_id}/monthly-goal", response_model=MonthlyGoalOut | None)
async def get_monthly_goal(
    guild_id: int,
    month: str | None = None,
    access_token: str = Depends(get_access_token),
) -> MonthlyGoalOut | None:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    month_value = month or dt.datetime.utcnow().strftime("%Y-%m")

    async with database.session() as session:
        service = MonthlyGoalService(session)
        goal = await service.get_active_goal(guild_id, month_value)
        if goal is None:
            result = await session.execute(
                select(ServerMonthlyGoal)
                .where((ServerMonthlyGoal.guild_id == guild_id) & (ServerMonthlyGoal.month == month_value))
                .order_by(ServerMonthlyGoal.created_at.desc())
                .limit(1)
            )
            goal = result.scalars().first()
        if goal is None:
            return None
        progress = await service.calculate_progress(guild_id, goal.metric_type, goal.month)
        return _monthly_goal_to_schema(goal, progress)


@app.post("/api/guilds/{guild_id}/monthly-goal", response_model=MonthlyGoalOut)
async def create_monthly_goal(
    guild_id: int,
    payload: MonthlyGoalIn,
    access_token: str = Depends(get_access_token),
) -> MonthlyGoalOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    async with database.session() as session:
        async with session.begin():
            if payload.is_active:
                existing = await session.execute(
                    select(ServerMonthlyGoal).where(
                        (ServerMonthlyGoal.guild_id == guild_id)
                        & (ServerMonthlyGoal.month == payload.month)
                        & (ServerMonthlyGoal.is_active.is_(True))
                    )
                )
                if existing.scalars().first() is not None:
                    raise HTTPException(status_code=400, detail="На этот месяц уже есть активная цель.")

            goal = ServerMonthlyGoal(
                guild_id=guild_id,
                month=payload.month,
                metric_type=payload.metric_type,
                target_value=payload.target_value,
                reward_role_id=payload.reward_role_id,
                min_user_contribution=payload.min_user_contribution,
                is_active=payload.is_active,
            )
            session.add(goal)
            await session.flush()

            service = MonthlyGoalService(session)
            progress = await service.calculate_progress(guild_id, goal.metric_type, goal.month)

        await session.refresh(goal)
        return _monthly_goal_to_schema(goal, progress)


@app.put("/api/guilds/{guild_id}/monthly-goal/{goal_id}", response_model=MonthlyGoalOut)
async def update_monthly_goal(
    guild_id: int,
    goal_id: int,
    payload: MonthlyGoalUpdate,
    access_token: str = Depends(get_access_token),
) -> MonthlyGoalOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    async with database.session() as session:
        async with session.begin():
            result = await session.execute(
                select(ServerMonthlyGoal).where(
                    (ServerMonthlyGoal.id == goal_id) & (ServerMonthlyGoal.guild_id == guild_id)
                )
            )
            goal = result.scalars().first()
            if goal is None:
                raise HTTPException(status_code=404, detail="Месячная цель не найдена.")

            if payload.is_active:
                dup = await session.execute(
                    select(ServerMonthlyGoal).where(
                        (ServerMonthlyGoal.guild_id == guild_id)
                        & (ServerMonthlyGoal.month == goal.month)
                        & (ServerMonthlyGoal.id != goal.id)
                        & (ServerMonthlyGoal.is_active.is_(True))
                    )
                )
                if dup.scalars().first() is not None:
                    raise HTTPException(status_code=400, detail="На этот месяц уже есть активная цель.")

            goal.metric_type = payload.metric_type
            goal.target_value = payload.target_value
            goal.reward_role_id = payload.reward_role_id
            goal.min_user_contribution = payload.min_user_contribution
            goal.is_active = payload.is_active

            service = MonthlyGoalService(session)
            progress = await service.calculate_progress(guild_id, goal.metric_type, goal.month)

        await session.refresh(goal)
        return _monthly_goal_to_schema(goal, progress)


@app.get("/api/analytics/behavior", response_model=BehaviorAnalyticsResponse)
async def get_behavior_analytics(
    guild_id: int,
    period: str = "7d",
    access_token: str = Depends(get_access_token),
) -> BehaviorAnalyticsResponse:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    try:
        return await build_behavior_analytics(
            database=database,
            guild_id=guild_id,
            period=period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

app.get("/api/guilds/{guild_id}/gambling", response_model=GamblingSettings)(gambling_get)
app.put("/api/guilds/{guild_id}/gambling", response_model=GamblingSettings)(gambling_put)
app.post("/api/guilds/{guild_id}/gambling/reset", response_model=GamblingSettings)(
    gambling_reset
)

app.get("/api/guilds/{guild_id}/shop", response_model=ShopSettings)(shop_get)
app.put("/api/guilds/{guild_id}/shop", response_model=ShopSettings)(shop_put)
app.post("/api/guilds/{guild_id}/shop/reset", response_model=ShopSettings)(shop_reset)

app.get("/api/guilds/{guild_id}/logs", response_model=LogsSettings)(logs_get)
app.put("/api/guilds/{guild_id}/logs", response_model=LogsSettings)(logs_put)
app.post("/api/guilds/{guild_id}/logs/reset", response_model=LogsSettings)(logs_reset)

app.get("/api/guilds/{guild_id}/reports", response_model=ReportsSettings)(reports_get)
app.put("/api/guilds/{guild_id}/reports", response_model=ReportsSettings)(reports_put)
app.post("/api/guilds/{guild_id}/reports/reset", response_model=ReportsSettings)(reports_reset)
app.get("/api/guilds/{guild_id}/rituals", response_model=RitualsSettings)(rituals_get)
app.put("/api/guilds/{guild_id}/rituals", response_model=RitualsSettings)(rituals_put)
app.get("/api/guilds/{guild_id}/word-emoji-stats", response_model=WordEmojiStatsSettings)(word_emoji_get)
app.put("/api/guilds/{guild_id}/word-emoji-stats", response_model=WordEmojiStatsSettings)(word_emoji_put)


@app.post("/api/guilds/{guild_id}/reports/monthly/dry-run", response_model=ReportsDryRunOut)
async def reports_monthly_dry_run(
    guild_id: int,
    range: str = "prev_month",
    context: Dict[str, Any] = Depends(_settings_dependency("reports")),
) -> ReportsDryRunOut:
    if range != "prev_month":
        raise HTTPException(status_code=400, detail="Only range=prev_month is supported")

    settings_map = context["settings_map"]
    report_settings = settings_map.get("reports", {})
    merged = ReportsSettings(**{**DEFAULT_REPORTS_SETTINGS, **report_settings})

    try:
        ZoneInfo(merged.timezone)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timezone: {merged.timezone}") from exc

    now = dt.datetime.now(dt.timezone.utc)
    period = calculate_previous_month_period(tz_name=merged.timezone, now_utc=now)

    async with database.session() as session:
        payload = await build_monthly_payload(
            session,
            guild_id=guild_id,
            period_start=period.period_start_utc,
            period_end=period.period_end_utc,
            tz=merged.timezone,
            include_sections=merged.monthly.include_sections.dict(),
        )

    return ReportsDryRunOut(payload=payload)


@app.post("/api/guilds/{guild_id}/reports/quarterly/dry-run", response_model=ReportsDryRunOut)
async def reports_quarterly_dry_run(
    guild_id: int,
    quarter: str = "prev",
    context: Dict[str, Any] = Depends(_settings_dependency("reports")),
) -> ReportsDryRunOut:
    settings_map = context["settings_map"]
    report_settings = settings_map.get("reports", {})
    merged = ReportsSettings(**{**DEFAULT_REPORTS_SETTINGS, **report_settings})

    try:
        ZoneInfo(merged.timezone)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timezone: {merged.timezone}") from exc

    now = dt.datetime.now(dt.timezone.utc)
    try:
        period = calculate_quarter_period(tz_name=merged.timezone, spec=quarter, now_utc=now)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with database.session() as session:
        payload = await build_quarterly_payload(
            session,
            guild_id=guild_id,
            period_start=period.period_start_utc,
            period_end=period.period_end_utc,
            tz=merged.timezone,
            include_sections=merged.quarterly.include_sections.dict(),
        )

    return ReportsDryRunOut(payload=payload)


@app.post("/api/guilds/{guild_id}/reports/yearly/dry-run", response_model=ReportsDryRunOut)
async def reports_yearly_dry_run(
    guild_id: int,
    range: str = "prev_year",
    context: Dict[str, Any] = Depends(_settings_dependency("reports")),
) -> ReportsDryRunOut:
    if range != "prev_year":
        raise HTTPException(status_code=400, detail="Only range=prev_year is supported")

    settings_map = context["settings_map"]
    report_settings = settings_map.get("reports", {})
    merged = ReportsSettings(**{**DEFAULT_REPORTS_SETTINGS, **report_settings})

    try:
        ZoneInfo(merged.timezone)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timezone: {merged.timezone}") from exc

    now = dt.datetime.now(dt.timezone.utc)
    period = calculate_previous_year_period(tz_name=merged.timezone, now_utc=now)

    async with database.session() as session:
        payload = await build_yearly_payload(
            session,
            guild_id=guild_id,
            period_start=period.period_start_utc,
            period_end=period.period_end_utc,
            tz=merged.timezone,
            include_sections=merged.yearly.include_sections.dict(),
        )

    return ReportsDryRunOut(payload=payload)


app.get("/api/guilds/{guild_id}/pvp", response_model=PvpSettings)(pvp_get)
app.put("/api/guilds/{guild_id}/pvp", response_model=PvpSettings)(pvp_put)
app.post("/api/guilds/{guild_id}/pvp/reset", response_model=PvpSettings)(pvp_reset)
app.get("/api/guilds/{guild_id}/pvp/season", response_model=PvpSeasonSettings)(pvp_season_get)
app.put("/api/guilds/{guild_id}/pvp/season", response_model=PvpSeasonSettings)(pvp_season_put)

app.get("/api/guilds/{guild_id}/feature-toggles", response_model=FeatureToggles)(
    feature_get
)
app.put("/api/guilds/{guild_id}/feature-toggles", response_model=FeatureToggles)(
    feature_put
)
app.post(
    "/api/guilds/{guild_id}/feature-toggles/reset", response_model=FeatureToggles
)(feature_reset)

app.get("/api/guilds/{guild_id}/economy-sinks", response_model=EconomySinkSettings)(
    economy_sinks_get
)
app.put("/api/guilds/{guild_id}/economy-sinks", response_model=EconomySinkSettings)(
    economy_sinks_put
)
app.post(
    "/api/guilds/{guild_id}/economy-sinks/reset",
    response_model=EconomySinkSettings,
)(economy_sinks_reset)

app.get("/api/guilds/{guild_id}/trust-score", response_model=TrustScoreSettings)(
    trust_get
)
app.put("/api/guilds/{guild_id}/trust-score", response_model=TrustScoreSettings)(
    trust_put
)
app.post(
    "/api/guilds/{guild_id}/trust-score/reset", response_model=TrustScoreSettings
)(trust_reset)

app.get("/api/guilds/{guild_id}/shadow-penalties", response_model=ShadowPenaltySettings)(
    shadow_get
)
app.put(
    "/api/guilds/{guild_id}/shadow-penalties", response_model=ShadowPenaltySettings
)(shadow_put)
app.post(
    "/api/guilds/{guild_id}/shadow-penalties/reset",
    response_model=ShadowPenaltySettings,
)(shadow_reset)


@app.get("/api/presets", response_model=list[PresetOut])
async def list_presets() -> list[PresetOut]:
    return [
        PresetOut(name=name, description=payload["description"], settings=payload["settings"])
        for name, payload in PRESETS.items()
    ]


@app.get("/api/guilds/{guild_id}/presets", response_model=list[PresetOut])
async def list_guild_presets(
    guild_id: int, access_token: str = Depends(get_access_token)
) -> list[PresetOut]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    return await list_presets()


def _estimate_economy_delta(
    current_settings: Dict[str, Any], new_settings: Dict[str, Any]
) -> Dict[str, Any]:
    current_daily = current_settings.get("daily_amount", 0)
    current_claims = current_settings.get("max_daily_claims", 1)
    new_daily = new_settings.get("daily_amount", current_daily)
    new_claims = new_settings.get("max_daily_claims", current_claims)
    delta = (new_daily * new_claims) - (current_daily * current_claims)
    return {
        "daily_payout_delta": delta,
        "currency": "per user estimate",
    }


@app.post("/api/guilds/{guild_id}/presets/{preset_name}/dry-run")
async def dry_run_preset(
    guild_id: int,
    preset_name: str,
    access_token: str = Depends(get_access_token),
) -> Dict[str, Any]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    preset = PRESETS.get(preset_name)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    config = await _get_or_create_config(guild_id)
    settings_map = _load_settings(config)
    changes = {}
    for category, new_settings in preset["settings"].items():
        current = settings_map.get(category, {})
        changes[category] = _diff_settings(current, new_settings)
    economy_delta = _estimate_economy_delta(
        settings_map.get("economy", {}), preset["settings"].get("economy", {})
    )
    return {
        "preset": preset_name,
        "changes": changes,
        "role_changes": [],
        "economy_impact": economy_delta,
        "dry_run": True,
    }


@app.post("/api/guilds/{guild_id}/presets/{preset_name}/apply")
async def apply_preset(
    guild_id: int,
    preset_name: str,
    request: Request,
    access_token: str = Depends(get_access_token),
) -> Dict[str, Any]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    preset = PRESETS.get(preset_name)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    config = await _get_or_create_config(guild_id)
    settings_map = _load_settings(config)
    previous_settings = settings_map.copy()
    settings_map.update(preset["settings"])
    _save_settings(config, settings_map)
    async with database.session() as session:
        session.add(config)
        await session.commit()
    await _record_config_change(
        guild_id=config.guild_id,
        category="preset",
        previous_settings=previous_settings,
        new_settings=settings_map,
        reason=request.headers.get("X-Change-Reason", f"Applied preset {preset_name}"),
        access_token=access_token,
    )
    return {"status": "applied", "preset": preset_name}


@app.post("/api/guilds/{guild_id}/dry-run/{category}")
async def dry_run_category(
    guild_id: int,
    category: str,
    payload: Dict[str, Any],
    access_token: str = Depends(get_access_token),
) -> Dict[str, Any]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    config = await _get_or_create_config(guild_id)
    settings_map = _load_settings(config)
    current = settings_map.get(category, {})
    changes = _diff_settings(current, payload)
    economy_delta = {}
    if category == "economy":
        economy_delta = _estimate_economy_delta(current, payload)
    return {
        "category": category,
        "changes": changes,
        "role_changes": [],
        "economy_impact": economy_delta,
        "dry_run": True,
    }


@app.get("/api/guilds/{guild_id}/overview", response_model=OverviewStats)
async def get_overview(
    guild_id: int, access_token: str = Depends(get_access_token)
) -> OverviewStats:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        member_count = await session.scalar(
            select(func.count()).select_from(UserProfile).where(UserProfile.guild_id == guild_id)
        )
        total_balance = await session.scalar(
            select(func.coalesce(func.sum(UserProfile.balance), 0)).where(
                UserProfile.guild_id == guild_id
            )
        )
        average_level = await session.scalar(
            select(func.coalesce(func.avg(UserProfile.level), 0)).where(
                UserProfile.guild_id == guild_id
            )
        )
        total_warnings = await session.scalar(
            select(func.count()).select_from(Warning).where(Warning.guild_id == guild_id)
        )
        total_shop_items = await session.scalar(
            select(func.count()).select_from(ShopItem).where(ShopItem.guild_id == guild_id)
        )
    return OverviewStats(
        guild_id=guild_id,
        member_count=member_count or 0,
        total_balance=total_balance or 0,
        average_level=float(average_level or 0),
        total_warnings=total_warnings or 0,
        total_shop_items=total_shop_items or 0,
    )


@app.get("/api/guilds/{guild_id}/history", response_model=list[ChangeHistoryEntry])
async def get_change_history(
    guild_id: int, access_token: str = Depends(get_access_token)
) -> list[ChangeHistoryEntry]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        result = await session.execute(
            select(GuildConfigHistory)
            .where(GuildConfigHistory.guild_id == guild_id)
            .order_by(GuildConfigHistory.created_at.desc())
            .limit(50)
        )
        entries = result.scalars().all()
    response = []
    for entry in entries:
        response.append(
            ChangeHistoryEntry(
                id=entry.id,
                guild_id=entry.guild_id,
                actor_id=entry.actor_id,
                category=entry.category,
                previous_settings=json.loads(entry.previous_settings),
                new_settings=json.loads(entry.new_settings),
                reason=entry.reason,
                created_at=entry.created_at.isoformat(),
            )
        )
    return response


@app.post("/api/guilds/{guild_id}/rollback/{history_id}")
async def rollback_config(
    guild_id: int,
    history_id: int,
    request: Request,
    access_token: str = Depends(get_access_token),
) -> Dict[str, Any]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        result = await session.execute(
            select(GuildConfigHistory).where(
                GuildConfigHistory.id == history_id,
                GuildConfigHistory.guild_id == guild_id,
            )
        )
        entry = result.scalars().first()
        if not entry:
            raise HTTPException(status_code=404, detail="History entry not found")
    config = await _get_or_create_config(guild_id)
    settings_map = _load_settings(config)
    previous_settings = settings_map.copy()
    restored_settings = json.loads(entry.previous_settings)
    if "server_rate" in restored_settings:
        config.server_rate = restored_settings.pop("server_rate")
    if "currency_name" in restored_settings:
        config.currency_name = restored_settings.pop("currency_name")
    settings_map.update(restored_settings)
    _save_settings(config, settings_map)
    async with database.session() as session:
        session.add(config)
        await session.commit()
    await _record_config_change(
        guild_id=config.guild_id,
        category="rollback",
        previous_settings=previous_settings,
        new_settings=settings_map,
        reason=request.headers.get("X-Change-Reason", f"Rollback {history_id}"),
        access_token=access_token,
    )
    return {"status": "rolled_back", "history_id": history_id}




@app.get("/api/guilds/{guild_id}/jobs", response_model=list[JobDefinitionOut])
async def list_jobs(guild_id: int, access_token: str = Depends(get_access_token)) -> list[JobDefinitionOut]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        result = await session.execute(select(JobDefinition).where(JobDefinition.guild_id == guild_id).order_by(JobDefinition.id))
        rows = result.scalars().all()
    return [
        JobDefinitionOut(
            id=row.id,
            guild_id=row.guild_id,
            name=row.name,
            description=row.description or "",
            enabled=bool(row.enabled),
            cooldown_seconds=int(row.cooldown_seconds or 0),
            reward_min=int(row.reward_min or 0),
            reward_max=int(row.reward_max or 0),
            fail_chance=float(row.fail_chance or 0),
            penalty_min=int(row.penalty_min or 0),
            penalty_max=int(row.penalty_max or 0),
            weight=int(row.weight or 1),
        )
        for row in rows
    ]


@app.post("/api/guilds/{guild_id}/jobs", response_model=JobDefinitionOut)
async def create_job(guild_id: int, payload: JobDefinitionIn, access_token: str = Depends(get_access_token)) -> JobDefinitionOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    if payload.reward_min > payload.reward_max:
        raise HTTPException(status_code=400, detail="reward_min должен быть <= reward_max")
    if payload.penalty_min > payload.penalty_max:
        raise HTTPException(status_code=400, detail="penalty_min должен быть <= penalty_max")
    item = JobDefinition(guild_id=guild_id, **payload.dict())
    async with database.session() as session:
        session.add(item)
        await session.commit()
        await session.refresh(item)
    return JobDefinitionOut(id=item.id, guild_id=item.guild_id, **payload.dict())


@app.put("/api/guilds/{guild_id}/jobs/{job_id}", response_model=JobDefinitionOut)
async def update_job(guild_id: int, job_id: int, payload: JobDefinitionIn, access_token: str = Depends(get_access_token)) -> JobDefinitionOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    if payload.reward_min > payload.reward_max:
        raise HTTPException(status_code=400, detail="reward_min должен быть <= reward_max")
    if payload.penalty_min > payload.penalty_max:
        raise HTTPException(status_code=400, detail="penalty_min должен быть <= penalty_max")
    async with database.session() as session:
        result = await session.execute(select(JobDefinition).where(JobDefinition.guild_id == guild_id, JobDefinition.id == job_id))
        item = result.scalars().first()
        if not item:
            raise HTTPException(status_code=404, detail="Job not found")
        for key, value in payload.dict().items():
            setattr(item, key, value)
        await session.commit()
        await session.refresh(item)
    return JobDefinitionOut(id=item.id, guild_id=item.guild_id, **payload.dict())


@app.delete("/api/guilds/{guild_id}/jobs/{job_id}")
async def delete_job(guild_id: int, job_id: int, access_token: str = Depends(get_access_token)) -> Dict[str, Any]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        result = await session.execute(select(JobDefinition).where(JobDefinition.guild_id == guild_id, JobDefinition.id == job_id))
        item = result.scalars().first()
        if not item:
            raise HTTPException(status_code=404, detail="Job not found")
        await session.delete(item)
        await session.commit()
    return {"status": "deleted"}

@app.get("/api/guilds/{guild_id}/shop/items", response_model=list[ShopItemOut])
async def list_shop_items(
    guild_id: int, access_token: str = Depends(get_access_token)
) -> list[ShopItemOut]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        result = await session.execute(
            select(ShopItem).where(ShopItem.guild_id == guild_id).order_by(ShopItem.id)
        )
        items = result.scalars().all()
    return [
        ShopItemOut(
            id=item.id,
            guild_id=item.guild_id,
            name=item.name,
            description=item.description,
            base_price=item.base_price,
            item_type=item.item_type,
            role_id=item.role_id,
            is_active=item.is_active,
            buff_json=item.buff_json,
            duration_seconds=item.duration_seconds,
            max_active_per_user=item.max_active_per_user,
            purchase_limit_per_user=item.purchase_limit_per_user,
            purchase_limit_total=item.purchase_limit_total,
            enabled=item.enabled,
        )
        for item in items
    ]


@app.post("/api/guilds/{guild_id}/shop/items", response_model=ShopItemOut)
async def create_shop_item(
    guild_id: int,
    payload: ShopItemIn,
    access_token: str = Depends(get_access_token),
) -> ShopItemOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    item = ShopItem(guild_id=guild_id, **payload.dict())
    async with database.session() as session:
        session.add(item)
        await session.commit()
        await session.refresh(item)
    return ShopItemOut(id=item.id, guild_id=item.guild_id, **payload.dict())


@app.put("/api/guilds/{guild_id}/shop/items/{item_id}", response_model=ShopItemOut)
async def update_shop_item(
    guild_id: int,
    item_id: int,
    payload: ShopItemIn,
    access_token: str = Depends(get_access_token),
) -> ShopItemOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        result = await session.execute(
            select(ShopItem).where(
                ShopItem.guild_id == guild_id, ShopItem.id == item_id
            )
        )
        item = result.scalars().first()
        if not item:
            raise HTTPException(status_code=404, detail="Shop item not found")
        for key, value in payload.dict().items():
            setattr(item, key, value)
        await session.commit()
        await session.refresh(item)
    return ShopItemOut(id=item.id, guild_id=item.guild_id, **payload.dict())


@app.delete("/api/guilds/{guild_id}/shop/items/{item_id}")
async def delete_shop_item(
    guild_id: int, item_id: int, access_token: str = Depends(get_access_token)
) -> Dict[str, Any]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        result = await session.execute(
            select(ShopItem).where(
                ShopItem.guild_id == guild_id, ShopItem.id == item_id
            )
        )
        item = result.scalars().first()
        if not item:
            raise HTTPException(status_code=404, detail="Shop item not found")
        await session.delete(item)
        await session.commit()
    return {"status": "deleted"}


@app.get("/api/guilds/{guild_id}/shop/purchases", response_model=list[ShopPurchaseLogOut])
async def list_shop_purchases(
    guild_id: int,
    days: int = 7,
    access_token: str = Depends(get_access_token),
) -> list[ShopPurchaseLogOut]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    if days not in {7, 30, 90}:
        raise HTTPException(status_code=400, detail="Допустимые значения days: 7, 30, 90.")

    since = dt.datetime.utcnow() - dt.timedelta(days=days)
    async with database.session() as session:
        result = await session.execute(
            select(ShopPurchaseLog)
            .where(ShopPurchaseLog.guild_id == guild_id, ShopPurchaseLog.purchased_at >= since)
            .order_by(desc(ShopPurchaseLog.purchased_at), desc(ShopPurchaseLog.id))
        )
        rows = result.scalars().all()

    return [
        ShopPurchaseLogOut(
            id=row.id,
            guild_id=row.guild_id,
            user_id=row.user_id,
            item_id=row.item_id,
            quantity=row.quantity,
            total_price=row.total_price,
            purchased_at=row.purchased_at.isoformat(),
        )
        for row in rows
    ]


@app.get("/api/guilds/{guild_id}/analytics/monthly-settings", response_model=AnalyticsMonthlySettings)
async def get_monthly_analytics_settings(
    guild_id: int,
    access_token: str = Depends(get_access_token),
) -> AnalyticsMonthlySettings:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    async with database.session() as session:
        config_result = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
        config = config_result.scalars().first()

        result = await session.execute(
            select(GuildFeatureFlag).where(
                GuildFeatureFlag.guild_id == guild_id,
                GuildFeatureFlag.flag_name.in_(
                    [MONTHLY_REPORTS_ENABLED_FLAG, MONTHLY_REPORTS_AUTOPOST_FLAG]
                ),
            )
        )
        overrides = {entry.flag_name: bool(entry.enabled) for entry in result.scalars().all()}

    return AnalyticsMonthlySettings(
        monthly_reports_enabled=overrides.get(MONTHLY_REPORTS_ENABLED_FLAG, False),
        monthly_reports_autopost=overrides.get(MONTHLY_REPORTS_AUTOPOST_FLAG, False),
        analytics_channel_id=(int(config.analytics_channel_id) if config and config.analytics_channel_id else None),
    )


@app.put("/api/guilds/{guild_id}/analytics/monthly-settings", response_model=AnalyticsMonthlySettings)
async def update_monthly_analytics_settings(
    guild_id: int,
    payload: AnalyticsMonthlySettings,
    access_token: str = Depends(get_access_token),
) -> AnalyticsMonthlySettings:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    async with database.session() as session:
        await _ensure_feature_flag_exists(
            session,
            flag_name=MONTHLY_REPORTS_ENABLED_FLAG,
            description="Enable monthly analytics report generation.",
        )
        await _ensure_feature_flag_exists(
            session,
            flag_name=MONTHLY_REPORTS_AUTOPOST_FLAG,
            description="Enable automatic posting of monthly analytics reports.",
        )

        await _upsert_guild_feature_flag(
            session,
            guild_id=guild_id,
            flag_name=MONTHLY_REPORTS_ENABLED_FLAG,
            enabled=payload.monthly_reports_enabled,
        )
        await _upsert_guild_feature_flag(
            session,
            guild_id=guild_id,
            flag_name=MONTHLY_REPORTS_AUTOPOST_FLAG,
            enabled=payload.monthly_reports_autopost,
        )

        result = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
        config = result.scalars().first()
        if config is None:
            config = GuildConfig(guild_id=guild_id)
            session.add(config)
        config.analytics_channel_id = payload.analytics_channel_id

        await session.commit()

    return payload


@app.get("/api/feature-flags", response_model=list[FeatureFlagState])
async def list_feature_flags(
    access_token: str = Depends(get_access_token),
) -> list[FeatureFlagState]:
    await _ensure_global_admin(access_token)
    async with database.session() as session:
        result = await session.execute(select(FeatureFlag).order_by(FeatureFlag.name))
        flags = result.scalars().all()
    return [
        FeatureFlagState(name=flag.name, enabled=flag.enabled, description=flag.description)
        for flag in flags
    ]


@app.put("/api/feature-flags/{flag_name}", response_model=FeatureFlagState)
async def upsert_feature_flag(
    flag_name: str,
    payload: FeatureFlagUpdate,
    access_token: str = Depends(get_access_token),
) -> FeatureFlagState:
    await _ensure_global_admin(access_token)
    async with database.session() as session:
        result = await session.execute(
            select(FeatureFlag).where(FeatureFlag.name == flag_name)
        )
        flag = result.scalars().first()
        if not flag:
            flag = FeatureFlag(name=flag_name)
            session.add(flag)
        flag.enabled = payload.enabled
        flag.description = payload.description
        flag.updated_at = func.now()
        await session.commit()
    return FeatureFlagState(name=flag_name, enabled=payload.enabled, description=payload.description)


@app.get("/api/guilds/{guild_id}/feature-flags", response_model=list[GuildFeatureFlagState])
async def list_guild_feature_flags(
    guild_id: int, access_token: str = Depends(get_access_token)
) -> list[GuildFeatureFlagState]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        result = await session.execute(select(FeatureFlag).order_by(FeatureFlag.name))
        global_flags = {flag.name: flag.enabled for flag in result.scalars().all()}
        result = await session.execute(
            select(GuildFeatureFlag).where(GuildFeatureFlag.guild_id == guild_id)
        )
        overrides = {flag.flag_name: flag.enabled for flag in result.scalars().all()}
    combined = []
    for name, enabled in global_flags.items():
        combined.append(
            GuildFeatureFlagState(name=name, enabled=overrides.get(name, enabled))
        )
    return combined


@app.put("/api/guilds/{guild_id}/feature-flags/{flag_name}")
async def update_guild_feature_flag(
    guild_id: int,
    flag_name: str,
    payload: GuildFeatureFlagUpdate,
    access_token: str = Depends(get_access_token),
) -> GuildFeatureFlagState:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        result = await session.execute(
            select(GuildFeatureFlag).where(
                GuildFeatureFlag.guild_id == guild_id,
                GuildFeatureFlag.flag_name == flag_name,
            )
        )
        flag = result.scalars().first()
        if not flag:
            flag = GuildFeatureFlag(guild_id=guild_id, flag_name=flag_name)
            session.add(flag)
        flag.enabled = payload.enabled
        flag.updated_at = func.now()
        await session.commit()
    return GuildFeatureFlagState(name=flag_name, enabled=payload.enabled)


@app.get("/api/guilds/{guild_id}/referral-promo/codes", response_model=list[ReferralPromoCodeOut])
async def list_referral_promo_codes(
    guild_id: int,
    access_token: str = Depends(get_access_token),
) -> list[ReferralPromoCodeOut]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    async with database.session() as session:
        result = await session.execute(
            select(ReferralCode)
            .where(ReferralCode.guild_id == guild_id)
            .order_by(ReferralCode.created_at.desc(), ReferralCode.id.desc())
        )
        codes = result.scalars().all()

    return [
        ReferralPromoCodeOut(
            id=code.id,
            guild_id=int(code.guild_id),
            code=code.code,
            reward_amount=int(code.reward_amount),
            max_uses=code.max_uses,
            expires_at=(code.expires_at.isoformat() + "Z") if code.expires_at else None,
            is_active=bool(code.is_active),
            current_uses=int(code.current_uses),
            created_at=code.created_at.isoformat() + "Z",
        )
        for code in codes
    ]


@app.post("/api/guilds/{guild_id}/referral-promo/codes", response_model=ReferralPromoCodeOut)
async def create_referral_promo_code(
    guild_id: int,
    payload: ReferralPromoCodeIn,
    access_token: str = Depends(get_access_token),
) -> ReferralPromoCodeOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    expires_at = _parse_iso_datetime(payload.expires_at) if payload.expires_at else None
    code = ReferralCode(
        guild_id=guild_id,
        creator_user_id=None,
        code=payload.code.strip().upper(),
        reward_amount=payload.reward_amount,
        max_uses=payload.max_uses,
        expires_at=expires_at,
        is_active=payload.is_active,
    )
    async with database.session() as session:
        session.add(code)
        await session.commit()
        await session.refresh(code)

    return ReferralPromoCodeOut(
        id=code.id,
        guild_id=int(code.guild_id),
        code=code.code,
        reward_amount=int(code.reward_amount),
        max_uses=code.max_uses,
        expires_at=(code.expires_at.isoformat() + "Z") if code.expires_at else None,
        is_active=bool(code.is_active),
        current_uses=int(code.current_uses),
        created_at=code.created_at.isoformat() + "Z",
    )


@app.get("/api/guilds/{guild_id}/referral-promo/stats", response_model=ReferralDashboardStats)
async def get_referral_promo_stats(
    guild_id: int,
    access_token: str = Depends(get_access_token),
) -> ReferralDashboardStats:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    async with database.session() as session:
        total_uses = await session.scalar(
            select(func.count()).select_from(ReferralUsage).where(ReferralUsage.guild_id == guild_id)
        )
        total_currency_distributed = await session.scalar(
            select(func.coalesce(func.sum(ReferralUsage.reward_amount * 2), 0)).where(
                ReferralUsage.guild_id == guild_id
            )
        )
        leaderboard_result = await session.execute(
            select(
                ReferralUsage.inviter_user_id,
                func.count(ReferralUsage.id).label("invites"),
                func.coalesce(func.sum(ReferralUsage.reward_amount), 0).label("earned"),
            )
            .where(ReferralUsage.guild_id == guild_id)
            .group_by(ReferralUsage.inviter_user_id)
            .order_by(func.count(ReferralUsage.id).desc(), func.sum(ReferralUsage.reward_amount).desc())
            .limit(10)
        )
        leaderboard = [
            {
                "user_id": int(row.inviter_user_id),
                "invites": int(row.invites or 0),
                "earned": int(row.earned or 0),
            }
            for row in leaderboard_result
        ]

    return ReferralDashboardStats(
        total_uses=int(total_uses or 0),
        total_currency_distributed=int(total_currency_distributed or 0),
        top_inviters=leaderboard,
    )


@app.get("/api/guilds/{guild_id}/analytics/referrals", response_model=ReferralRedeemSummary)
async def get_referral_analytics(
    guild_id: int,
    access_token: str = Depends(get_access_token),
) -> ReferralRedeemSummary:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    month_start = dt.datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with database.session() as session:
        monthly_referral_volume = await session.scalar(
            select(func.count()).select_from(ReferralUsage).where(
                ReferralUsage.guild_id == guild_id,
                ReferralUsage.created_at >= month_start,
            )
        )
        total_referral_payout = await session.scalar(
            select(func.coalesce(func.sum(ReferralUsage.reward_amount * 2), 0)).where(
                ReferralUsage.guild_id == guild_id
            )
        )
        top_inviters_result = await session.execute(
            select(
                ReferralUsage.inviter_user_id,
                func.count(ReferralUsage.id).label("invites"),
                func.coalesce(func.sum(ReferralUsage.reward_amount), 0).label("earned"),
            )
            .where(ReferralUsage.guild_id == guild_id)
            .group_by(ReferralUsage.inviter_user_id)
            .order_by(func.count(ReferralUsage.id).desc(), func.sum(ReferralUsage.reward_amount).desc())
            .limit(10)
        )
        top_inviters = [
            {
                "user_id": int(row.inviter_user_id),
                "invites": int(row.invites or 0),
                "earned": int(row.earned or 0),
            }
            for row in top_inviters_result
        ]

    return ReferralRedeemSummary(
        monthly_referral_volume=int(monthly_referral_volume or 0),
        total_referral_payout=int(total_referral_payout or 0),
        top_inviters=top_inviters,
    )




def _build_growth_referral_settings(settings_map: Dict[str, Any]) -> GrowthReferralCampaignSettings:
    raw = settings_map.get("referral_campaign", {})
    return GrowthReferralCampaignSettings(
        enabled=bool(raw.get("enabled", True)),
        reward_percent_referrer=float(raw.get("reward_percent_referrer", 5.0)),
        reward_percent_invited=float(raw.get("reward_percent_invited", 2.0)),
        active_threshold_messages=int(raw.get("active_threshold_messages", 20)),
        season_duration_days=int(raw.get("season_duration_days", 30)),
        max_rewards_per_user=int(raw.get("max_rewards_per_user", 0)),
        referral_min_account_age_days=int(raw.get("referral_min_account_age_days", 0)),
        referral_min_messages=int(raw.get("referral_min_messages", 0)),
        promo_cooldown_hours=int(raw.get("promo_cooldown_hours", 0)),
    )


@app.get("/api/growth/referral/settings", response_model=GrowthReferralCampaignSettings)
async def get_growth_referral_settings(
    guild_id: int,
    access_token: str = Depends(get_access_token),
) -> GrowthReferralCampaignSettings:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    await _require_growth_enabled(guild_id)
    config = await _get_or_create_config(guild_id)
    settings_map = _load_settings(config)
    return _build_growth_referral_settings(settings_map)


@app.put("/api/growth/referral/settings", response_model=GrowthReferralCampaignSettings)
async def update_growth_referral_settings(
    guild_id: int,
    payload: GrowthReferralCampaignSettings,
    request: Request,
    access_token: str = Depends(get_access_token),
) -> GrowthReferralCampaignSettings:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    await _require_growth_enabled(guild_id)
    config = await _get_or_create_config(guild_id)
    settings_map = _load_settings(config)
    previous_settings = dict(settings_map)
    settings_map["referral_campaign"] = payload.dict()
    _save_settings(config, settings_map)

    async with database.session() as session:
        session.add(config)
        await session.commit()

    await _record_config_change(
        guild_id=guild_id,
        category="growth_referral_campaign",
        previous_settings=previous_settings,
        new_settings=settings_map,
        reason=request.headers.get("X-Change-Reason", "Updated growth referral campaign settings"),
        access_token=access_token,
    )
    return payload


@app.get("/api/growth/promo", response_model=list[GrowthPromoCodeOut])
async def list_growth_promo_codes(
    guild_id: int,
    access_token: str = Depends(get_access_token),
) -> list[GrowthPromoCodeOut]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    await _require_growth_enabled(guild_id)
    async with database.session() as session:
        result = await session.execute(
            select(PromoCodeExtended)
            .where(PromoCodeExtended.guild_id == guild_id)
            .order_by(PromoCodeExtended.created_at.desc(), PromoCodeExtended.id.desc())
        )
        rows = result.scalars().all()

    return [
        GrowthPromoCodeOut(
            id=row.id,
            guild_id=int(row.guild_id),
            code=row.code,
            reward_type=row.reward_type.value,
            reward_value=float(row.reward_value),
            max_uses=row.max_total_uses,
            per_user_limit=row.max_uses_per_user,
            expires_at=(row.end_at.isoformat() if row.end_at else None),
            enabled=bool(row.is_active),
            total_uses=int(row.total_uses or 0),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


@app.post("/api/growth/promo", response_model=GrowthPromoCodeOut)
async def create_growth_promo_code(
    guild_id: int,
    payload: GrowthPromoCodeIn,
    access_token: str = Depends(get_access_token),
) -> GrowthPromoCodeOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    await _require_growth_enabled(guild_id)
    actor_id = await _get_actor_id(access_token)
    expires_at = _parse_iso_datetime(payload.expires_at) if payload.expires_at else None

    code = PromoCodeExtended(
        guild_id=guild_id,
        campaign_id=None,
        code=payload.code.strip().upper(),
        reward_type=PromoRewardType(payload.reward_type),
        reward_value=payload.reward_value,
        max_total_uses=payload.max_uses,
        max_uses_per_user=payload.per_user_limit,
        is_active=payload.enabled,
        end_at=expires_at,
        created_by_admin_id=(actor_id or 0),
    )
    async with database.session() as session:
        session.add(code)
        await session.commit()
        await session.refresh(code)

    return GrowthPromoCodeOut(
        id=code.id,
        guild_id=int(code.guild_id),
        code=code.code,
        reward_type=code.reward_type.value,
        reward_value=float(code.reward_value),
        max_uses=code.max_total_uses,
        per_user_limit=code.max_uses_per_user,
        expires_at=(code.end_at.isoformat() if code.end_at else None),
        enabled=bool(code.is_active),
        total_uses=int(code.total_uses or 0),
        created_at=code.created_at.isoformat(),
    )


@app.put("/api/growth/promo/{promo_id}", response_model=GrowthPromoCodeOut)
async def update_growth_promo_code(
    promo_id: int,
    guild_id: int,
    payload: GrowthPromoCodeIn,
    access_token: str = Depends(get_access_token),
) -> GrowthPromoCodeOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    await _require_growth_enabled(guild_id)

    expires_at = _parse_iso_datetime(payload.expires_at) if payload.expires_at else None

    async with database.session() as session:
        result = await session.execute(
            select(PromoCodeExtended).where(
                PromoCodeExtended.id == promo_id,
                PromoCodeExtended.guild_id == guild_id,
            )
        )
        code = result.scalars().first()
        if code is None:
            raise HTTPException(status_code=404, detail="Промо-код не найден")

        code.code = payload.code.strip().upper()
        code.reward_type = PromoRewardType(payload.reward_type)
        code.reward_value = payload.reward_value
        code.max_total_uses = payload.max_uses
        code.max_uses_per_user = payload.per_user_limit
        code.end_at = expires_at
        code.is_active = payload.enabled

        await session.commit()
        await session.refresh(code)

    return GrowthPromoCodeOut(
        id=code.id,
        guild_id=int(code.guild_id),
        code=code.code,
        reward_type=code.reward_type.value,
        reward_value=float(code.reward_value),
        max_uses=code.max_total_uses,
        per_user_limit=code.max_uses_per_user,
        expires_at=(code.end_at.isoformat() if code.end_at else None),
        enabled=bool(code.is_active),
        total_uses=int(code.total_uses or 0),
        created_at=code.created_at.isoformat(),
    )


@app.delete("/api/growth/promo/{promo_id}")
async def delete_growth_promo_code(
    promo_id: int,
    guild_id: int,
    access_token: str = Depends(get_access_token),
) -> Dict[str, Any]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    await _require_growth_enabled(guild_id)
    async with database.session() as session:
        result = await session.execute(
            select(PromoCodeExtended).where(
                PromoCodeExtended.id == promo_id,
                PromoCodeExtended.guild_id == guild_id,
            )
        )
        code = result.scalars().first()
        if code is None:
            raise HTTPException(status_code=404, detail="Промо-код не найден")

        await session.delete(code)
        await session.commit()

    return {"status": "deleted"}


@app.get("/api/guilds/{guild_id}/growth/promos/{promo_id}/stats", response_model=GrowthPromoStats)
async def get_growth_promo_stats(
    guild_id: int,
    promo_id: int,
    access_token: str = Depends(get_access_token),
) -> GrowthPromoStats:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    await _require_growth_enabled(guild_id)

    async with database.session() as session:
        promo = await session.scalar(
            select(PromoCodeExtended).where(
                PromoCodeExtended.guild_id == guild_id,
                PromoCodeExtended.id == promo_id,
            )
        )
        if promo is None:
            raise HTTPException(status_code=404, detail="Промо-код не найден")

        usage = (
            await session.execute(
                select(
                    func.count(PromoCodeUsage.id).label("total_uses"),
                    func.count(func.distinct(PromoCodeUsage.user_id)).label("unique_users"),
                    func.coalesce(func.sum(PromoCodeUsage.reward_amount), 0).label("total_currency_issued"),
                    func.coalesce(func.avg(PromoCodeUsage.reward_amount), 0).label("average_reward"),
                ).where(
                    PromoCodeUsage.guild_id == guild_id,
                    PromoCodeUsage.promo_code_id == promo_id,
                )
            )
        ).one()

        top_users_rows = await session.execute(
            select(
                PromoCodeUsage.user_id,
                func.coalesce(func.sum(PromoCodeUsage.reward_amount), 0).label("total_reward"),
            )
            .where(
                PromoCodeUsage.guild_id == guild_id,
                PromoCodeUsage.promo_code_id == promo_id,
            )
            .group_by(PromoCodeUsage.user_id)
            .order_by(func.sum(PromoCodeUsage.reward_amount).desc(), PromoCodeUsage.user_id.asc())
            .limit(5)
        )

        net_new_users = await session.scalar(
            select(func.count(func.distinct(ReferralRelationship.invited_user_id))).where(
                ReferralRelationship.guild_id == guild_id,
                ReferralRelationship.activated_at.is_not(None),
                ReferralRelationship.invited_at >= promo.created_at,
            )
        )

    total_issued = int(usage.total_currency_issued or 0)
    net_new = int(net_new_users or 0)
    per_user_cost = (total_issued / net_new) if net_new > 0 else float(total_issued)
    if per_user_cost > 1500:
        roi_indicator = "aggressive"
        suggestion = "Награда распределяется слишком щедро — рекомендуется снизить reward_value."
    elif per_user_cost < 300:
        roi_indicator = "low"
        suggestion = "Распределение консервативное — можно аккуратно повысить reward_value для роста."
    else:
        roi_indicator = "balanced"
        suggestion = "Текущие параметры промо выглядят сбалансированными."

    return GrowthPromoStats(
        total_uses=int(usage.total_uses or 0),
        unique_users=int(usage.unique_users or 0),
        total_currency_issued=total_issued,
        average_reward=float(usage.average_reward or 0.0),
        top_5_users_by_reward=[
            GrowthPromoUserReward(user_id=int(row.user_id), total_reward=int(row.total_reward or 0))
            for row in top_users_rows
        ],
        roi=GrowthPromoRoi(
            promo_id=promo_id,
            total_issued_currency=total_issued,
            net_new_users=net_new,
            roi_indicator=roi_indicator,
            suggestion=suggestion,
        ),
    )


@app.get("/api/guilds/{guild_id}/growth/referrals/stats", response_model=GrowthReferralStats)
async def get_growth_referral_stats(
    guild_id: int,
    access_token: str = Depends(get_access_token),
) -> GrowthReferralStats:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    await _require_growth_enabled(guild_id)

    async with database.session() as session:
        total_referrals = await session.scalar(
            select(func.count()).select_from(ReferralRelationship).where(ReferralRelationship.guild_id == guild_id)
        )
        successful_referrals = await session.scalar(
            select(func.count()).select_from(ReferralRelationship).where(
                ReferralRelationship.guild_id == guild_id,
                ReferralRelationship.activated_at.is_not(None),
            )
        )
        total_currency_paid = await session.scalar(
            select(func.coalesce(func.sum(ReferralReward.amount), 0)).where(ReferralReward.guild_id == guild_id)
        )
        top_rows = await session.execute(
            select(
                ReferralRelationship.inviter_user_id,
                func.count(ReferralRelationship.id).label("total_referrals"),
                func.coalesce(func.sum(ReferralRelationship.total_reward_paid), 0).label("total_currency_paid"),
            )
            .where(ReferralRelationship.guild_id == guild_id)
            .group_by(ReferralRelationship.inviter_user_id)
            .order_by(func.count(ReferralRelationship.id).desc(), ReferralRelationship.inviter_user_id.asc())
            .limit(10)
        )

    total = int(total_referrals or 0)
    success = int(successful_referrals or 0)
    paid = int(total_currency_paid or 0)
    return GrowthReferralStats(
        total_referrals=total,
        successful_referrals=success,
        pending_referrals=max(0, total - success),
        total_currency_paid=paid,
        average_reward=float((paid / success) if success > 0 else 0.0),
        top_10_referrers=[
            GrowthReferrerStatsRow(
                user_id=int(row.inviter_user_id),
                total_referrals=int(row.total_referrals or 0),
                total_currency_paid=int(row.total_currency_paid or 0),
            )
            for row in top_rows
        ],
    )


def _parse_growth_range(value: str | None) -> tuple[str, int]:
    allowed = {"7d": 7, "30d": 30, "90d": 90}
    if value is None:
        return "30d", 30
    normalized = value.strip().lower()
    if normalized not in allowed:
        raise HTTPException(status_code=422, detail="range must be one of: 7d, 30d, 90d")
    return normalized, allowed[normalized]


def _build_growth_series(days: int, aggregates: dict[str, int], now: dt.datetime) -> list[GrowthDailyMetricPoint]:
    start_day = (now - dt.timedelta(days=days - 1)).date()
    points: list[GrowthDailyMetricPoint] = []
    for offset in range(days):
        current_day = start_day + dt.timedelta(days=offset)
        key = current_day.isoformat()
        points.append(GrowthDailyMetricPoint(day=key, value=int(aggregates.get(key, 0) or 0)))
    return points


def _to_growth_recommendations(
    conversion_rate: float,
    roi_ratio: float,
    net_growth_value: int,
    total_referrals: int,
) -> list[GrowthRecommendation]:
    recommendations: list[GrowthRecommendation] = []

    if conversion_rate < 0.25:
        recommendations.append(
            GrowthRecommendation(
                level="warning",
                text="Конверсия рефералов ниже 25%: рекомендуется снизить процент награды приглашённому пользователю.",
            )
        )

    if roi_ratio < 1:
        recommendations.append(
            GrowthRecommendation(
                level="warning",
                text="ROI ниже 1: рекомендуется снизить процент награды рефереру для контроля затрат.",
            )
        )

    if conversion_rate >= 0.4 and roi_ratio >= 1 and net_growth_value > 0 and total_referrals >= 10:
        recommendations.append(
            GrowthRecommendation(
                level="info",
                text="Высокий рост и положительный ROI: можно увеличить лимиты кампании для масштабирования.",
            )
        )

    if not recommendations:
        recommendations.append(
            GrowthRecommendation(
                level="info",
                text="Метрики стабильны: продолжайте мониторинг, текущие настройки выглядят сбалансированными.",
            )
        )

    return recommendations


@app.get("/api/growth/overview", response_model=GrowthOverviewResponse)
async def get_growth_overview(
    guild_id: int,
    range: str = "30d",
    access_token: str = Depends(get_access_token),
) -> GrowthOverviewResponse:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)

    await _require_growth_enabled(guild_id)

    range_label, period_days = _parse_growth_range(range)
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=period_days)

    async with database.session() as session:
        total_referrals = await session.scalar(
            select(func.count()).select_from(ReferralRelationship).where(
                ReferralRelationship.guild_id == guild_id
            )
        )
        active_referrals = await session.scalar(
            select(func.count()).select_from(ReferralRelationship).where(
                ReferralRelationship.guild_id == guild_id,
                ReferralRelationship.activated_at.is_not(None),
            )
        )
        total_rewards_paid = await session.scalar(
            select(func.coalesce(func.sum(ReferralReward.amount), 0)).where(
                ReferralReward.guild_id == guild_id
            )
        )
        total_promo_redemptions = await session.scalar(
            select(func.count()).select_from(PromoCodeUsage).where(PromoCodeUsage.guild_id == guild_id)
        )

        top_referrers_result = await session.execute(
            select(
                ReferralRelationship.inviter_user_id,
                func.count(ReferralRelationship.id).label("total_referrals"),
                func.coalesce(func.sum(case((ReferralRelationship.activated_at.is_not(None), 1), else_=0)), 0).label("active_referrals"),
                func.coalesce(func.sum(ReferralRelationship.total_reward_paid), 0).label("total_rewards_paid"),
            )
            .where(ReferralRelationship.guild_id == guild_id)
            .group_by(ReferralRelationship.inviter_user_id)
            .order_by(func.count(ReferralRelationship.id).desc())
            .limit(10)
        )

        top_referrers = [
            GrowthTopReferrer(
                user_id=int(row.inviter_user_id),
                total_referrals=int(row.total_referrals or 0),
                active_referrals=int(row.active_referrals or 0),
                total_rewards_paid=int(row.total_rewards_paid or 0),
            )
            for row in top_referrers_result
        ]

        most_used_result = await session.execute(
            select(PromoCodeExtended)
            .where(PromoCodeExtended.guild_id == guild_id)
            .order_by(PromoCodeExtended.total_uses.desc(), PromoCodeExtended.id.asc())
            .limit(1)
        )
        most_used_entity = most_used_result.scalars().first()

        registration_rows = await session.execute(
            select(
                func.date(ReferralRelationship.invited_at).label("day"),
                func.count(ReferralRelationship.id).label("value"),
            )
            .where(
                ReferralRelationship.guild_id == guild_id,
                ReferralRelationship.invited_at >= cutoff,
            )
            .group_by(func.date(ReferralRelationship.invited_at))
            .order_by(func.date(ReferralRelationship.invited_at).asc())
        )
        registrations_map = {str(row.day): int(row.value or 0) for row in registration_rows}

        active_referral_rows = await session.execute(
            select(
                func.date(ReferralRelationship.activated_at).label("day"),
                func.count(ReferralRelationship.id).label("value"),
            )
            .where(
                ReferralRelationship.guild_id == guild_id,
                ReferralRelationship.activated_at.is_not(None),
                ReferralRelationship.activated_at >= cutoff,
            )
            .group_by(func.date(ReferralRelationship.activated_at))
            .order_by(func.date(ReferralRelationship.activated_at).asc())
        )
        active_referrals_map = {str(row.day): int(row.value or 0) for row in active_referral_rows}

        promo_rows = await session.execute(
            select(
                func.date(PromoCodeUsage.used_at).label("day"),
                func.count(PromoCodeUsage.id).label("value"),
            )
            .where(
                PromoCodeUsage.guild_id == guild_id,
                PromoCodeUsage.used_at >= cutoff,
            )
            .group_by(func.date(PromoCodeUsage.used_at))
            .order_by(func.date(PromoCodeUsage.used_at).asc())
        )
        promo_redemptions_map = {str(row.day): int(row.value or 0) for row in promo_rows}

        rewards_rows = await session.execute(
            select(
                func.date(ReferralReward.created_at).label("day"),
                func.coalesce(func.sum(ReferralReward.amount), 0).label("value"),
            )
            .where(
                ReferralReward.guild_id == guild_id,
                ReferralReward.created_at >= cutoff,
            )
            .group_by(func.date(ReferralReward.created_at))
            .order_by(func.date(ReferralReward.created_at).asc())
        )
        rewards_paid_map = {str(row.day): int(row.value or 0) for row in rewards_rows}

        referred_revenue_sum = await session.scalar(
            select(func.coalesce(func.sum(ReferralRelationship.lifetime_revenue_generated), 0)).where(
                ReferralRelationship.guild_id == guild_id,
                ReferralRelationship.invited_at >= cutoff,
            )
        )

    most_used = None
    if most_used_entity is not None:
        most_used = GrowthMostUsedPromo(
            id=most_used_entity.id,
            code=most_used_entity.code,
            total_uses=int(most_used_entity.total_uses or 0),
        )

    registrations_per_day = _build_growth_series(period_days, registrations_map, now)
    active_referrals_per_day = _build_growth_series(period_days, active_referrals_map, now)
    promo_redemptions_per_day = _build_growth_series(period_days, promo_redemptions_map, now)
    rewards_paid_per_day = _build_growth_series(period_days, rewards_paid_map, now)

    period_registrations = sum(point.value for point in registrations_per_day)
    period_active_referrals = sum(point.value for point in active_referrals_per_day)
    period_rewards_paid = sum(point.value for point in rewards_paid_per_day)
    period_promo_redemptions = sum(point.value for point in promo_redemptions_per_day)

    total_revenue = int(referred_revenue_sum or 0)
    net_growth_value = int(total_revenue - period_rewards_paid)

    referral_conversion_rate = (
        (period_active_referrals / period_registrations) if period_registrations > 0 else 0.0
    )
    avg_revenue_per_referral = (total_revenue / period_registrations) if period_registrations > 0 else 0.0
    roi_ratio = (total_revenue / period_rewards_paid) if period_rewards_paid > 0 else 0.0

    recommendations = _to_growth_recommendations(
        conversion_rate=referral_conversion_rate,
        roi_ratio=roi_ratio,
        net_growth_value=net_growth_value,
        total_referrals=period_registrations,
    )

    return GrowthOverviewResponse(
        range=range_label,
        total_referrals=int(total_referrals or 0),
        active_referrals=int(active_referrals or 0),
        total_rewards_paid=int(total_rewards_paid or 0),
        total_promo_redemptions=int(total_promo_redemptions or 0),
        registrations_per_day=registrations_per_day,
        active_referrals_per_day=active_referrals_per_day,
        promo_redemptions_per_day=promo_redemptions_per_day,
        rewards_paid_per_day=rewards_paid_per_day,
        net_growth_value=net_growth_value,
        referral_conversion_rate=float(referral_conversion_rate),
        avg_revenue_per_referral=float(avg_revenue_per_referral),
        roi_ratio=float(roi_ratio),
        recommendations=recommendations,
        top_referrers=top_referrers,
        most_used_promo=most_used,
    )


@app.get("/api/public/guilds/{guild_id}/stats")
async def readonly_stats(guild_id: int, request: Request) -> OverviewStats:
    _require_readonly_access(request)
    async with database.session() as session:
        member_count = await session.scalar(
            select(func.count()).select_from(UserProfile).where(UserProfile.guild_id == guild_id)
        )
        total_balance = await session.scalar(
            select(func.coalesce(func.sum(UserProfile.balance), 0)).where(
                UserProfile.guild_id == guild_id
            )
        )
        average_level = await session.scalar(
            select(func.coalesce(func.avg(UserProfile.level), 0)).where(
                UserProfile.guild_id == guild_id
            )
        )
        total_warnings = await session.scalar(
            select(func.count()).select_from(Warning).where(Warning.guild_id == guild_id)
        )
        total_shop_items = await session.scalar(
            select(func.count()).select_from(ShopItem).where(ShopItem.guild_id == guild_id)
        )
    return OverviewStats(
        guild_id=guild_id,
        member_count=member_count or 0,
        total_balance=total_balance or 0,
        average_level=float(average_level or 0),
        total_warnings=total_warnings or 0,
        total_shop_items=total_shop_items or 0,
    )


@app.get("/api/public/guilds/{guild_id}/leaderboard")
async def readonly_leaderboard(guild_id: int, request: Request) -> Dict[str, Any]:
    _require_readonly_access(request)
    async with database.session() as session:
        result = await session.execute(
            select(UserProfile)
            .where(UserProfile.guild_id == guild_id)
            .order_by(UserProfile.level.desc(), UserProfile.xp.desc())
            .limit(10)
        )
        users = result.scalars().all()
    leaderboard = [
        {"user_id": user.user_id, "level": user.level, "xp": user.xp, "balance": user.balance}
        for user in users
    ]
    return {"guild_id": guild_id, "leaderboard": leaderboard}


@app.get("/{page}.html", response_class=HTMLResponse)
async def serve_page(page: str) -> HTMLResponse:
    file_path = STATIC_DIR / f"{page}.html"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    content = file_path.read_text(encoding="utf-8")
    return HTMLResponse(content=content, media_type="text/html; charset=utf-8")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


async def _resolve_guild_name(access_token: str, guild_id: int) -> str:
    guilds = await fetch_user_guilds(access_token)
    for guild in guilds:
        if str(guild.get("id")) == str(guild_id):
            return str(guild.get("name") or guild_id)
    return str(guild_id)


@app.get("/api/presence/settings", response_model=PresenceSettings)
async def get_presence_settings(access_token: str = Depends(get_access_token)) -> PresenceSettings:
    await _ensure_global_admin(access_token)
    async with database.session() as session:
        payload = await PresenceSettingsService.get(session)
    return PresenceSettings(**payload)


@app.put("/api/presence/settings", response_model=PresenceSettings)
async def update_presence_settings(payload: PresenceSettings, access_token: str = Depends(get_access_token)) -> PresenceSettings:
    await _ensure_global_admin(access_token)
    async with database.session() as session:
        merged = await PresenceSettingsService.save(session, payload.model_dump())
    return PresenceSettings(**merged)


@app.post("/api/presence/preview", response_model=PresencePreviewOut)
async def preview_presence_settings(
    guild_id: int | None = None,
    access_token: str = Depends(get_access_token),
) -> PresencePreviewOut:
    await _ensure_global_admin(access_token)
    async with database.session() as session:
        settings = await PresenceSettingsService.get(session)

        selected_guild_id = guild_id or settings.get("primary_guild_id")
        if not selected_guild_id:
            guilds = await fetch_user_guilds(access_token)
            if not guilds:
                raise HTTPException(status_code=400, detail="No available guilds")
            selected_guild_id = int(guilds[0]["id"])

        guild_name = await _resolve_guild_name(access_token, int(selected_guild_id))
        provider = PresenceDataProvider()

        class _GuildStub:
            def __init__(self, _id: int, _name: str):
                self.id = _id
                self.name = _name
                self.member_count = None
                self.members = []

        ctx = await provider.get_context(session, _GuildStub(int(selected_guild_id), guild_name))
        rendered = []
        for tpl in settings.get("templates", []):
            text = render_presence_text(str(tpl.get("text", "")), ctx)
            if text:
                rendered.append(text)

    return PresencePreviewOut(guild_id=int(selected_guild_id), rendered=rendered)


app.include_router(betting_router)


async def _build_top_stats(session, model, guild_id: int, days: int, key_column: str) -> tuple[list[dict], list[dict]]:
    start_day = dt.datetime.utcnow().date() - dt.timedelta(days=days - 1)
    key_attr = getattr(model, key_column)

    top_rows = await session.execute(
        select(key_attr.label("k"), func.coalesce(func.sum(model.count), 0).label("c"))
        .where((model.guild_id == guild_id) & (model.day >= start_day))
        .group_by(key_attr)
        .order_by(desc("c"))
        .limit(20)
    )
    top = [{"key": str(r.k), "count": int(r.c or 0)} for r in top_rows]

    series_rows = await session.execute(
        select(model.day, func.coalesce(func.sum(model.count), 0).label("c"))
        .where((model.guild_id == guild_id) & (model.day >= start_day))
        .group_by(model.day)
        .order_by(model.day.asc())
    )
    series = [{"day": r.day.isoformat(), "count": int(r.c or 0)} for r in series_rows]
    return top, series


@app.get("/api/guilds/{guild_id}/stats/words", response_model=WordEmojiStatsResponse)
async def get_words_stats(
    guild_id: int,
    days: int = 30,
    access_token: str = Depends(get_access_token),
) -> WordEmojiStatsResponse:
    period_days = _validate_analytics_period(days)
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        top, series = await _build_top_stats(session, WordStatDaily, guild_id, period_days, "token")
    return WordEmojiStatsResponse(guild_id=guild_id, days=period_days, top=top, series=series)


@app.get("/api/guilds/{guild_id}/stats/emojis", response_model=WordEmojiStatsResponse)
async def get_emojis_stats(
    guild_id: int,
    days: int = 30,
    access_token: str = Depends(get_access_token),
) -> WordEmojiStatsResponse:
    period_days = _validate_analytics_period(days)
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        top, series = await _build_top_stats(session, EmojiStatDaily, guild_id, period_days, "emoji_key")
    return WordEmojiStatsResponse(guild_id=guild_id, days=period_days, top=top, series=series)


def _default_growth_settings() -> GrowthSettings:
    return GrowthSettings()


def _get_growth_settings_map(settings_map: Dict[str, Any]) -> Dict[str, Any]:
    raw = settings_map.get("growth", {})
    return raw if isinstance(raw, dict) else {}


@app.get("/api/guilds/{guild_id}/growth", response_model=GrowthSettings)
async def get_growth_settings(
    guild_id: int,
    access_token: str = Depends(get_access_token),
) -> GrowthSettings:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    config = await _get_or_create_config(guild_id)
    settings_map = _load_settings(config)
    merged = _default_growth_settings().dict()
    merged.update(_get_growth_settings_map(settings_map))
    return GrowthSettings(**merged)


@app.put("/api/guilds/{guild_id}/growth", response_model=GrowthSettings)
async def put_growth_settings(
    guild_id: int,
    payload: GrowthSettings,
    request: Request,
    access_token: str = Depends(get_access_token),
) -> GrowthSettings:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    config = await _get_or_create_config(guild_id)
    settings_map = _load_settings(config)
    previous_settings = dict(settings_map)
    settings_map["growth"] = payload.dict()
    _save_settings(config, settings_map)
    async with database.session() as session:
        session.add(config)
        await session.commit()
    await _record_config_change(
        guild_id=guild_id,
        category="growth",
        previous_settings=previous_settings,
        new_settings=settings_map,
        reason=request.headers.get("X-Change-Reason", "Updated growth settings"),
        access_token=access_token,
    )
    return payload


@app.get("/api/guilds/{guild_id}/growth/campaigns", response_model=list[PromoCampaignOut])
async def list_growth_campaigns(guild_id: int, access_token: str = Depends(get_access_token)) -> list[PromoCampaignOut]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        result = await session.execute(
            select(PromoCampaignV2).where(PromoCampaignV2.guild_id == guild_id).order_by(PromoCampaignV2.id.desc())
        )
        rows = result.scalars().all()
    return [PromoCampaignOut(id=int(r.id), guild_id=int(r.guild_id), name=r.name, description=r.description, status=r.status, starts_at=r.starts_at.isoformat() if r.starts_at else None, ends_at=r.ends_at.isoformat() if r.ends_at else None, created_at=r.created_at.isoformat(), updated_at=r.updated_at.isoformat()) for r in rows]


@app.post("/api/guilds/{guild_id}/growth/campaigns", response_model=PromoCampaignOut)
async def create_growth_campaign(guild_id: int, payload: PromoCampaignIn, access_token: str = Depends(get_access_token)) -> PromoCampaignOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    row = PromoCampaignV2(
        guild_id=guild_id,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        starts_at=_parse_iso_datetime(payload.starts_at) if payload.starts_at else None,
        ends_at=_parse_iso_datetime(payload.ends_at) if payload.ends_at else None,
    )
    async with database.session() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return PromoCampaignOut(id=int(row.id), guild_id=int(row.guild_id), name=row.name, description=row.description, status=row.status, starts_at=row.starts_at.isoformat() if row.starts_at else None, ends_at=row.ends_at.isoformat() if row.ends_at else None, created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat())


@app.put("/api/guilds/{guild_id}/growth/campaigns/{campaign_id}", response_model=PromoCampaignOut)
async def update_growth_campaign(guild_id: int, campaign_id: int, payload: PromoCampaignIn, access_token: str = Depends(get_access_token)) -> PromoCampaignOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        row = (await session.execute(select(PromoCampaignV2).where(PromoCampaignV2.guild_id == guild_id, PromoCampaignV2.id == campaign_id))).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        row.name = payload.name
        row.description = payload.description
        row.status = payload.status
        row.starts_at = _parse_iso_datetime(payload.starts_at) if payload.starts_at else None
        row.ends_at = _parse_iso_datetime(payload.ends_at) if payload.ends_at else None
        await session.commit()
        await session.refresh(row)
    return PromoCampaignOut(id=int(row.id), guild_id=int(row.guild_id), name=row.name, description=row.description, status=row.status, starts_at=row.starts_at.isoformat() if row.starts_at else None, ends_at=row.ends_at.isoformat() if row.ends_at else None, created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat())


@app.delete("/api/guilds/{guild_id}/growth/campaigns/{campaign_id}")
async def delete_growth_campaign(guild_id: int, campaign_id: int, access_token: str = Depends(get_access_token)) -> dict[str, bool]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        row = (await session.execute(select(PromoCampaignV2).where(PromoCampaignV2.guild_id == guild_id, PromoCampaignV2.id == campaign_id))).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        await session.delete(row)
        await session.commit()
    return {"ok": True}


@app.get("/api/guilds/{guild_id}/growth/promo/codes", response_model=list[PromoCodeV2Out])
async def list_growth_promo_codes_v2(guild_id: int, access_token: str = Depends(get_access_token)) -> list[PromoCodeV2Out]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        rows = (await session.execute(select(PromoCodeV2).where(PromoCodeV2.guild_id == guild_id).order_by(PromoCodeV2.id.desc()))).scalars().all()
    return [PromoCodeV2Out(id=int(r.id), guild_id=int(r.guild_id), campaign_id=r.campaign_id, code=r.code, reward_type=r.reward_type, reward_value=float(r.reward_value), currency_cap=r.currency_cap, total_uses_limit=r.total_uses_limit, per_user_uses_limit=int(r.per_user_uses_limit), min_account_age_days=r.min_account_age_days, only_new_users=bool(r.only_new_users), allowed_role_ids_json=r.allowed_role_ids_json, enabled=bool(r.enabled), created_at=r.created_at.isoformat(), updated_at=r.updated_at.isoformat()) for r in rows]


@app.get("/api/guilds/{guild_id}/growth/overview", response_model=GrowthOverviewV2)
async def growth_overview_v2(guild_id: int, days: int = 30, access_token: str = Depends(get_access_token)) -> GrowthOverviewV2:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    if days not in {7, 30, 90}:
        raise HTTPException(status_code=422, detail="days must be one of 7,30,90")
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    async with database.session() as session:
        promo_total_redemptions = await session.scalar(select(func.count()).select_from(PromoRedemptionV2).where(PromoRedemptionV2.guild_id == guild_id, PromoRedemptionV2.redeemed_at >= cutoff))
        promo_total_payout = await session.scalar(select(func.coalesce(func.sum(PromoRedemptionV2.reward_amount), 0)).where(PromoRedemptionV2.guild_id == guild_id, PromoRedemptionV2.redeemed_at >= cutoff))
        referrals_pending = await session.scalar(select(func.count()).select_from(ReferralAttributionV2).where(ReferralAttributionV2.guild_id == guild_id, ReferralAttributionV2.status == "pending"))
        referrals_activated = await session.scalar(select(func.count()).select_from(ReferralAttributionV2).where(ReferralAttributionV2.guild_id == guild_id, ReferralAttributionV2.status == "activated"))
        referrals_total_rewards = await session.scalar(select(func.coalesce(func.sum(ReferralRewardV2.reward_amount), 0)).where(ReferralRewardV2.guild_id == guild_id, ReferralRewardV2.rewarded_at >= cutoff))
        top_rows = await session.execute(select(ReferralAttributionV2.referrer_user_id, func.count(ReferralAttributionV2.id).label("total_referrals")).where(ReferralAttributionV2.guild_id == guild_id).group_by(ReferralAttributionV2.referrer_user_id).order_by(desc(func.count(ReferralAttributionV2.id))).limit(5))
    return GrowthOverviewV2(days=days, promo_total_redemptions=int(promo_total_redemptions or 0), promo_total_payout=int(promo_total_payout or 0), referrals_pending=int(referrals_pending or 0), referrals_activated=int(referrals_activated or 0), referrals_total_rewards=int(referrals_total_rewards or 0), top_referrers=[GrowthTopReferrer(user_id=int(r.referrer_user_id), total_referrals=int(r.total_referrals or 0), active_referrals=0, total_rewards_paid=0) for r in top_rows])

@app.post("/api/guilds/{guild_id}/growth/promo/codes", response_model=PromoCodeV2Out)
async def create_growth_promo_code_v2(guild_id: int, payload: PromoCodeV2In, access_token: str = Depends(get_access_token)) -> PromoCodeV2Out:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    row = PromoCodeV2(guild_id=guild_id, campaign_id=payload.campaign_id, code=payload.code.strip().upper(), reward_type=payload.reward_type, reward_value=float(payload.reward_value), currency_cap=payload.currency_cap, total_uses_limit=payload.total_uses_limit, per_user_uses_limit=payload.per_user_uses_limit, min_account_age_days=payload.min_account_age_days, only_new_users=payload.only_new_users, allowed_role_ids_json=payload.allowed_role_ids_json, enabled=payload.enabled)
    async with database.session() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return PromoCodeV2Out(id=int(row.id), guild_id=int(row.guild_id), campaign_id=row.campaign_id, code=row.code, reward_type=row.reward_type, reward_value=float(row.reward_value), currency_cap=row.currency_cap, total_uses_limit=row.total_uses_limit, per_user_uses_limit=int(row.per_user_uses_limit), min_account_age_days=row.min_account_age_days, only_new_users=bool(row.only_new_users), allowed_role_ids_json=row.allowed_role_ids_json, enabled=bool(row.enabled), created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat())


@app.put("/api/guilds/{guild_id}/growth/promo/codes/{code_id}", response_model=PromoCodeV2Out)
async def update_growth_promo_code_v2(guild_id: int, code_id: int, payload: PromoCodeV2In, access_token: str = Depends(get_access_token)) -> PromoCodeV2Out:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        row = (await session.execute(select(PromoCodeV2).where(PromoCodeV2.guild_id == guild_id, PromoCodeV2.id == code_id))).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Promo code not found")
        row.campaign_id = payload.campaign_id
        row.code = payload.code.strip().upper()
        row.reward_type = payload.reward_type
        row.reward_value = float(payload.reward_value)
        row.currency_cap = payload.currency_cap
        row.total_uses_limit = payload.total_uses_limit
        row.per_user_uses_limit = payload.per_user_uses_limit
        row.min_account_age_days = payload.min_account_age_days
        row.only_new_users = payload.only_new_users
        row.allowed_role_ids_json = payload.allowed_role_ids_json
        row.enabled = payload.enabled
        await session.commit()
        await session.refresh(row)
    return PromoCodeV2Out(id=int(row.id), guild_id=int(row.guild_id), campaign_id=row.campaign_id, code=row.code, reward_type=row.reward_type, reward_value=float(row.reward_value), currency_cap=row.currency_cap, total_uses_limit=row.total_uses_limit, per_user_uses_limit=int(row.per_user_uses_limit), min_account_age_days=row.min_account_age_days, only_new_users=bool(row.only_new_users), allowed_role_ids_json=row.allowed_role_ids_json, enabled=bool(row.enabled), created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat())


@app.delete("/api/guilds/{guild_id}/growth/promo/codes/{code_id}")
async def delete_growth_promo_code_v2(guild_id: int, code_id: int, access_token: str = Depends(get_access_token)) -> dict[str, bool]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        row = (await session.execute(select(PromoCodeV2).where(PromoCodeV2.guild_id == guild_id, PromoCodeV2.id == code_id))).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Promo code not found")
        await session.delete(row)
        await session.commit()
    return {"ok": True}


@app.get("/api/guilds/{guild_id}/growth/promo/redemptions")
async def growth_promo_redemptions(guild_id: int, days: int = 30, access_token: str = Depends(get_access_token)) -> dict[str, int]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    async with database.session() as session:
        total = await session.scalar(select(func.count()).select_from(PromoRedemptionV2).where(PromoRedemptionV2.guild_id == guild_id, PromoRedemptionV2.redeemed_at >= cutoff))
        payout = await session.scalar(select(func.coalesce(func.sum(PromoRedemptionV2.reward_amount), 0)).where(PromoRedemptionV2.guild_id == guild_id, PromoRedemptionV2.redeemed_at >= cutoff))
    return {"days": days, "total_redemptions": int(total or 0), "total_payout": int(payout or 0)}


@app.get("/api/guilds/{guild_id}/growth/referrals/leaderboard")
async def growth_referrals_leaderboard(guild_id: int, days: int = 30, access_token: str = Depends(get_access_token)) -> list[dict[str, int]]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    async with database.session() as session:
        rows = await session.execute(select(ReferralAttributionV2.referrer_user_id, func.count(ReferralAttributionV2.id).label("activations")).where(ReferralAttributionV2.guild_id == guild_id, ReferralAttributionV2.status == "activated", ReferralAttributionV2.activated_at >= cutoff).group_by(ReferralAttributionV2.referrer_user_id).order_by(desc(func.count(ReferralAttributionV2.id))).limit(50))
    return [{"user_id": int(r.referrer_user_id), "activations": int(r.activations or 0)} for r in rows]


def _goal_template_to_schema(row: GuildGoalTemplate) -> MonthlyGoalTemplateOut:
    return MonthlyGoalTemplateOut(
        id=int(row.id),
        guild_id=int(row.guild_id),
        name=row.name,
        description=row.description,
        goal_type=row.goal_type,
        target_value=int(row.target_value),
        eligibility_type=row.eligibility_type,
        eligibility_min_value=int(row.eligibility_min_value),
        enabled=bool(row.enabled),
        created_at=row.created_at.isoformat() + "Z",
        updated_at=row.updated_at.isoformat() + "Z",
    )


def _current_goal_to_schema(goal: GuildMonthlyGoal, eligible_count: int) -> MonthlyGoalCurrentOut:
    now = dt.datetime.utcnow()
    percent = (float(goal.progress_value) / float(goal.target_value) * 100.0) if goal.target_value > 0 else 0.0
    days_left = max(0, int((goal.ends_at - now).total_seconds() // 86400))
    return MonthlyGoalCurrentOut(
        id=int(goal.id),
        guild_id=int(goal.guild_id),
        month=goal.month.isoformat(),
        template_id=goal.template_id,
        goal_type=goal.goal_type,
        target_value=int(goal.target_value),
        progress_value=int(goal.progress_value),
        status=goal.status,
        started_at=goal.started_at.isoformat() + "Z",
        ends_at=goal.ends_at.isoformat() + "Z",
        closed_at=goal.closed_at.isoformat() + "Z" if goal.closed_at else None,
        reward_role_id=goal.reward_role_id,
        announce_channel_id=goal.announce_channel_id,
        summary_message_id=goal.summary_message_id,
        percent_completed=max(0.0, min(100.0, percent)),
        days_left=days_left,
        eligible_count=int(eligible_count),
    )


@app.get("/api/guilds/{guild_id}/monthly-goals/settings", response_model=MonthlyGoalsSettings)
async def get_monthly_goals_settings(guild_id: int, access_token: str = Depends(get_access_token)) -> MonthlyGoalsSettings:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    cfg = await _get_or_create_config(guild_id)
    settings = MonthlyCommunityGoalService.parse_settings(cfg.settings)
    return MonthlyGoalsSettings(**settings)


@app.put("/api/guilds/{guild_id}/monthly-goals/settings", response_model=MonthlyGoalsSettings)
async def update_monthly_goals_settings(guild_id: int, payload: MonthlyGoalsSettings, access_token: str = Depends(get_access_token)) -> MonthlyGoalsSettings:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        cfg = (await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))).scalars().first()
        if cfg is None:
            cfg = GuildConfig(guild_id=guild_id)
            session.add(cfg)
            await session.flush()
        cfg.settings = MonthlyCommunityGoalService.save_settings(cfg.settings, payload.model_dump())
        await session.commit()
    return payload


@app.get("/api/guilds/{guild_id}/monthly-goals/templates", response_model=list[MonthlyGoalTemplateOut])
async def list_monthly_goal_templates(guild_id: int, access_token: str = Depends(get_access_token)) -> list[MonthlyGoalTemplateOut]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        rows = (await session.execute(select(GuildGoalTemplate).where(GuildGoalTemplate.guild_id == guild_id).order_by(GuildGoalTemplate.id.asc()))).scalars().all()
        return [_goal_template_to_schema(r) for r in rows]


@app.post("/api/guilds/{guild_id}/monthly-goals/templates", response_model=MonthlyGoalTemplateOut)
async def create_monthly_goal_template(guild_id: int, payload: MonthlyGoalTemplateIn, access_token: str = Depends(get_access_token)) -> MonthlyGoalTemplateOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        row = GuildGoalTemplate(guild_id=guild_id, **payload.model_dump())
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _goal_template_to_schema(row)


@app.put("/api/guilds/{guild_id}/monthly-goals/templates/{template_id}", response_model=MonthlyGoalTemplateOut)
async def update_monthly_goal_template(guild_id: int, template_id: int, payload: MonthlyGoalTemplateIn, access_token: str = Depends(get_access_token)) -> MonthlyGoalTemplateOut:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        row = (await session.execute(select(GuildGoalTemplate).where((GuildGoalTemplate.guild_id == guild_id) & (GuildGoalTemplate.id == template_id)))).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Template not found")
        for k, v in payload.model_dump().items():
            setattr(row, k, v)
        await session.commit()
        await session.refresh(row)
        return _goal_template_to_schema(row)


@app.delete("/api/guilds/{guild_id}/monthly-goals/templates/{template_id}")
async def delete_monthly_goal_template(guild_id: int, template_id: int, access_token: str = Depends(get_access_token)) -> dict[str, bool]:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        row = (await session.execute(select(GuildGoalTemplate).where((GuildGoalTemplate.guild_id == guild_id) & (GuildGoalTemplate.id == template_id)))).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Template not found")
        await session.delete(row)
        await session.commit()
    return {"ok": True}


@app.get("/api/guilds/{guild_id}/monthly-goals/current", response_model=MonthlyGoalCurrentOut | None)
async def get_monthly_goal_current(guild_id: int, access_token: str = Depends(get_access_token)) -> MonthlyGoalCurrentOut | None:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        row = (await session.execute(select(GuildMonthlyGoal).where(GuildMonthlyGoal.guild_id == guild_id).order_by(GuildMonthlyGoal.month.desc()))).scalars().first()
        if row is None:
            return None
        eligible = await session.scalar(select(func.count()).select_from(GuildMonthlyGoalContribution).where((GuildMonthlyGoalContribution.goal_id == row.id) & (GuildMonthlyGoalContribution.eligible.is_(True))))
        return _current_goal_to_schema(row, int(eligible or 0))


@app.post("/api/guilds/{guild_id}/monthly-goals/current/force-close")
async def force_close_monthly_goal(guild_id: int, access_token: str = Depends(get_access_token)) -> dict:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        service = MonthlyCommunityGoalService(session)
        row = (await session.execute(select(GuildMonthlyGoal).where((GuildMonthlyGoal.guild_id == guild_id) & (GuildMonthlyGoal.closed_at.is_(None))).order_by(GuildMonthlyGoal.month.desc()))).scalars().first()
        if row is None:
            return {"ok": True, "closed": False, "reason": "no_open_goal"}
        guild_obj = app.state.bot.get_guild(guild_id) if hasattr(app.state, "bot") else None
        if guild_obj is None:
            return {"ok": False, "closed": False, "reason": "guild_not_loaded"}
        await service.recalc_progress(guild_id, int(row.id), row.started_at, row.ends_at)
        await service.recalc_contributions(guild_id, int(row.id), row.started_at, row.ends_at)
        result = await service.close_monthly_goal(guild_obj, int(row.id), dt.datetime.utcnow())
        await session.commit()
        return {"ok": True, **result}


@app.get("/api/guilds/{guild_id}/monthly-goals/current/dry-run")
async def dry_run_monthly_goal(guild_id: int, access_token: str = Depends(get_access_token)) -> dict:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    async with database.session() as session:
        row = (await session.execute(select(GuildMonthlyGoal).where(GuildMonthlyGoal.guild_id == guild_id).order_by(GuildMonthlyGoal.month.desc()))).scalars().first()
        if row is None:
            return {"ok": True, "exists": False}
        eligible = await session.scalar(select(func.count()).select_from(GuildMonthlyGoalContribution).where((GuildMonthlyGoalContribution.goal_id == row.id) & (GuildMonthlyGoalContribution.eligible.is_(True))))
        return {
            "ok": True,
            "exists": True,
            "goal_id": int(row.id),
            "status": row.status,
            "progress_value": int(row.progress_value),
            "target_value": int(row.target_value),
            "eligible_count": int(eligible or 0),
            "will_complete": int(row.progress_value) >= int(row.target_value),
            "will_rotate_role": bool(row.reward_role_id),
        }
