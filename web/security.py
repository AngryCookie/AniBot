from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, status

from .config import settings

DISCORD_API_BASE = "https://discord.com/api"
ADMINISTRATOR_BIT = 0x8
MANAGE_GUILD_BIT = 0x20
logger = logging.getLogger(__name__)


def _build_fernet(key: str) -> Fernet:
    try:
        return Fernet(key)
    except ValueError as exc:
        raise RuntimeError(
            "SESSION_ENCRYPTION_KEY must be a valid Fernet key (32 url-safe base64-encoded bytes)"
        ) from exc


def validate_session_encryption_key() -> None:
    if not settings.session_encryption_key:
        logger.error("SESSION_ENCRYPTION_KEY is missing; web app startup aborted")
        raise RuntimeError("SESSION_ENCRYPTION_KEY is required")

    try:
        _build_fernet(settings.session_encryption_key)
    except RuntimeError as exc:
        logger.error("Invalid SESSION_ENCRYPTION_KEY: %s", exc)
        raise


def _get_fernet() -> Fernet:
    return _build_fernet(settings.session_encryption_key)


def encrypt_token(token: str) -> str:
    return _get_fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token: str) -> str:
    return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def get_access_token(request: Request) -> str:
    cookies = getattr(request, "cookies", {}) or {}
    session = getattr(request, "session", {}) or {}
    cookie_present = settings.session_cookie_name in cookies
    session_keys = sorted(session.keys())
    logger.info(
        "session.access_token.request",
        extra={"cookie_present": cookie_present, "session_keys": session_keys},
    )

    encrypted_token = session.get("access_token")
    if not encrypted_token:
        logger.info("session.access_token.missing", extra={"cookie_present": cookie_present, "session_keys": session_keys})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")

    expires_at = int(session.get("expires_at", 0) or 0)
    if expires_at and expires_at <= int(time.time()):
        session.clear()
        logger.info("session.access_token.expired", extra={"expires_at": expires_at})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    return decrypt_token(encrypted_token)


async def fetch_user(access_token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Discord session"
        )
    return response.json()


async def fetch_user_guilds(access_token: str) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DISCORD_API_BASE}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unable to fetch guilds"
        )
    return response.json()


def has_guild_permission(guild: Dict[str, Any]) -> bool:
    permissions = int(guild.get("permissions", 0))
    return bool(permissions & (ADMINISTRATOR_BIT | MANAGE_GUILD_BIT))


def ensure_guild_access(guilds: List[Dict[str, Any]], guild_id: int) -> Dict[str, Any]:
    for guild in guilds:
        if int(guild.get("id", 0)) == guild_id and has_guild_permission(guild):
            return guild
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
