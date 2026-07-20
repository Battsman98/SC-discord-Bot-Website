import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

import aiohttp
from fastapi import HTTPException, Request

from src.config import Settings


DISCORD_API_BASE_URL = "https://discord.com/api/v10"
MANAGE_GUILD_PERMISSION = 0x20
ADMINISTRATOR_PERMISSION = 0x8
SESSION_COOKIE_NAME = "game_assist_session"
OAUTH_STATE_COOKIE_NAME = "game_assist_oauth_state"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class WebUser:
    id: int
    username: str
    display_name: str
    avatar_url: str | None
    roles: tuple[int, ...]
    guild_permissions: int
    can_manage_changes: bool
    can_manage_admin: bool


def discord_auth_configured(settings: Settings) -> bool:
    return bool(
        settings.discord_client_id
        and settings.discord_client_secret
        and settings.discord_redirect_uri
        and settings.discord_guild_id
        and settings.discord_token
    )


def oauth_state() -> str:
    return secrets.token_urlsafe(32)


def build_discord_authorize_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": "identify",
        "state": state,
        "prompt": "none",
    }
    query = "&".join(f"{key}={_quote(value)}" for key, value in params.items())
    return f"https://discord.com/oauth2/authorize?{query}"


async def exchange_discord_code(settings: Settings, code: str) -> dict[str, Any]:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{DISCORD_API_BASE_URL}/oauth2/token",
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.discord_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            payload = await response.json()
            if response.status >= 400:
                raise HTTPException(status_code=401, detail="Discord login failed.")
            return payload


async def fetch_web_user(settings: Settings, access_token: str) -> WebUser:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{DISCORD_API_BASE_URL}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as response:
            user_payload = await response.json()
            if response.status >= 400:
                raise HTTPException(status_code=401, detail="Could not read Discord user.")

        user_id = int(user_payload["id"])
        member_payload = await _fetch_guild_member(session, settings, user_id)
        role_ids = tuple(int(role_id) for role_id in member_payload.get("roles", []))
        permissions = await _resolve_member_permissions(session, settings, role_ids)

    username = str(user_payload.get("username") or "")
    global_name = user_payload.get("global_name")
    discriminator = user_payload.get("discriminator")
    display_name = str(global_name or username)
    if discriminator and discriminator != "0":
        username = f"{username}#{discriminator}"

    return WebUser(
        id=user_id,
        username=username,
        display_name=display_name,
        avatar_url=_avatar_url(user_payload),
        roles=role_ids,
        guild_permissions=permissions,
        can_manage_changes=can_manage_change_commands(settings, role_ids, permissions),
        can_manage_admin=can_manage_admin_commands(settings, user_id, role_ids, permissions),
    )


async def _fetch_guild_member(
    session: aiohttp.ClientSession,
    settings: Settings,
    user_id: int,
) -> dict[str, Any]:
    async with session.get(
        f"{DISCORD_API_BASE_URL}/guilds/{settings.discord_guild_id}/members/{user_id}",
        headers={"Authorization": f"Bot {settings.discord_token}"},
    ) as response:
        payload = await response.json()
        if response.status == 404:
            raise HTTPException(status_code=403, detail="You are not a member of the configured Discord server.")
        if response.status >= 400:
            raise HTTPException(status_code=403, detail="Could not verify Discord server membership.")
        return payload


async def _resolve_member_permissions(
    session: aiohttp.ClientSession,
    settings: Settings,
    role_ids: tuple[int, ...],
) -> int:
    role_set = {int(settings.discord_guild_id or 0), *role_ids}
    async with session.get(
        f"{DISCORD_API_BASE_URL}/guilds/{settings.discord_guild_id}/roles",
        headers={"Authorization": f"Bot {settings.discord_token}"},
    ) as response:
        roles = await response.json()
        if response.status >= 400:
            raise HTTPException(status_code=403, detail="Could not read Discord role permissions.")

    permissions = 0
    for role in roles:
        role_id = int(role.get("id", 0))
        if role_id in role_set:
            permissions |= int(role.get("permissions", "0"))
    return permissions


def can_manage_change_commands(settings: Settings, role_ids: tuple[int, ...], permissions: int) -> bool:
    if settings.exec_admin_role_ids:
        return bool(set(role_ids).intersection(settings.exec_admin_role_ids))
    return has_manage_guild(permissions)


def can_manage_admin_commands(
    settings: Settings,
    user_id: int,
    role_ids: tuple[int, ...],
    permissions: int,
) -> bool:
    if user_id in settings.bot_admin_user_ids:
        return True
    if settings.bot_admin_role_ids:
        return bool(set(role_ids).intersection(settings.bot_admin_role_ids))
    return has_manage_guild(permissions)


def has_manage_guild(permissions: int) -> bool:
    return bool(permissions & ADMINISTRATOR_PERMISSION or permissions & MANAGE_GUILD_PERMISSION)


def encode_session(user: WebUser, secret: str) -> str:
    payload = {
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "avatar_url": user.avatar_url,
            "roles": list(user.roles),
            "guild_permissions": user.guild_permissions,
            "can_manage_changes": user.can_manage_changes,
            "can_manage_admin": user.can_manage_admin,
        },
        "expires_at": int(time.time()) + SESSION_TTL_SECONDS,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_text = _b64encode(payload_bytes)
    signature = _sign(payload_text, secret)
    return f"{payload_text}.{signature}"


def decode_session(value: str | None, secret: str) -> WebUser | None:
    if not value or not secret or "." not in value:
        return None
    payload_text, signature = value.rsplit(".", 1)
    if not hmac.compare_digest(_sign(payload_text, secret), signature):
        return None
    try:
        payload = json.loads(_b64decode(payload_text))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("expires_at", 0)) <= int(time.time()):
        return None
    user = payload.get("user")
    if not isinstance(user, dict):
        return None
    return WebUser(
        id=int(user["id"]),
        username=str(user.get("username") or ""),
        display_name=str(user.get("display_name") or ""),
        avatar_url=user.get("avatar_url"),
        roles=tuple(int(role_id) for role_id in user.get("roles", [])),
        guild_permissions=int(user.get("guild_permissions", 0)),
        can_manage_changes=bool(user.get("can_manage_changes")),
        can_manage_admin=bool(user.get("can_manage_admin")),
    )


def current_user_from_request(request: Request, settings: Settings) -> WebUser | None:
    secret = session_secret(settings)
    return decode_session(request.cookies.get(SESSION_COOKIE_NAME), secret)


def session_secret(settings: Settings) -> str:
    return settings.web_session_secret or settings.web_admin_token or settings.discord_client_secret


def _avatar_url(user_payload: dict[str, Any]) -> str | None:
    avatar = user_payload.get("avatar")
    if not avatar:
        return None
    extension = "gif" if str(avatar).startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user_payload['id']}/{avatar}.{extension}?size=128"


def _sign(payload_text: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_text.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _quote(value: object) -> str:
    from urllib.parse import quote

    return quote(str(value), safe="")
