from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.middleware.sessions import SessionMiddleware

from bot.database.db import Database
from bot.database.models import Base, GuildConfig, ShopItem, UserProfile, Warning

from .config import settings
from .schemas import (
    EconomySettings,
    GamblingSettings,
    GuildSettings,
    LevelingSettings,
    LogsSettings,
    OverviewStats,
    ShopItemIn,
    ShopItemOut,
    ShopSettings,
)
from .security import (
    DISCORD_API_BASE,
    encrypt_token,
    ensure_guild_access,
    fetch_user,
    fetch_user_guilds,
    get_access_token,
)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AniBot Web Admin", version="2.0")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)


database = Database(settings.database_url)


@app.on_event("startup")
async def startup() -> None:
    if not settings.session_secret:
        raise RuntimeError("SESSION_SECRET is required")
    await database.init_models(Base.metadata)


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
    payload: GuildSettings, context: Dict[str, Any] = Depends(_settings_dependency("guild"))
):
    config = context["config"]
    settings_map = context["settings_map"]
    config.server_rate = payload.server_rate
    config.currency_name = payload.currency_name
    settings_map["guild"] = payload.dict(exclude={"server_rate", "currency_name"})
    _save_settings(config, settings_map)
    async with database.session() as session:
        session.add(config)
        await session.commit()
    return payload


def _category_routes(category: str, model):
    async def get_category(context: Dict[str, Any] = Depends(_settings_dependency(category))):
        settings_map = context["settings_map"]
        return model(**settings_map.get(category, {}))

    async def update_category(
        payload: model, context: Dict[str, Any] = Depends(_settings_dependency(category))
    ):
        config = context["config"]
        settings_map = context["settings_map"]
        settings_map[category] = payload.dict()
        _save_settings(config, settings_map)
        async with database.session() as session:
            session.add(config)
            await session.commit()
        return payload

    async def reset_category(context: Dict[str, Any] = Depends(_settings_dependency(category))):
        config = context["config"]
        settings_map = context["settings_map"]
        settings_map[category] = model().dict()
        _save_settings(config, settings_map)
        async with database.session() as session:
            session.add(config)
            await session.commit()
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


@app.get("/{page}.html")
async def serve_page(page: str) -> FileResponse:
    file_path = STATIC_DIR / f"{page}.html"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(file_path)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
