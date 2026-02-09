from __future__ import annotations

from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

import json
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.middleware.sessions import SessionMiddleware

from bot.database.db import Database
from bot.database.migrations import MIGRATIONS
from bot.database.models import (
    Base,
    FeatureFlag,
    GuildConfig,
    GuildConfigHistory,
    GuildFeatureFlag,
    ShopItem,
    UserProfile,
    Warning,
)

from .config import settings
from .schemas import (
    ChangeHistoryEntry,
    EconomyAnalyticsResponse,
    EconomySettings,
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
    OverviewStats,
    PresetOut,
    ShopItemIn,
    ShopItemOut,
    ShopSettings,
    ShadowPenaltySettings,
    TrustScoreSettings,
)
from .security import (
    DISCORD_API_BASE,
    encrypt_token,
    ensure_guild_access,
    fetch_user,
    fetch_user_guilds,
    get_access_token,
)
from .observability import request_logger, setup_logging

setup_logging()

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AniBot Web Admin", version="2.0")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.middleware("http")(request_logger())


database = Database(settings.database_url)
_readonly_requests: Dict[str, List[float]] = {}
READONLY_RATE_LIMIT = 60


@app.on_event("startup")
async def startup() -> None:
    if not settings.session_secret:
        raise RuntimeError("SESSION_SECRET is required")
    await database.apply_migrations(MIGRATIONS)


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/login.html")


@app.get("/auth/login")
async def login() -> RedirectResponse:
    if not settings.discord_client_id or not settings.discord_redirect_uri:
        raise HTTPException(status_code=500, detail="Discord OAuth not configured")
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": "identify guilds",
    }
    query = httpx.QueryParams(params)
    return RedirectResponse(
        url=f"https://discord.com/oauth2/authorize?{query}", status_code=302
    )


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str) -> RedirectResponse:
    if not settings.discord_client_secret or not settings.discord_redirect_uri:
        raise HTTPException(status_code=500, detail="Discord OAuth not configured")
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
                "xp_per_message": 12,
                "xp_cooldown_seconds": 75,
                "announce_level_up": True,
                "rewards_roles_enabled": True,
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
                "xp_per_message": 10,
                "xp_cooldown_seconds": 90,
                "announce_level_up": False,
                "rewards_roles_enabled": True,
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
                "xp_per_message": 18,
                "xp_cooldown_seconds": 45,
                "announce_level_up": True,
                "rewards_roles_enabled": True,
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
                "xp_per_message": 14,
                "xp_cooldown_seconds": 60,
                "announce_level_up": True,
                "rewards_roles_enabled": False,
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


leveling_get, leveling_put, leveling_reset = _category_routes(
    "leveling", LevelingSettings
)
economy_get, economy_put, economy_reset = _category_routes("economy", EconomySettings)
gambling_get, gambling_put, gambling_reset = _category_routes(
    "gambling", GamblingSettings
)
shop_get, shop_put, shop_reset = _category_routes("shop", ShopSettings)
logs_get, logs_put, logs_reset = _category_routes("logs", LogsSettings)
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


