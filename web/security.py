from __future__ import annotations

import base64
from typing import Any, Dict, List

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, status

from .config import settings

DISCORD_API_BASE = "https://discord.com/api"
ADMINISTRATOR_BIT = 0x8
MANAGE_GUILD_BIT = 0x20


def _get_fernet() -> Fernet:
    if not settings.session_encryption_key:
        raise RuntimeError("SESSION_ENCRYPTION_KEY is required")
    key = settings.session_encryption_key
    if len(key) != 44:
        key = base64.urlsafe_b64encode(key.encode("utf-8").ljust(32, b"0"))
    return Fernet(key)


def encrypt_token(token: str) -> str:
    return _get_fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token: str) -> str:
    return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def get_access_token(request: Request) -> str:
    encrypted_token = request.session.get("access_token")
    if not encrypted_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")
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