def _mock_economy_analytics(guild_id: int, period: int) -> EconomyAnalyticsResponse:
    # TODO: заменить мок-генерацию на реальные агрегации из economy_ledger и профилей.
    period_scale = {7: 1.0, 30: 1.6, 90: 2.4}.get(period, 1.0)
    guild_modifier = 1 + ((guild_id % 7) * 0.03)
    scale = period_scale * guild_modifier

    total_currency = int(120000 * scale)
    average_balance = round(750 * scale, 2)
    median_balance = int(430 * scale)
    active_users = int(180 * scale)

    generated = int(42000 * scale)
    removed = int(36000 * scale)
    net_flow = generated - removed

    points = 7 if period == 7 else 8 if period == 30 else 12
    label_prefix = "День" if period == 7 else "Неделя"
    series = []
    base_generated = generated / points
    base_removed = removed / points
    for index in range(points):
        generated_point = int(base_generated * (0.9 + (index % 4) * 0.05))
        removed_point = int(base_removed * (0.85 + (index % 3) * 0.06))
        series.append(
            {
                "label": f"{label_prefix} {index + 1}",
                "generated": generated_point,
                "removed": removed_point,
                "net": generated_point - removed_point,
            }
        )

    ratio = round(removed / generated, 2) if generated else 0.0
    if ratio < 0.85:
        inflation = "inflating"
        interpretation = (
            "Источники валюты доминируют над sink-механиками — риск роста цен."
        )
    elif ratio > 1.1:
        inflation = "deflating"
        interpretation = "Списания превышают начисления — возможен дефицит валюты."
    else:
        inflation = "stable"
        interpretation = "Соотношение источников и sink-механик выглядит сбалансированным."

    warnings = []
    if ratio < 0.75:
        warnings.append(
            {
                "code": "source_dominance",
                "message": "Источники валюты существенно превышают списания.",
                "severity": "warning",
            }
        )
    if ratio > 1.25:
        warnings.append(
            {
                "code": "sink_pressure",
                "message": "Списания значительно выше начислений.",
                "severity": "warning",
            }
        )
    if net_flow > generated * 0.35:
        warnings.append(
            {
                "code": "net_flow_spike",
                "message": "Чистый приток валюты выше ожидаемого порога.",
                "severity": "info",
            }
        )

    return EconomyAnalyticsResponse(
        period=period,
        is_mocked=True,
        overview={
            "total_currency": total_currency,
            "average_balance": average_balance,
            "median_balance": median_balance,
            "active_users": active_users,
        },
        flow={
            "generated": generated,
            "removed": removed,
            "net_flow": net_flow,
            "series": series,
        },
        top_activity={
            "earners": [
                {"user_id": 101, "user_name": "Neo", "amount": int(8200 * scale)},
                {"user_id": 102, "user_name": "Luna", "amount": int(7600 * scale)},
                {"user_id": 103, "user_name": "Kira", "amount": int(7100 * scale)},
                {"user_id": 104, "user_name": "Rin", "amount": int(6900 * scale)},
                {"user_id": 105, "user_name": "Mira", "amount": int(6600 * scale)},
            ],
            "spenders": [
                {"user_id": 201, "user_name": "Dex", "amount": int(7900 * scale)},
                {"user_id": 202, "user_name": "Aki", "amount": int(7400 * scale)},
                {"user_id": 203, "user_name": "Zoe", "amount": int(7000 * scale)},
                {"user_id": 204, "user_name": "Kai", "amount": int(6700 * scale)},
                {"user_id": 205, "user_name": "Noa", "amount": int(6400 * scale)},
            ],
        },
        health={
            "inflation_indicator": inflation,
            "sink_source_ratio": ratio,
            "warnings": warnings,
            "interpretation": interpretation,
        },
    )


@app.get(
    "/api/guilds/{guild_id}/economy/analytics",
    response_model=EconomyAnalyticsResponse,
)
async def get_economy_analytics(
    guild_id: int,
    period: int = 7,
    access_token: str = Depends(get_access_token),
) -> EconomyAnalyticsResponse:
    guilds = await fetch_user_guilds(access_token)
    ensure_guild_access(guilds, guild_id)
    if period not in (7, 30, 90):
        raise HTTPException(status_code=400, detail="Unsupported analytics period")
    # TODO: заменить мок-данные на реальные агрегаты по economy_ledger.
    return _mock_economy_analytics(guild_id, period)

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


@app.get("/api/feature-flags", response_model=list[FeatureFlagState])
async def list_feature_flags(
    access_token: str = Depends(get_access_token),
) -> list[FeatureFlagState]:
    await fetch_user(access_token)
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
    await fetch_user(access_token)
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


@app.get("/{page}.html")
async def serve_page(page: str) -> FileResponse:
    file_path = STATIC_DIR / f"{page}.html"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(file_path)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
