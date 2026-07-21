import asyncio
import difflib
import html
import re
from io import BytesIO
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.bot import (
    CZ_TIMER_DEFINITIONS,
    CZ_TIMERS_CACHE_KEY,
    EXEC_OVERRIDE_CACHE_KEY,
    _has_mining_multi_separator,
    _mining_multi_search_terms,
    _mining_space_search_terms,
    _mining_term_signatures,
    _shared_mining_signatures,
    _unique_preserve_order,
    add_community_mining_location,
    apply_community_mining_locations,
    get_cz_dashboard_timers,
)
from src.cache import SQLiteCache
from src.config import Settings
from src.sources.registry import SourceRegistry, build_default_registry
from src.timers import (
    calculate_countdown_end_unix,
    calculate_cycle_start_from_phase,
    calculate_exec_hangar_status,
    fetch_exec_cycle_start_unix,
)
from src.web_auth import (
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    build_discord_authorize_url,
    current_user_from_request,
    discord_auth_configured,
    encode_session,
    exchange_discord_code,
    fetch_web_user,
    oauth_state,
    session_secret,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
COMMANDS_PATH = ROOT_DIR / "docs" / "commands.md"
SHIP_LOANERS = {
    "600i explorer": ["Cyclone"],
    "600i executive": ["Cyclone"],
    "890 jump": ["85x"],
    "arrastra": ["Anvil Arrow", "Argo MOLE", "MISC Prospector"],
    "rsi arrastra": ["Anvil Arrow", "Argo MOLE", "MISC Prospector"],
    "carrack": ["C8 Pisces", "URSA Rover"],
    "carrack expedition": ["C8 Pisces", "URSA Rover"],
    "carrack w c8x": ["C8X Pisces Expedition", "URSA Rover"],
    "carrack expedition w c8x": ["C8X Pisces Expedition", "URSA Rover"],
    "centurion": ["Aurora MR"],
    "constellation andromeda": ["P-52 Merlin"],
    "constellation aquila": ["P-52 Merlin", "URSA Rover"],
    "constellation phoenix": ["P-72 Archimedes", "Lynx Rover"],
    "constellation phoenix emerald": ["P-72 Archimedes", "Lynx Rover"],
    "crucible": ["Constellation Andromeda"],
    "csv sm": ["Aurora MR"],
    "cyclone": ["Aurora MR"],
    "cyclone aa": ["Aurora MR"],
    "cyclone mt": ["Aurora MR"],
    "cyclone rc": ["Aurora MR"],
    "cyclone rn": ["Aurora MR"],
    "cyclone tr": ["Aurora MR"],
    "dragonfly": ["Aurora MR"],
    "e1 spirit": ["A1 Spirit"],
    "endeavor": ["Starfarer", "Cutlass Red"],
    "expanse": ["Prospector", "Reliant Kore"],
    "fury": ["Aurora MR"],
    "fury lx": ["Aurora MR"],
    "fury mx": ["Aurora MR"],
    "g12": ["Lynx"],
    "g12 a": ["Lynx"],
    "g12 r": ["Lynx"],
    "galaxy": ["Anvil Carrack"],
    "rsi galaxy": ["Anvil Carrack"],
    "genesis starliner": ["Hercules C2"],
    "hull d": ["Hull C", "Hercules C2"],
    "hull e": ["Hull C", "Hercules C2"],
    "idris m": ["F7C-M Super Hornet", "MPUV Passenger"],
    "idris p": ["F7C-M Super Hornet", "MPUV Passenger"],
    "javelin": ["Idris-P", "MPUV Cargo"],
    "kraken": ["Polaris", "Ironclad Assault", "Buccaneer"],
    "kraken privateer": ["Polaris", "Ironclad", "Buccaneer"],
    "liberator": ["Ironclad Assault", "F7C-M Super Hornet"],
    "legionnaire": ["Vanguard Hoplite"],
    "lynx": ["Aurora MR"],
    "mantis": ["Aurora LN"],
    "merchantman": ["Hull C", "Defender", "Hercules C2"],
    "banu merchantman": ["Hull C", "Defender", "Hercules C2"],
    "mole": ["Prospector"],
    "mpuv tractor": ["Aurora MR"],
    "mxc": ["Aurora MR"],
    "mule": ["Aurora MR"],
    "nautilus": ["Polaris", "Avenger Titan"],
    "nova": ["Aurora MR"],
    "nox": ["Aurora MR"],
    "odin": ["Idris-P"],
    "odyssey": ["Carrack", "Reliant Kore"],
    "orion": ["Prospector", "Mole"],
    "pioneer": ["Caterpillar", "Nomad"],
    "pitbull": ["Aurora MR"],
    "pulse": ["Aurora MR"],
    "pulse lx": ["Aurora MR"],
    "railen": ["Hercules C2", "Syulen"],
    "ranger cv": ["Cyclone"],
    "ranger rc": ["Cyclone RC"],
    "ranger tr": ["Cyclone TR"],
    "redeemer": ["Arrow"],
    "srv": ["Aurora LN"],
    "storm": ["Aurora MR"],
    "storm aa": ["Aurora MR"],
    "storm variants": ["Aurora MR"],
    "stv": ["Aurora MR"],
    "utv": ["Aurora MR"],
    "vulcan": ["Starfarer"],
    "x1": ["Aurora MR"],
    "x1 force": ["Aurora MR"],
    "x1 velocity": ["Aurora MR"],
    "zeus mk ii mr": ["Zeus Mk II ES"],
}
SHIP_DISPLAY_PREFIXES = (
    "Aegis ",
    "Anvil ",
    "Aopoa ",
    "Argo ",
    "Banu ",
    "Consolidated Outland ",
    "Crusader ",
    "Drake ",
    "Esperia ",
    "Gatac ",
    "Greycat ",
    "Kruger ",
    "MISC ",
    "Mirai ",
    "Origin ",
    "RSI ",
    "Tumbril ",
)


class AppState:
    settings: Settings
    cache: SQLiteCache
    sources: SourceRegistry


class MiningCommunityRequest(BaseModel):
    material: str = Field(min_length=1)
    system: str = Field(min_length=1)
    location_type: str = Field(min_length=1)
    location: str = Field(min_length=1)
    reported_by: str = "Website"


class ExecOverrideRequest(BaseModel):
    phase: str
    remaining_minutes: int = Field(gt=0)
    corrected_by: str = "Website"


class CZTimerRequest(BaseModel):
    timer: str
    started_minutes_ago: int = Field(default=0, ge=0)


class BlueprintOwnershipRequest(BaseModel):
    name: str = Field(min_length=1)
    category: str | None = None
    source_name: str | None = None
    source_url: str | None = None


class BlueprintTextImportRequest(BaseModel):
    text: str = Field(min_length=1)


class ShipOwnershipRequest(BaseModel):
    name: str = Field(min_length=1)
    ownership_type: str
    manufacturer: str | None = None
    role: str | None = None
    vehicle_type: str | None = None
    size: str | None = None
    status: str | None = None
    cargo_capacity: float | None = None
    source_name: str | None = None
    source_url: str | None = None
    image_url: str | None = None
    notes: str | None = None
    quantity: int | None = Field(default=None, ge=1, le=999)
    increment: bool = False


class RsiPledgeImportRequest(BaseModel):
    pages: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)


class InventoryItemRequest(BaseModel):
    name: str = Field(min_length=1)
    category: str | None = None
    location: str = Field(min_length=1)
    quantity: float = Field(default=1, ge=0)
    quality: float | None = Field(default=None, ge=0)
    item_type: str | None = None
    item_size: str | None = None
    volume_scu: float | None = Field(default=None, ge=0)
    notes: str | None = None


class InventoryTransferRequest(BaseModel):
    location: str = Field(min_length=1)


class InventoryClearRequest(BaseModel):
    location: str | None = None


class InventoryTextImportRequest(BaseModel):
    text: str = Field(min_length=1)
    default_location: str | None = None
    default_category: str | None = None
    scanner_mode: bool = False
    min_score: float = Field(default=0.72, ge=0, le=1)
    exclude_words: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env(require_discord_token=False)
    cache = await SQLiteCache.create(settings.database_path)
    sources = await build_default_registry(settings, cache)
    app.state.game_assist = AppState()
    app.state.game_assist.settings = settings
    app.state.game_assist.cache = cache
    app.state.game_assist.sources = sources
    try:
        yield
    finally:
        await sources.close()
        await cache.close()


app = FastAPI(
    title="Game Assist Web",
    description="Website companion API for the Star Citizen Discord bot.",
    version="0.1.0",
    lifespan=lifespan,
)
_RAPID_OCR = None


def state() -> AppState:
    return app.state.game_assist


def require_change_admin(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> None:
    user = current_user_from_request(request, state().settings)
    if user and user.can_manage_changes:
        return
    require_legacy_admin_token(x_admin_token)


def require_bot_admin(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> None:
    user = current_user_from_request(request, state().settings)
    if user and user.can_manage_admin:
        return
    require_legacy_admin_token(x_admin_token)


def require_legacy_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    token = state().settings.web_admin_token
    if not token:
        raise HTTPException(status_code=401, detail="Discord login with the required permissions is needed.")
    if x_admin_token != token:
        raise HTTPException(status_code=401, detail="Discord login with the required permissions is needed.")


def require_user(request: Request):
    user = current_user_from_request(request, state().settings)
    if user is None:
        raise HTTPException(status_code=401, detail="Discord login is required.")
    return user


def encode(value: Any) -> Any:
    if is_dataclass(value):
        return encode(asdict(value))
    if isinstance(value, list):
        return [encode(item) for item in value]
    if isinstance(value, dict):
        return {str(key): encode(item) for key, item in value.items()}
    return value


def not_found(message: str) -> None:
    raise HTTPException(status_code=404, detail=message)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    settings = state().settings
    return {
        "status": "online",
        "database_path": settings.database_path,
        "discord_auth_enabled": discord_auth_configured(settings),
        "legacy_admin_token_enabled": bool(settings.web_admin_token),
        "configured_channels": {
            "commands": settings.commands_channel_id,
            "exec_status": settings.exec_status_channel_id,
            "cz_timers": settings.cz_timers_channel_id,
            "audit_log": settings.audit_log_channel_id,
        },
        "command_channel_ids": settings.command_channel_ids,
    }


@app.get("/api/me")
async def me(request: Request) -> dict[str, Any]:
    user = current_user_from_request(request, state().settings)
    if user is None:
        return {
            "authenticated": False,
            "discord_auth_enabled": discord_auth_configured(state().settings),
        }
    return {
        "authenticated": True,
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "roles": user.roles,
        "guild_permissions": user.guild_permissions,
        "can_manage_changes": user.can_manage_changes,
        "can_manage_admin": user.can_manage_admin,
    }


@app.get("/auth/discord/login")
async def discord_login() -> RedirectResponse:
    settings = state().settings
    if not discord_auth_configured(settings):
        raise HTTPException(status_code=503, detail="Discord OAuth is not configured.")
    state_token = oauth_state()
    response = RedirectResponse(build_discord_authorize_url(settings, state_token))
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        state_token,
        httponly=True,
        samesite="lax",
        max_age=300,
    )
    return response


@app.get("/auth/discord/callback")
async def discord_callback(
    request: Request,
    code: str,
    oauth_state_value: str = Query(alias="state"),
) -> RedirectResponse:
    settings = state().settings
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    if not expected_state or expected_state != oauth_state_value:
        raise HTTPException(status_code=400, detail="Discord login state did not match.")
    token_payload = await exchange_discord_code(settings, code)
    user = await fetch_web_user(settings, str(token_payload.get("access_token")))
    secret = session_secret(settings)
    if not secret:
        raise HTTPException(status_code=503, detail="WEB_SESSION_SECRET or DISCORD_CLIENT_SECRET is required.")
    response = RedirectResponse("/")
    response.set_cookie(
        SESSION_COOKIE_NAME,
        encode_session(user, secret),
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
    )
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME)
    return response


@app.post("/auth/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.get("/api/commands")
async def commands() -> dict[str, str]:
    return {"markdown": COMMANDS_PATH.read_text(encoding="utf-8")}


@app.get("/api/lookup")
async def lookup(query: str) -> dict[str, Any]:
    result = await state().sources.lookup(query)
    if result is None:
        not_found(f"No result found for {query}.")
    return encode(result)


@app.get("/api/autocomplete/ships")
async def autocomplete_ships(query: str = "") -> list[str]:
    return await state().sources.autocomplete_ships(query)


@app.get("/api/ships/facets")
async def ship_facets() -> dict[str, list[str]]:
    return await state().sources.ship_facets()


@app.get("/api/ships")
async def ships(
    query: str | None = None,
    manufacturer: str | None = None,
    vehicle_type: str | None = None,
    size: str | None = None,
    role: str | None = None,
    status: str | None = None,
    sort_by: str = "name",
    min_cargo: float | None = Query(default=None, ge=0),
    max_cargo: float | None = Query(default=None, ge=0),
    limit: int = Query(default=24, ge=1, le=100),
    page: int = Query(default=1, ge=1),
) -> list[dict[str, Any]]:
    if min_cargo is not None and max_cargo is not None and min_cargo > max_cargo:
        raise HTTPException(status_code=422, detail="Minimum cargo cannot be greater than maximum cargo.")
    results = await state().sources.search_ships(
            query,
            manufacturer,
            vehicle_type,
            size,
            role,
            status,
            min_cargo,
            max_cargo,
            1000,
            1,
        )
    if sort_by == "cargo":
        results = sorted(results, key=lambda ship: float(ship.cargo_capacity or 0), reverse=True)
    elif sort_by == "manufacturer":
        results = sorted(results, key=lambda ship: ((ship.manufacturer or "").lower(), ship.name.lower()))
    elif sort_by == "size":
        results = sorted(results, key=lambda ship: ((ship.size or "").lower(), ship.name.lower()))
    else:
        results = sorted(results, key=lambda ship: ship.name.lower())
    start = max(0, (page - 1) * limit)
    return encode(results[start : start + limit])


@app.get("/api/ships/{name}")
async def ship(name: str) -> dict[str, Any]:
    result = await state().sources.lookup_ship(name)
    if result is None:
        not_found(f"No ship or vehicle found for {name}.")
    return encode(result)


@app.get("/api/me/ships")
async def my_ships(user=Depends(require_user)) -> list[dict[str, Any]]:
    ships = await state().cache.user_ships(user.id)
    repaired = False
    for ship in ships:
        display_name = _ship_display_name(str(ship.get("name") or ""))
        display_loaner_for = _ship_display_name(str(ship.get("loaner_for") or "")) if ship.get("loaner_for") else None
        cleaned_notes = _clean_redundant_loaner_note(
            ship.get("notes"),
            display_loaner_for,
        ) if ship.get("ownership_type") == "loaner" else ship.get("notes")
        if display_name and (
            display_name != ship.get("name")
            or display_loaner_for != ship.get("loaner_for")
            or cleaned_notes != ship.get("notes")
        ):
            await state().cache.save_user_ship(
                user.id,
                display_name,
                str(ship.get("ownership_type") or "in_game"),
                ship.get("manufacturer"),
                ship.get("role"),
                ship.get("source_name"),
                ship.get("source_url"),
                ship.get("image_url"),
                cleaned_notes,
                display_loaner_for,
            )
            if display_name != ship.get("name"):
                await state().cache.delete_user_ship(user.id, str(ship.get("name")))
            ship["name"] = display_name
            ship["loaner_for"] = display_loaner_for
            ship["notes"] = cleaned_notes
            repaired = True
        if not _ship_image_needs_refresh(ship.get("image_url")) and ship.get("manufacturer") and _has_ship_basic_info(ship.get("role")):
            if ship.get("ownership_type") == "pledged":
                repaired = await _sync_auto_loaners(user.id, str(ship.get("name") or ""), "pledged") or repaired
            continue
        detail = await state().sources.lookup_ship(str(ship.get("name") or ""))
        if ship.get("ownership_type") == "pledged":
            repaired = await _sync_auto_loaners(
                user.id,
                str(ship.get("name") or ""),
                "pledged",
                detail.status if detail else None,
            ) or repaired
        if detail is None:
            continue
        await state().cache.save_user_ship(
            user.id,
            _ship_display_name(detail.name),
            str(ship.get("ownership_type") or "in_game"),
            detail.manufacturer or ship.get("manufacturer"),
            _ship_basic_info(detail) or ship.get("role"),
            detail.source_name or ship.get("source_name"),
            detail.source_url or ship.get("source_url"),
            detail.image_url,
            ship.get("notes"),
            _ship_display_name(str(ship.get("loaner_for") or "")) if ship.get("loaner_for") else None,
        )
        repaired = True
    return await state().cache.user_ships(user.id) if repaired else ships


def _ship_image_needs_refresh(image_url: object) -> bool:
    value = str(image_url or "").strip().lower()
    return not value or "/thumb/" in value or "store_small" in value


@app.put("/api/me/ships")
async def save_my_ship(request: ShipOwnershipRequest, user=Depends(require_user)) -> dict[str, str]:
    ownership_type = request.ownership_type.strip().lower()
    if ownership_type not in {"pledged", "loaner", "in_game"}:
        raise HTTPException(status_code=422, detail="Ship ownership type must be pledged, loaner, or in_game.")
    ship_name = request.name.strip()
    display_name = _ship_display_name(ship_name)
    quantity = request.quantity
    if request.increment:
        existing = next(
            (ship for ship in await state().cache.user_ships(user.id) if _normalize_text(ship.get("name")) == _normalize_text(display_name)),
            None,
        )
        quantity = int(existing.get("quantity") or 1) + 1 if existing else 1
    await state().cache.save_user_ship(
        user.id,
        display_name,
        ownership_type,
        request.manufacturer.strip() if request.manufacturer else None,
        _ship_basic_info_from_values(
            request.role,
            request.vehicle_type,
            request.size,
            request.status,
            request.cargo_capacity,
        ),
        request.source_name.strip() if request.source_name else None,
        str(request.source_url).strip() if request.source_url else None,
        str(request.image_url).strip() if request.image_url else None,
        request.notes.strip() if request.notes else None,
        None,
        quantity,
    )
    await _sync_auto_loaners(user.id, display_name, ownership_type, request.status)
    return {"status": "saved"}


@app.post("/api/me/ships/import/rsi")
async def import_rsi_pledges(request: RsiPledgeImportRequest, user=Depends(require_user)) -> dict[str, Any]:
    imported: list[str] = []
    skipped: list[str] = []
    candidates: set[str] = {
        cleaned
        for value in request.candidates[:500]
        if (cleaned := _clean_rsi_pledge_ship_name(value))
    }
    for page in request.pages:
        candidates.update(_extract_rsi_pledge_ship_names(page))
    if not candidates:
        raise HTTPException(status_code=400, detail="No ship or vehicle candidates were supplied.")
    for candidate in sorted(candidates, key=str.lower):
        detail = await _resolve_imported_ship(candidate)
        if detail is None:
            skipped.append(candidate)
            continue
        display_name = _ship_display_name(detail.name)
        await state().cache.save_user_ship(
            user.id,
            display_name,
            "pledged",
            detail.manufacturer,
            _ship_basic_info(detail),
            detail.source_name,
            detail.source_url,
            detail.image_url,
            None,
            None,
        )
        await _sync_auto_loaners(user.id, display_name, "pledged", detail.status)
        imported.append(display_name)
    return {
        "status": "imported",
        "candidates": sorted(candidates, key=str.lower),
        "imported": sorted(set(imported), key=str.lower),
        "skipped": sorted(set(skipped), key=str.lower),
    }


async def _resolve_imported_ship(candidate: str) -> Any:
    for name in _rsi_import_lookup_candidates(candidate):
        detail = await state().sources.lookup_ship(name)
        if detail is not None:
            return detail
    for name in _rsi_import_lookup_candidates(candidate):
        results = await state().sources.search_ships(query=name, limit=5)
        if results:
            normalized = _normalize_text(name)
            exact = next(
                (
                    ship
                    for ship in results
                    if _normalize_text(ship.name) == normalized
                    or _normalize_text(_ship_display_name(ship.name)) == normalized
                ),
                None,
            )
            return exact or results[0]
    return None


@app.delete("/api/me/ships/{ship_name}")
async def delete_my_ship(ship_name: str, user=Depends(require_user)) -> dict[str, str]:
    await state().cache.delete_user_ship(user.id, ship_name)
    await state().cache.delete_user_loaners_for_ship(user.id, ship_name)
    return {"status": "removed"}


async def _sync_auto_loaners(
    user_id: int,
    ship_name: str,
    ownership_type: str,
    status_hint: str | None = None,
) -> bool:
    loaner_names = SHIP_LOANERS.get(_normalize_text(ship_name), [])
    if not loaner_names:
        return False
    if ownership_type != "pledged":
        await state().cache.delete_user_loaners_for_ship(user_id, ship_name)
        return True
    detail = None
    if not _ship_is_in_concept(status_hint):
        detail = await state().sources.lookup_ship(ship_name)
        if not _ship_is_in_concept(detail.status if detail else None):
            await state().cache.delete_user_loaners_for_ship(user_id, ship_name)
            return True
    existing_ships = await state().cache.user_ships(user_id)
    existing_by_name = {
        _normalize_text(existing.get("name")): existing
        for existing in existing_ships
    }
    changed = False
    for loaner_name in loaner_names:
        loaner_display_name = _ship_display_name(loaner_name)
        existing = existing_by_name.get(_normalize_text(loaner_name)) or existing_by_name.get(_normalize_text(loaner_display_name))
        if existing and existing.get("loaner_for") != ship_name:
            continue
        loaner = await state().sources.lookup_ship(loaner_name)
        await state().cache.save_user_ship(
            user_id,
            _ship_display_name(loaner.name if loaner else loaner_display_name),
            "loaner",
            loaner.manufacturer if loaner else None,
            _ship_basic_info(loaner) if loaner else None,
            loaner.source_name if loaner else "RSI Loaner Ship Matrix",
            loaner.source_url if loaner else "https://support.robertsspaceindustries.com/hc/en-us/articles/360003093114-Loaner-Ship-Matrix",
            loaner.image_url if loaner else None,
            None,
            ship_name,
        )
        changed = True
    return changed


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").lower().replace("-", " ").split())


def _clean_redundant_loaner_note(notes: object, loaner_for: str | None) -> str | None:
    value = str(notes or "").strip()
    if not value:
        return None
    if loaner_for and _normalize_text(value) == _normalize_text(f"Loaner for {loaner_for}"):
        return None
    return value


def _extract_rsi_pledge_ship_names(page_html: str) -> set[str]:
    candidates: set[str] = set()
    candidates.update(_extract_rsi_typed_item_ship_names(page_html))
    candidates.update(_extract_rsi_pledge_ship_names_from_links(page_html))
    candidates.update(_extract_rsi_pledge_ship_names_from_json(page_html))
    text = html.unescape(re.sub(r"<[^>]+>", "\n", page_html))
    text = re.sub(r"\s+", " ", text)
    candidates.update(_extract_rsi_pledge_ship_names_from_blocks(text))
    patterns = [
        r"(?:Contains|Also Contains)\s*:?\s+([^$<>]{2,120}?)(?=\s+(?:Also Contains|Standalone Ship|Package|Serial|Insurance|Starting Money|Hangar|Downloadable|Contains|$))",
        r"(?:Standalone Ship|Game Package|Package)\s*[-:]\s*([^$<>]{2,100}?)(?=\s+(?:Attributed|Created|Serial|Insurance|Contains|$))",
        r"Ship\s*[:\-]\s*([^$<>]{2,100}?)(?=\s+(?:Serial|Insurance|Contains|$))",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            for name in re.split(r"\s+(?:and|&|\+)\s+", match.group(1)):
                cleaned = _clean_rsi_pledge_ship_name(name)
                if cleaned:
                    candidates.add(cleaned)
    return candidates


def _extract_rsi_typed_item_ship_names(page_html: str) -> set[str]:
    candidates: set[str] = set()
    item_starts = [
        match.start()
        for match in re.finditer(r'''<[^>]+class=["'][^"']*\bitem\b[^"']*["'][^>]*>''', page_html, flags=re.IGNORECASE)
    ]
    for index, start in enumerate(item_starts):
        end = min(item_starts[index + 1] if index + 1 < len(item_starts) else len(page_html), start + 2400)
        block = page_html[start:end]
        kind_match = re.search(r'''class=["'][^"']*\bkind\b[^"']*["'][^>]*>([\s\S]{0,240}?)</[^>]+>''', block, flags=re.IGNORECASE)
        title_match = re.search(r'''class=["'][^"']*\btitle\b[^"']*["'][^>]*>([\s\S]{0,240}?)</[^>]+>''', block, flags=re.IGNORECASE)
        if not kind_match or not title_match:
            continue
        kind_text = html.unescape(re.sub(r"<[^>]+>", " ", kind_match.group(1)))
        if not re.search(r"\b(?:ship|vehicle)\b", kind_text, flags=re.IGNORECASE):
            continue
        title_text = html.unescape(re.sub(r"<[^>]+>", " ", title_match.group(1)))
        cleaned = _clean_rsi_pledge_ship_name(title_text)
        if cleaned:
            candidates.add(cleaned)
    return candidates


def _extract_rsi_pledge_ship_names_from_links(page_html: str) -> set[str]:
    candidates: set[str] = set()
    for match in re.finditer(r"/pledge/ships/[^\"'<> ]+/([^\"'<>?#]+)", page_html, flags=re.IGNORECASE):
        slug = html.unescape(match.group(1))
        cleaned = _clean_rsi_pledge_ship_name(slug.replace("-", " "))
        if cleaned:
            candidates.add(cleaned)
    return candidates


def _extract_rsi_pledge_ship_names_from_blocks(text: str) -> set[str]:
    candidates: set[str] = set()
    block_pattern = (
        r"(?P<kind>Standalone Ship|Game Package|Package)\s+"
        r"(?P<body>.{0,900}?)(?=\s+(?:Standalone Ship|Game Package|Package|Upgrade|Add-Ons|Paints|$))"
    )
    for block in re.finditer(block_pattern, text, flags=re.IGNORECASE):
        body = block.group("body")
        for pattern in (
            r"(?:Contains|Also Contains)\s*:?\s+([^$<>]{2,140}?)(?=\s+(?:Also Contains|Attributed|Created|Serial|Insurance|Starting Money|Hangar|Downloadable|Contains|$))",
            r"^\s*[-:]?\s*([^$<>]{2,120}?)(?=\s+(?:Attributed|Created|Serial|Insurance|Contains|$))",
        ):
            for match in re.finditer(pattern, body, flags=re.IGNORECASE):
                cleaned = _clean_rsi_pledge_ship_name(match.group(1))
                if cleaned:
                    candidates.add(cleaned)
    return candidates


def _extract_rsi_pledge_ship_names_from_json(page_html: str) -> set[str]:
    candidates: set[str] = set()
    for key in ("name", "title", "label"):
        pattern = rf'"{key}"\s*:\s*"([^"]{{2,120}})"'
        for match in re.finditer(pattern, page_html, flags=re.IGNORECASE):
            raw_value = match.group(1).encode("utf-8").decode("unicode_escape", errors="ignore")
            # RSI pages contain JSON labels for paints, equipment, flair, currencies,
            # navigation, and recommendations. Only pledge titles that explicitly
            # identify a ship or ship-bearing package belong in the hangar import.
            if not re.match(r"^\s*(?:Standalone Ship|Game Package|Package)\s*(?:[-:]|\s)", raw_value, flags=re.IGNORECASE):
                continue
            cleaned = _clean_rsi_pledge_ship_name(raw_value)
            if cleaned:
                candidates.add(cleaned)
    return candidates


def _clean_rsi_pledge_ship_name(name: str) -> str | None:
    value = " ".join(name.split())
    value = re.sub(r"^(?:Standalone Ship|Package|Upgrade|Ship)\s*[-:]\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(?:with Lifetime Insurance|with Lifetime|Lifetime Insurance|Best In Show|BIS|ILW|IAE|Warbond|Edition|Paint|Poster|Model|Serial|LTI)\b.*$", "", value, flags=re.IGNORECASE).strip(" -:,.")
    if not value or len(value) < 2:
        return None
    if len(value) > 72 or len(value.split()) > 10:
        return None
    blocked_words = {"insurance", "hangar", "poster", "paint", "skin", "flair", "manual", "downloadable"}
    blocked_terms = {
        "add on",
        "add-on",
        "attributed",
        "canadian dollar",
        "created",
        "download",
        "downloadable",
        "english",
        "figurine",
        "flair",
        "gift card",
        "gold livery",
        "hangar",
        "name reservation",
        "paint",
        "plushie",
        "poster",
        "pound sterling",
        "referral reward",
        "self land",
        "skin",
        "store",
        "subscriber",
        "support",
        "upgrade",
        "united states dollar",
    }
    normalized = _normalize_text(value)
    if re.search(r"\bto\b.*\b(?:year|insurance)\b|\b\d+\s*year\b", normalized):
        return None
    if normalized in blocked_words or any(term in normalized for term in blocked_terms):
        return None
    return value


def _rsi_import_lookup_candidates(value: str) -> list[str]:
    cleaned = _clean_rsi_pledge_ship_name(value) or value
    candidates = [cleaned, _ship_display_name(cleaned)]
    normalized = _normalize_text(cleaned)
    package_markers = [
        "starter pack",
        "starter package",
        "game package",
        "pack",
        "package",
    ]
    simplified = cleaned
    for marker in package_markers:
        simplified = re.sub(rf"\b{re.escape(marker)}\b", "", simplified, flags=re.IGNORECASE)
    simplified = " ".join(simplified.split()).strip(" -:,.")
    if simplified:
        candidates.extend([simplified, _ship_display_name(simplified)])
    if " - " in cleaned:
        candidates.append(cleaned.split(" - ")[-1].strip())
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        key = _normalize_text(candidate)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _ship_is_in_concept(status: object) -> bool:
    return _normalize_text(status) == "in concept"


def _ship_basic_info(ship: Any) -> str | None:
    role = " / ".join(str(value) for value in [getattr(ship, "career", None), getattr(ship, "role", None)] if value)
    return _ship_basic_info_from_values(
        role,
        getattr(ship, "vehicle_type", None),
        getattr(ship, "size", None),
        getattr(ship, "status", None),
        getattr(ship, "cargo_capacity", None),
    )


def _ship_basic_info_from_values(
    role: object,
    vehicle_type: object,
    size: object,
    status: object,
    cargo_capacity: object,
) -> str | None:
    parts = [role, vehicle_type, size, status]
    if cargo_capacity is not None and cargo_capacity != "":
        parts.append(f"{cargo_capacity} SCU")
    return " | ".join(str(part) for part in parts if part) or None


def _has_ship_basic_info(value: object) -> bool:
    return " | " in str(value or "")


def _ship_display_name(name: str) -> str:
    value = " ".join(str(name or "").split())
    for prefix in SHIP_DISPLAY_PREFIXES:
        if value.startswith(prefix):
            return value.removeprefix(prefix).strip()
    return value


@app.get("/api/commodities/{name}")
async def commodity(
    name: str,
    system: str | None = None,
    purchase_system: str | None = None,
    sell_system: str | None = None,
) -> dict[str, Any]:
    result = await state().sources.lookup_commodity(name, system, purchase_system, sell_system)
    if result is None:
        not_found(f"No commodity found for {name}.")
    return encode(result)


@app.get("/api/autocomplete/commodities")
async def autocomplete_commodities(query: str = "") -> list[str]:
    return await state().sources.autocomplete_commodities(query)


@app.get("/api/mining/{material}")
async def mining(material: str, system: str | None = None, planet: str | None = None) -> dict[str, Any]:
    terms = _mining_multi_search_terms(material)
    result = None
    if len(terms) == 1 and not _has_mining_multi_separator(material):
        result = await state().sources.lookup_mining_material(material, system, planet)
        if result is None:
            terms = _mining_space_search_terms(material)

    if len(terms) > 1:
        return await multi_mining_signature_payload(material, terms)

    if result is None:
        result = await state().sources.lookup_mining_material(material, system, planet)
    if result is None:
        not_found(f"No mining material found for {material}.")
    return encode(await apply_community_mining_locations(state().cache, result))


async def multi_mining_signature_payload(query: str, terms: list[str]) -> dict[str, Any]:
    results = []
    missing = []
    for term in terms:
        result = await state().sources.lookup_mining_material(term)
        if result is None:
            missing.append(term)
            continue
        results.append(
            {
                "term": term,
                "material": result.material_name,
                "signatures": _mining_term_signatures(result, term),
            }
        )

    shared_signatures = _shared_mining_signatures([result["signatures"] for result in results])
    return {
        "result_type": "multi_mining_signatures",
        "material_name": "Mining Signature Match",
        "query": query,
        "materials": _unique_preserve_order([result["material"] for result in results]),
        "missing": missing,
        "rock_signatures": shared_signatures,
        "source_name": "Star-Head mining signatures",
    }


@app.post("/api/mining/community", dependencies=[Depends(require_change_admin)])
async def mining_community(request: MiningCommunityRequest) -> dict[str, str]:
    await add_community_mining_location(state().cache, request.model_dump())
    await state().cache.add_audit_event(
        "Website Mining Location Added",
        {
            "Material": request.material,
            "System": request.system,
            "Location Type": request.location_type,
            "Location": request.location,
            "Reported By": request.reported_by,
        },
    )
    return {"status": "saved"}


@app.get("/api/autocomplete/mining-materials")
async def autocomplete_mining_materials(query: str = "") -> list[str]:
    return await state().sources.autocomplete_mining_materials(query)


@app.get("/api/blueprints")
async def blueprints(
    query: str | None = None,
    category: str | None = None,
    material: str | None = None,
    mission_type: str | None = None,
    contractor: str | None = None,
    location: str | None = None,
    limit: int = Query(default=12, ge=1, le=50),
    page: int = Query(default=1, ge=1),
) -> list[dict[str, Any]]:
    return encode(
        await state().sources.lookup_blueprints(
            query,
            category,
            material,
            mission_type,
            contractor,
            location,
            limit,
            page,
        )
    )


@app.get("/api/autocomplete/blueprints")
async def autocomplete_blueprints(query: str = "") -> list[str]:
    return await state().sources.autocomplete_blueprints(query)


@app.post("/api/blueprints/import/text")
async def import_blueprints_from_text(request: BlueprintTextImportRequest) -> dict[str, Any]:
    return {
        "ocr_available": True,
        "ocr_text": request.text,
        "matches": encode(await _match_blueprints_from_text(request.text)),
    }


@app.post("/api/blueprints/import/images")
async def import_blueprints_from_images(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    ocr_text, ocr_error = await _ocr_blueprint_images(files)
    return {
        "ocr_available": ocr_error is None,
        "ocr_error": ocr_error,
        "ocr_text": ocr_text,
        "matches": encode(await _match_blueprints_from_text(ocr_text)) if ocr_text.strip() else [],
    }


@app.get("/api/me/blueprints")
async def my_blueprints(user=Depends(require_user)) -> list[dict[str, Any]]:
    return await state().cache.user_blueprints(user.id)


@app.put("/api/me/blueprints")
async def save_my_blueprint(request: BlueprintOwnershipRequest, user=Depends(require_user)) -> dict[str, str]:
    await state().cache.save_user_blueprint(
        user.id,
        request.name.strip(),
        request.category.strip() if request.category else None,
        request.source_name.strip() if request.source_name else None,
        str(request.source_url).strip() if request.source_url else None,
    )
    return {"status": "saved"}


@app.delete("/api/me/blueprints/{blueprint_name}")
async def delete_my_blueprint(blueprint_name: str, user=Depends(require_user)) -> dict[str, str]:
    await state().cache.delete_user_blueprint(user.id, blueprint_name)
    return {"status": "removed"}


@app.get("/api/me/inventory")
async def my_inventory(
    location: str | None = None,
    category: str | None = None,
    query: str | None = None,
    sort_by: str = "name",
    user=Depends(require_user),
) -> list[dict[str, Any]]:
    return await state().cache.user_inventory_items(
        user.id,
        location.strip() if location else None,
        category.strip() if category else None,
        query.strip() if query else None,
        sort_by,
    )


@app.get("/api/me/inventory/facets")
async def my_inventory_facets(user=Depends(require_user)) -> dict[str, list[str]]:
    return await state().cache.user_inventory_facets(user.id)


@app.post("/api/me/inventory/import/text")
async def import_inventory_from_text(
    request: InventoryTextImportRequest,
    user=Depends(require_user),
) -> dict[str, Any]:
    del user
    if request.scanner_mode:
        scanner_lookups = await _inventory_scanner_lookups(request.text, request.exclude_words)
        return {
            "ocr_available": True,
            "ocr_text": request.text,
            "items": await _match_inventory_scanner_text(
                request.text,
                request.default_location,
                request.default_category,
                request.min_score,
                request.exclude_words,
                scanner_lookups,
            ),
            "diagnostics": await _inventory_scanner_diagnostics(
                request.text,
                request.min_score,
                request.exclude_words,
                scanner_lookups,
            ),
        }
    return {
        "ocr_available": True,
        "ocr_text": request.text,
        "items": await _enrich_inventory_items(
            _inventory_items_from_text(
                request.text,
                request.default_location,
                request.default_category,
                first_match=request.scanner_mode,
            )
        ),
    }


@app.post("/api/me/inventory/import/images")
async def import_inventory_from_images(
    files: list[UploadFile] = File(...),
    default_location: str | None = None,
    default_category: str | None = None,
    scanner_mode: bool = False,
    live_scan: bool = False,
    min_score: float = Query(default=0.72, ge=0, le=1),
    exclude_words: str | None = None,
    user=Depends(require_user),
) -> dict[str, Any]:
    del user
    ocr_text, ocr_error = await _ocr_blueprint_images(files)
    if scanner_mode:
        scanner_lookups = await _inventory_scanner_lookups(
            ocr_text,
            exclude_words,
            candidate_limit=8 if live_scan else None,
        ) if ocr_text.strip() else {}
        return {
            "ocr_available": ocr_error is None,
            "ocr_error": ocr_error,
            "ocr_text": ocr_text,
            "items": await _match_inventory_scanner_text(
                ocr_text,
                default_location,
                default_category,
                min_score,
                exclude_words,
                scanner_lookups,
            ) if ocr_text.strip() else [],
            "diagnostics": None if live_scan else await _inventory_scanner_diagnostics(
                ocr_text,
                min_score,
                exclude_words,
                scanner_lookups,
            ) if ocr_text.strip() else {"candidates": [], "rejected_lines": []},
        }
    return {
        "ocr_available": ocr_error is None,
        "ocr_error": ocr_error,
        "ocr_text": ocr_text,
        "items": await _enrich_inventory_items(
            _inventory_items_from_text(
                ocr_text,
                default_location,
                default_category,
                first_match=scanner_mode,
            )
        ) if ocr_text.strip() else [],
    }


@app.post("/api/me/inventory")
async def add_my_inventory_item(request: InventoryItemRequest, user=Depends(require_user)) -> dict[str, Any]:
    await state().cache.merge_user_inventory_duplicates(user.id)
    item_id = await state().cache.save_user_inventory_item(
        user.id,
        request.name.strip(),
        request.category.strip() if request.category else None,
        request.location.strip(),
        request.quantity,
        request.quality,
        request.item_type.strip() if request.item_type else None,
        request.item_size.strip() if request.item_size else None,
        request.volume_scu,
        request.notes.strip() if request.notes else None,
    )
    return {"status": "saved", "id": item_id}


@app.post("/api/me/inventory/merge-duplicates")
async def merge_my_inventory_duplicates(user=Depends(require_user)) -> dict[str, Any]:
    removed = await state().cache.merge_user_inventory_duplicates(user.id)
    return {"status": "merged", "removed": removed}


@app.post("/api/me/inventory/clear")
async def clear_my_inventory(request: InventoryClearRequest, user=Depends(require_user)) -> dict[str, Any]:
    location = request.location.strip() if request.location else None
    removed = await state().cache.clear_user_inventory_items(user.id, location or None)
    return {"status": "cleared", "removed": removed, "location": location}


@app.get("/api/me/inventory/export")
async def export_my_inventory(
    location: str | None = None,
    category: str | None = None,
    query: str | None = None,
    sort_by: str = "location",
    user=Depends(require_user),
) -> Response:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    items = await state().cache.user_inventory_items(
        user.id,
        location.strip() if location else None,
        category.strip() if category else None,
        query.strip() if query else None,
        sort_by,
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Station Inventory"
    headers = ["Location", "Category", "Item Type", "Size", "Name", "Quantity", "Quality", "Volume SCU", "Notes", "Updated At"]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for item in items:
        sheet.append(
            [
                item["location"],
                item["category"] or "",
                item["item_type"] or "",
                item["item_size"] or "",
                item["name"],
                item["quantity"],
                item["quality"] if item["quality"] is not None else "",
                item["volume_scu"] if item["volume_scu"] is not None else "",
                item["notes"] or "",
                item["updated_at"],
            ]
        )
    for column in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column)
        sheet.column_dimensions[column[0].column_letter].width = min(max(max_length + 2, 12), 48)
    output = BytesIO()
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="station-inventory.xlsx"'},
    )


@app.put("/api/me/inventory/{item_id}")
async def update_my_inventory_item(
    item_id: int,
    request: InventoryItemRequest,
    user=Depends(require_user),
) -> dict[str, str]:
    updated = await state().cache.update_user_inventory_item(
        user.id,
        item_id,
        request.name.strip(),
        request.category.strip() if request.category else None,
        request.location.strip(),
        request.quantity,
        request.quality,
        request.item_type.strip() if request.item_type else None,
        request.item_size.strip() if request.item_size else None,
        request.volume_scu,
        request.notes.strip() if request.notes else None,
    )
    if not updated:
        not_found("Inventory item not found.")
    return {"status": "updated"}


@app.post("/api/me/inventory/{item_id}/transfer")
async def transfer_my_inventory_item(
    item_id: int,
    request: InventoryTransferRequest,
    user=Depends(require_user),
) -> dict[str, str]:
    updated = await state().cache.transfer_user_inventory_item(user.id, item_id, request.location.strip())
    if not updated:
        not_found("Inventory item not found.")
    return {"status": "transferred"}


@app.delete("/api/me/inventory/{item_id}")
async def delete_my_inventory_item(item_id: int, user=Depends(require_user)) -> dict[str, str]:
    deleted = await state().cache.delete_user_inventory_item(user.id, item_id)
    if not deleted:
        not_found("Inventory item not found.")
    return {"status": "removed"}


async def _ocr_blueprint_images(files: list[UploadFile]) -> tuple[str, str | None]:
    try:
        from PIL import Image
    except Exception:
        return "", "Image OCR needs Pillow installed on the server."

    texts: list[str] = []
    for file in files[:8]:
        data = await file.read()
        if not data:
            continue
        try:
            Image.open(BytesIO(data)).verify()
            texts.append(_read_image_text(data))
        except Exception as exc:
            return "\n".join(texts), f"Could not read {file.filename or 'image'}: {exc}"
    return "\n".join(texts), None


def _read_image_text(image_data: bytes) -> str:
    rapid_text, rapid_error = _read_image_text_with_rapidocr(image_data)
    if rapid_text.strip() or rapid_error is None:
        return rapid_text

    tesseract_text, tesseract_error = _read_image_text_with_tesseract(image_data)
    if tesseract_text.strip() or tesseract_error is None:
        return tesseract_text
    raise RuntimeError(f"Bundled OCR failed: {rapid_error}. Optional Tesseract fallback failed: {tesseract_error}")


def _read_image_text_with_rapidocr(image_data: bytes) -> tuple[str, str | None]:
    global _RAPID_OCR
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as exc:
        return "", str(exc)

    try:
        if _RAPID_OCR is None:
            _RAPID_OCR = RapidOCR()
        result, _ = _RAPID_OCR(image_data)
        lines = [str(item[1]).strip() for item in result or [] if len(item) > 1 and str(item[1]).strip()]
        return "\n".join(lines), None
    except Exception as exc:
        return "", str(exc)


def _read_image_text_with_tesseract(image_data: bytes) -> tuple[str, str | None]:
    try:
        from PIL import Image
        import pytesseract
    except Exception as exc:
        return "", str(exc)

    try:
        image = Image.open(BytesIO(image_data))
        return pytesseract.image_to_string(image), None
    except Exception as exc:
        return "", str(exc)


async def _match_blueprints_from_text(text: str) -> list[dict[str, Any]]:
    matches: dict[str, dict[str, Any]] = {}
    for candidate in _blueprint_text_candidates(text):
        results = await state().sources.lookup_blueprints(query=candidate, limit=5)
        for result in results:
            confidence = _blueprint_match_confidence(candidate, result.name)
            if confidence < 0.58:
                continue
            existing = matches.get(result.name)
            if existing and existing["confidence"] >= confidence:
                continue
            matches[result.name] = {
                "name": result.name,
                "category": result.category,
                "source_name": result.source_name,
                "source_url": result.source_url,
                "component_size": result.component_size,
                "confidence": round(confidence, 2),
                "matched_text": candidate,
            }
    return sorted(matches.values(), key=lambda item: (-item["confidence"], item["name"].lower()))


def _blueprint_text_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw_line in re.split(r"[\r\n]+", text):
        line = _clean_blueprint_ocr_line(raw_line)
        if not line:
            continue
        parts = [line]
        parts.extend(part.strip() for part in re.split(r"\s{2,}|[|•·]", line) if part.strip())
        for part in parts:
            if 3 <= len(part) <= 80 and _normalize_text(part) not in seen:
                seen.add(_normalize_text(part))
                candidates.append(part)
        if len(candidates) >= 120:
            break
    return candidates


def _inventory_items_from_text(
    text: str,
    default_location: str | None = None,
    default_category: str | None = None,
    first_match: bool = False,
) -> list[dict[str, Any]]:
    location = (default_location or "").strip() or "Unknown location"
    category = (default_category or "").strip() or None
    if first_match:
        tooltip_item = _inventory_item_from_tooltip_text(text, location, category)
        return [tooltip_item] if tooltip_item else []

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for raw_line in re.split(r"[\r\n]+", text):
        parsed = _inventory_item_from_ocr_line(raw_line, location, category)
        if parsed is None:
            continue
        key = (parsed["name"].casefold(), parsed["location"].casefold(), parsed["category"])
        if key in seen:
            continue
        seen.add(key)
        items.append(parsed)
        if first_match:
            break
        if len(items) >= 80:
            break
    return items


async def _enrich_inventory_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in items:
        enriched_item = item.copy()
        try:
            results = await state().sources.lookup_inventory_items(item["name"], limit=5)
        except Exception:
            results = []
        match = _best_inventory_item_lookup(item["name"], results)
        if match:
            enriched_item["name"] = match.name
            enriched_item["category"] = match.category or enriched_item.get("category")
            enriched_item["item_type"] = match.section or enriched_item.get("item_type")
            enriched_item["item_size"] = match.size or enriched_item.get("item_size")
            enriched_item["source_name"] = match.source_name
            enriched_item["source_url"] = match.source_url
        enriched.append(enriched_item)
    return enriched


async def _match_inventory_scanner_text(
    text: str,
    default_location: str | None,
    default_category: str | None,
    min_score: float,
    exclude_words: str | None,
    scanner_lookups: dict[str, list[tuple[Any, float]]] | None = None,
) -> list[dict[str, Any]]:
    location = (default_location or "").strip() or "Unknown location"
    category = (default_category or "").strip() or None
    matches: dict[str, dict[str, Any]] = {}
    exclude = {_normalize_text(word) for word in re.split(r"[,;\n]+", exclude_words or "") if word.strip()}

    for candidate in _inventory_scanner_text_candidates(text, exclude):
        for result, confidence in _inventory_scanner_accepted_matches(
            scanner_lookups.get(candidate, []) if scanner_lookups is not None else await _inventory_lookup_scored_matches(candidate, 5),
            min_score,
        ):
            existing = matches.get(result.name)
            if existing and existing["confidence"] >= confidence:
                continue
            item = _inventory_item_from_tooltip_text(text, location, category, result.name) or _inventory_item_from_ocr_line(
                result.name,
                location,
                category,
            )
            if item is None:
                continue
            if not _inventory_tooltip_match_agrees_with_result(item, result.name):
                continue
            item.update(
                {
                    "name": result.name,
                    "category": result.category or item.get("category"),
                    "item_type": result.section or item.get("item_type"),
                    "item_size": result.size or item.get("item_size"),
                    "source_name": result.source_name,
                    "source_url": result.source_url,
                    "confidence": round(confidence, 2),
                    "matched_text": candidate,
                }
            )
            item["notes"] = _inventory_scanner_notes(item.get("notes"), confidence, candidate)
            matches[result.name] = item

    return sorted(matches.values(), key=lambda item: (-float(item["confidence"]), item["name"].lower()))[:5]


def _inventory_scanner_accepted_matches(scored_matches: list[tuple[Any, float]], min_score: float) -> list[tuple[Any, float]]:
    accepted = [(result, confidence) for result, confidence in scored_matches if confidence >= min_score]
    if not accepted:
        return []
    return [max(accepted, key=lambda item: (item[1], -len(item[0].name)))]


def _inventory_tooltip_match_agrees_with_result(item: dict[str, Any], result_name: str) -> bool:
    item_name = _normalize_text(str(item.get("name") or ""))
    result = _normalize_text(result_name)
    attachment_terms = {"compensator", "suppressor"}
    item_terms = {term for term in attachment_terms if term in item_name}
    result_terms = {term for term in attachment_terms if term in result}
    if item_terms and result_terms and item_terms.isdisjoint(result_terms):
        return False
    return True


async def _inventory_scanner_diagnostics(
    text: str,
    min_score: float,
    exclude_words: str | None,
    scanner_lookups: dict[str, list[tuple[Any, float]]] | None = None,
) -> dict[str, Any]:
    exclude = {_normalize_text(word) for word in re.split(r"[,;\n]+", exclude_words or "") if word.strip()}
    raw_lines = [_clean_inventory_ocr_line(line) for line in re.split(r"[\r\n]+", text)]
    raw_lines = [line for line in raw_lines if line]
    candidate_values = _inventory_scanner_text_candidates(text, exclude)
    candidates: list[dict[str, Any]] = []

    for candidate in candidate_values[:30]:
        try:
            results = scanner_lookups.get(candidate, []) if scanner_lookups is not None else await _inventory_lookup_scored_matches(candidate, 5)
        except Exception as exc:
            candidates.append(
                {
                    "text": candidate,
                    "status": "lookup_error",
                    "reason": str(exc),
                    "matches": [],
                }
            )
            continue

        scored_matches = []
        for result, score in results:
            scored_matches.append(
                {
                    "name": result.name,
                    "category": result.category,
                    "item_type": result.section,
                    "size": result.size,
                    "source_name": result.source_name,
                    "source_url": result.source_url,
                    "score": round(score, 2),
                    "accepted": score >= min_score,
                }
            )
        best_score = max((float(match["score"]) for match in scored_matches), default=0.0)
        candidates.append(
            {
                "text": candidate,
                "status": "accepted" if best_score >= min_score else "rejected",
                "reason": "catalog score passed" if best_score >= min_score else f"best score below {min_score:g}",
                "matches": sorted(scored_matches, key=lambda match: -float(match["score"])),
            }
        )

    candidate_norms = {_normalize_text(candidate) for candidate in candidate_values}
    rejected_lines = [
        {
            "text": line,
            "reason": "metadata/noise" if _inventory_scanner_line_is_metadata(line) else "not selected as candidate",
        }
        for line in raw_lines[:80]
        if _normalize_text(line) not in candidate_norms
    ]
    return {
        "min_score": min_score,
        "candidate_count": len(candidate_values),
        "candidates": candidates,
        "rejected_lines": rejected_lines[:40],
    }


async def _inventory_scanner_lookups(
    text: str,
    exclude_words: str | None,
    candidate_limit: int | None = None,
) -> dict[str, list[tuple[Any, float]]]:
    """Resolve each OCR candidate once for both matching and diagnostics.

    Catalog lookups are network-bound. A small concurrency limit keeps a scan
    inside reverse-proxy timeouts without flooding the upstream data source.
    """
    exclude = {_normalize_text(word) for word in re.split(r"[,;\n]+", exclude_words or "") if word.strip()}
    candidates = _inventory_scanner_text_candidates(text, exclude)
    if candidate_limit is not None:
        candidates = candidates[:max(1, candidate_limit)]
    semaphore = asyncio.Semaphore(4)

    async def lookup(candidate: str) -> tuple[str, list[tuple[Any, float]]]:
        async with semaphore:
            return candidate, await _inventory_lookup_scored_matches(candidate, 5)

    return dict(await asyncio.gather(*(lookup(candidate) for candidate in candidates)))


async def _inventory_lookup_scored_matches(candidate: str, limit: int = 5) -> list[tuple[Any, float]]:
    seen: set[str] = set()
    scored: list[tuple[Any, float]] = []
    for query in _inventory_lookup_queries(candidate):
        try:
            results = await state().sources.lookup_inventory_items(query, limit=limit)
        except Exception:
            results = []
        for result in results:
            key = _normalize_text(getattr(result, "name", ""))
            if not key or key in seen:
                continue
            seen.add(key)
            scored.append((result, _inventory_match_confidence(candidate, result.name)))
    return sorted(scored, key=lambda item: (-item[1], item[0].name.lower()))[:limit]


def _inventory_lookup_queries(candidate: str) -> list[str]:
    normalized = _normalize_inventory_tooltip_name(candidate)
    words = [word for word in re.split(r"\s+", normalized.strip()) if word]
    queries = [normalized]
    if len(words) >= 2:
        queries.append(" ".join(words[:2]))
        if len(words[0]) >= 5 or re.search(r"\d", words[0]):
            queries.append(words[0])
    if len(words) >= 3:
        queries.append(" ".join(words[:3]))
        queries.append(" ".join(words[-2:]))
    return _unique_preserve_order(query for query in queries if len(query) >= 3)


def _inventory_scanner_notes(notes: object, confidence: float, candidate: str) -> str:
    base = str(notes or "Imported from hover scanner")
    suffix = f"Match: {round(confidence * 100)}% from '{candidate}'"
    if suffix in base:
        return base
    return f"{base} ({suffix})"


def _inventory_scanner_text_candidates(text: str, exclude_words: set[str] | None = None) -> list[str]:
    exclude_words = exclude_words or set()
    candidates: list[str] = []
    seen: set[str] = set()
    lines = [_clean_inventory_ocr_line(line) for line in re.split(r"[\r\n]+", text)]
    lines = [line for line in lines if line]
    blocks = _inventory_tooltip_blocks(lines)

    for block in blocks:
        tooltip_name = _inventory_tooltip_name(block)
        if tooltip_name:
            _add_inventory_candidate(candidates, seen, tooltip_name, exclude_words)

    relevant_lines = [line for block in blocks for line in block]
    for line in relevant_lines:
        if _inventory_scanner_line_is_metadata(line):
            continue
        normalized_line = _normalize_inventory_tooltip_name(line)
        _add_inventory_candidate(candidates, seen, normalized_line, exclude_words)
        for part in re.split(r"\s{2,}|[|•·]", normalized_line):
            _add_inventory_candidate(candidates, seen, part, exclude_words)

    joined = " ".join(relevant_lines)
    for pattern in (
        r"\b[A-Z]{2,4}[- ]\d+\s+[A-Z][A-Za-z0-9'\"() -]{2,40}",
        r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z0-9'\"() -]+){1,5}\b",
    ):
        for match in re.finditer(pattern, joined):
            _add_inventory_candidate(candidates, seen, _normalize_inventory_tooltip_name(match.group(0)), exclude_words)
            if len(candidates) >= 30:
                return candidates
    return candidates[:30]


def _add_inventory_candidate(
    candidates: list[str],
    seen: set[str],
    value: str,
    exclude_words: set[str],
) -> None:
    candidate = " ".join(str(value or "").split()).strip(" -:,.")
    normalized = _normalize_text(candidate)
    if not normalized or normalized in seen:
        return
    if len(candidate) < 3 or len(candidate) > 80:
        return
    if any(word and word in normalized for word in exclude_words):
        return
    if _inventory_scanner_line_is_metadata(candidate):
        return
    if not any(char.isalpha() for char in candidate):
        return
    seen.add(normalized)
    candidates.append(candidate)


def _inventory_scanner_line_is_metadata(line: str) -> bool:
    normalized = _normalize_text(line)
    if not normalized:
        return True
    blocked_exact = {
        "inventory",
        "personal all",
        "personal backpack",
        "local local",
        "looting view",
        "move all",
        "clear filters",
        "empty",
    }
    if normalized in blocked_exact:
        return True
    blocked_prefixes = (
        "volume",
        "capacity",
        "manufacturer",
        "type",
        "item type",
        "class",
        "magazine size",
        "rate of fire",
        "fire rate",
        "effective range",
        "attachments",
        "attachment point",
        "underbarrel",
        "barrel",
        "optics",
        "magnification",
        "zoom",
        "aim time",
        "impact force",
        "recoil",
        "damage",
        "size",
        "quality",
    )
    if normalized.startswith(blocked_prefixes):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:scu|uscu|q|rpm|m)", normalized):
        return True
    words = normalized.split()
    if len(words) > 10:
        return True
    if len(words) >= 6 and sum(1 for word in words if word in {"the", "and", "to", "of", "for", "that", "with"}) >= 2:
        return True
    return False


def _inventory_match_confidence(candidate: str, item_name: str) -> float:
    if _inventory_scanner_line_is_metadata(candidate):
        return 0
    candidate_norm = _normalize_text(candidate)
    item_norm = _normalize_text(item_name)
    if not candidate_norm or not item_norm:
        return 0
    if candidate_norm == item_norm:
        return 1
    if item_norm in candidate_norm:
        return min(0.96, len(item_norm) / max(len(candidate_norm), 1) + 0.25)
    if candidate_norm in item_norm:
        return min(0.9, len(candidate_norm) / max(len(item_norm), 1) + 0.2)
    candidate_words = set(candidate_norm.split())
    item_words = set(item_norm.split())
    overlap = len(candidate_words & item_words)
    word_score = overlap / max(len(item_words), 1) if overlap else 0
    typo_score = difflib.SequenceMatcher(None, candidate_norm, item_norm).ratio()
    compact_typo_score = difflib.SequenceMatcher(
        None,
        candidate_norm.replace(" ", ""),
        item_norm.replace(" ", ""),
    ).ratio()
    score = max(word_score, typo_score * 0.95, compact_typo_score * 0.92)
    candidate_family = _inventory_name_family(candidate_norm)
    item_family = _inventory_name_family(item_norm)
    if candidate_family and item_family and candidate_family != item_family:
        family_similarity = difflib.SequenceMatcher(None, candidate_family, item_family).ratio()
        if family_similarity < 0.72:
            score = min(score, 0.65)
    candidate_numbers = set(re.findall(r"\d+", candidate_norm))
    item_numbers = set(re.findall(r"\d+", item_norm))
    if candidate_numbers and item_numbers and not (candidate_numbers & item_numbers):
        score = min(score, 0.65)
    return score


def _inventory_name_family(normalized_name: str) -> str | None:
    for word in normalized_name.split():
        if any(char.isalpha() for char in word) and len(word) >= 3:
            return word
    return None


def _best_inventory_item_lookup(name: str, results: list[Any]) -> Any | None:
    if not results:
        return None
    normalized = _normalize_text(name)
    for result in results:
        if _normalize_text(getattr(result, "name", "")) == normalized:
            return result
    for result in results:
        result_name = _normalize_text(getattr(result, "name", ""))
        if normalized in result_name or result_name in normalized:
            return result
    return results[0]


def _inventory_item_from_tooltip_text(
    text: str,
    default_location: str,
    default_category: str | None,
    matched_name: str | None = None,
) -> dict[str, Any] | None:
    lines = [_clean_inventory_ocr_line(line) for line in re.split(r"[\r\n]+", text)]
    lines = [line for line in lines if line]
    blocks = _inventory_tooltip_blocks(lines)
    lines = _inventory_tooltip_block_for_match(blocks, matched_name) if blocks else []
    if not lines:
        return None
    name = _inventory_tooltip_name(lines)
    if not name:
        return None
    category, item_type = _inventory_tooltip_category(lines, default_category)
    item_size = _inventory_tooltip_size(lines)
    if re.search(r"(?:^|\s)x?\s*\d+(?:\.\d+)?\s*$", lines[0], flags=re.IGNORECASE):
        stack_item = _inventory_item_from_ocr_line(lines[0], default_location, default_category)
        if stack_item:
            stack_item["notes"] = "Imported from hover scanner"
            stack_item["category"] = category or stack_item["category"]
            stack_item["item_type"] = item_type or stack_item["item_type"]
            stack_item["item_size"] = item_size
            return stack_item
    quality = _inventory_tooltip_quality(lines, name)
    volume_scu = _inventory_tooltip_volume_scu(lines)
    uses_scu = _inventory_tooltip_uses_scu(category, item_type, lines)
    if not uses_scu:
        volume_scu = None
        if not _inventory_tooltip_has_explicit_quality(lines):
            quality = None
    if quality is None and volume_scu is None:
        stack_item = _inventory_item_from_ocr_line(name, default_location, default_category)
        if stack_item:
            stack_item["notes"] = "Imported from hover scanner"
            stack_item["category"] = category or stack_item["category"]
            stack_item["item_type"] = item_type or stack_item["item_type"]
            stack_item["item_size"] = item_size
            return stack_item
    details = []
    if quality is not None:
        details.append(f"Quality: {quality:g}")
    if item_size:
        details.append(f"Size: {item_size}")
    if volume_scu is not None:
        details.append(f"Volume: {volume_scu:g} SCU")
    return {
        "name": name,
        "category": category,
        "item_type": item_type,
        "item_size": item_size,
        "location": default_location,
        "quantity": volume_scu if uses_scu and volume_scu is not None else 1.0,
        "quality": quality,
        "volume_scu": volume_scu,
        "notes": "Imported from hover scanner" + (f" ({', '.join(details)})" if details else ""),
    }


def _inventory_tooltip_block_for_match(blocks: list[list[str]], matched_name: str | None) -> list[str]:
    if not blocks:
        return []
    if not matched_name:
        return blocks[0]
    return max(
        blocks,
        key=lambda block: _inventory_match_confidence(_inventory_tooltip_name(block) or "", matched_name),
    )


def _inventory_tooltip_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        normalized = _normalize_text(line)
        if not normalized:
            continue
        if current and _inventory_line_starts_tooltip(line) and any(_inventory_line_is_tooltip_stat(item) for item in current):
            blocks.append(_inventory_tooltip_relevant_lines(current))
            current = [line]
            continue
        current.append(line)
    if current:
        blocks.append(_inventory_tooltip_relevant_lines(current))
    stat_blocks = [
        block
        for index, block in enumerate(blocks)
        if any(_inventory_line_is_tooltip_stat(line) for line in block)
        and (index == 0 or sum(1 for line in block if _inventory_line_is_tooltip_stat(line)) >= 2)
    ]
    return stat_blocks or blocks


def _inventory_line_starts_tooltip(line: str) -> bool:
    normalized = _normalize_text(line)
    if not normalized or _inventory_scanner_line_is_metadata(line):
        return False
    if _inventory_line_is_tooltip_stat(line):
        return False
    if re.search(r"\b\d{1,4}\b.*\b(?:scu|uscu|5cu)\b", normalized):
        return False
    words = normalized.split()
    if len(words) > 7:
        return False
    if sum(1 for word in words if word in {"the", "and", "to", "of", "for", "that", "with", "where", "you"}) >= 2:
        return False
    return any(char.isalpha() for char in line)


def _inventory_line_is_tooltip_stat(line: str) -> bool:
    normalized = _normalize_text(line)
    return normalized.startswith(
        (
            "volume",
            "manufacturer",
            "type",
            "item type",
            "attachment point",
            "attachmentpoint",
            "magnification",
            "zoom",
            "aim time",
            "parallax",
            "size",
            "class",
            "magazine size",
            "rate of fire",
            "fire rate",
            "effective range",
            "attachments",
            "capacity",
            "quality",
            "visual recoil",
        )
    )


def _inventory_tooltip_relevant_lines(lines: list[str]) -> list[str]:
    relevant: list[str] = []
    saw_stat = False
    after_description = False
    for line in lines:
        normalized = _normalize_text(line)
        if not normalized:
            continue
        if after_description:
            if normalized.startswith(("capacity", "quality")):
                relevant.append(line)
                continue
            if re.search(r"\b\d{1,4}\b.*\b(?:scu|uscu|5cu)\b", normalized) and not normalized.startswith(
                ("volume", "manufacturer", "type", "item type", "attachment", "magnification", "zoom", "aim", "size")
            ):
                relevant.append(line)
            continue
        if _inventory_line_is_tooltip_stat(line):
            saw_stat = True
            relevant.append(line)
            continue
        words = normalized.split()
        looks_like_description = len(words) >= 7 and sum(
            1 for word in words if word in {"the", "and", "to", "of", "for", "that", "with", "where", "you"}
        ) >= 2
        if saw_stat and looks_like_description:
            after_description = True
            continue
        relevant.append(line)
    return relevant


def _inventory_tooltip_name(lines: list[str]) -> str | None:
    blocked_prefixes = (
        "volume",
        "capacity",
        "storage",
        "quality",
        "1:",
        "2:",
        "3:",
        "4:",
        "5:",
        "featuring",
        "the ",
        "this ",
        "when ",
        "it ",
    )
    blocked_exact = {"empty", "personal", "backpack", "local", "looting view", "move all", "tart", "start"}
    for line in lines:
        lowered = line.casefold()
        if lowered in blocked_exact or lowered.startswith(blocked_prefixes):
            continue
        if _inventory_is_noisy_header(line):
            continue
        if re.search(r"\d+\s*(?:/|scu|µscu|uscu|q\b)", lowered):
            continue
        if 3 <= len(line) <= 80 and any(char.isalpha() for char in line):
            return _normalize_inventory_tooltip_name(line)
    return None


def _inventory_tooltip_quality(lines: list[str], name: str) -> float | None:
    for line in lines:
        if "quality" in line.casefold():
            match = re.search(r"(\d+(?:\.\d+)?)", line)
            if match:
                return float(match.group(1))
    label = name.split()[-1] if name else ""
    for index, line in enumerate(lines):
        if label and label.casefold() not in line.casefold():
            if re.fullmatch(r"\d{1,4}", line):
                nearby = " ".join(lines[index + 1 : index + 3]).casefold()
                if label.casefold() in nearby or "scu" in nearby:
                    return float(line)
            continue
        line_without_scu = re.sub(r"\d+(?:\.\d+)?\s*(?:scu|µscu|uscu|5cu)", " ", line, flags=re.IGNORECASE)
        numbers = [
            float(value)
            for value in re.findall(r"(?<![\d.])(\d{1,4})(?![\d.])", line_without_scu)
        ]
        if numbers:
            return numbers[-1]
    return None


def _inventory_tooltip_category(lines: list[str], default_category: str | None) -> tuple[str | None, str | None]:
    joined = " ".join(lines).casefold()
    if re.search(r"\bitem\s*type\s*[: ]\s*(?:lmg|rifle|shotgun|sniper|smg|launcher|railgun)\b", joined):
        return "Personal Weapons", "Primary"
    if re.search(r"\bitem\s*type\s*[: ]\s*(?:pistol|sidearm)\b", joined):
        return "Personal Weapons", "Sidearm"
    if "personal weapon" in joined or re.search(r"\b(pistol|rifle|shotgun|sniper|smg|lmg)\b", joined):
        return "Personal Weapons", "Primary"
    if (
        "attachmentpoint" in joined
        or "attachment point" in joined
        or "magnification" in joined
        or "optic" in joined
        or "holographic" in joined
        or "telescopic" in joined
    ):
        return "Personal Weapons", "Attachments"
    return default_category, None


def _inventory_tooltip_uses_scu(category: str | None, item_type: str | None, lines: list[str]) -> bool:
    joined = " ".join(lines).casefold()
    if category == "Personal Weapons" or item_type in {"Attachments", "Weapons"}:
        return False
    return "scu" in joined or "commodity" in joined or "material" in joined


def _inventory_tooltip_has_explicit_quality(lines: list[str]) -> bool:
    return any("quality" in line.casefold() for line in lines)


def _inventory_tooltip_volume_scu(lines: list[str]) -> float | None:
    joined = " ".join(lines)
    scu_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:SCU|5CU)", joined, flags=re.IGNORECASE)
    if scu_matches:
        return float(scu_matches[-1])
    micro_match = re.search(r"Volume\s*[: ]\s*(\d+(?:\.\d+)?)\s*(?:µSCU|uSCU|USCU|pSCU)", joined, flags=re.IGNORECASE)
    if micro_match:
        return float(micro_match.group(1)) / 1_000_000
    return None


def _inventory_tooltip_size(lines: list[str]) -> str | None:
    for line in lines:
        match = re.search(r"^Size\s*[: ]\s*(S?\d+)\b", line, flags=re.IGNORECASE)
        if match:
            value = match.group(1).upper()
            return value if value.startswith("S") else f"Size {value}"
    return None


def _clean_inventory_ocr_line(value: str) -> str:
    value = value.replace("μ", "µ").replace("Âµ", "µ")
    value = re.sub(r"[^A-Za-z0-9'’+./():µ -]", " ", value)
    return " ".join(value.split()).strip(" -.")


def _normalize_inventory_tooltip_name(value: str) -> str:
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    value = value.replace("KopionHorn", "Kopion Horn")
    value = re.sub(r'(\w)"', r'\1 "', value)
    value = re.sub(r'"(\()', r'" \1', value)
    value = re.sub(r"\)(\w)", r") \1", value)
    value = re.sub(r"(\d+)x([A-Z])", r"\1x \2", value)
    value = " ".join(value.split())
    replacements = {
        r"\bkilshot\b": "Killshot",
        r"\bkillshot\b": "Killshot",
        r"\brrie\b": "Rifle",
        r"\brifie\b": "Rifle",
        r"\brile\b": "Rifle",
        r"\brfie\b": "Rifle",
        r"\bparalax\b": "Parallax",
        r"\bsorguine\b": "Sanguine",
        r"\bsarguine\b": "Sanguine",
        r"\bcompensatora\b": "Compensator",
    }
    for pattern, replacement in replacements.items():
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return " ".join(value.split())


def _inventory_is_noisy_header(value: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", value.casefold())
    if "access" in normalized or "stor" in normalized and "acce" in normalized:
        return True
    if normalized.endswith("rccese") or normalized.endswith("rccece"):
        return True
    return False


def _inventory_item_from_ocr_line(
    line: str,
    default_location: str,
    default_category: str | None,
) -> dict[str, Any] | None:
    cleaned = _clean_inventory_ocr_line(line)
    if len(cleaned) < 3:
        return None
    blocked = {
        "inventory",
        "local inventory",
        "external inventory",
        "personal inventory",
        "filter",
        "search",
        "category",
        "location",
        "station",
        "quantity",
        "qty",
        "name",
        "items",
    }
    if cleaned.casefold() in blocked:
        return None

    quantity = 1.0
    quantity_match = re.search(r"(?:^|\s)(?:x\s*)?(\d+(?:\.\d+)?)(?:\s*x)?$", cleaned, flags=re.IGNORECASE)
    if quantity_match and quantity_match.start(1) > 0:
        quantity = float(quantity_match.group(1))
        cleaned = cleaned[: quantity_match.start(0)].strip(" -.")
    prefix_match = re.match(r"^(?:x\s*)?(\d+(?:\.\d+)?)\s+(.+)$", cleaned, flags=re.IGNORECASE)
    if prefix_match:
        quantity = float(prefix_match.group(1))
        cleaned = prefix_match.group(2).strip(" -.")

    if len(cleaned) < 3 or cleaned.casefold() in blocked:
        return None
    return {
        "name": cleaned,
        "category": default_category,
        "item_type": None,
        "item_size": None,
        "location": default_location,
        "quantity": quantity,
        "quality": None,
        "volume_scu": None,
        "notes": "Imported from screen capture",
    }


def _clean_blueprint_ocr_line(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9'’+./() -]", " ", value)
    value = " ".join(value.split()).strip(" -.")
    blocked = {"owned", "blueprint", "blueprints", "craft", "category", "search", "filter"}
    if _normalize_text(value) in blocked:
        return ""
    return value


def _blueprint_match_confidence(candidate: str, blueprint_name: str) -> float:
    candidate_norm = _normalize_text(candidate)
    blueprint_norm = _normalize_text(blueprint_name)
    if not candidate_norm or not blueprint_norm:
        return 0
    if candidate_norm == blueprint_norm:
        return 1
    if blueprint_norm in candidate_norm:
        return min(0.95, len(blueprint_norm) / max(len(candidate_norm), 1) + 0.25)
    if candidate_norm in blueprint_norm:
        return min(0.88, len(candidate_norm) / max(len(blueprint_norm), 1) + 0.2)
    candidate_words = set(candidate_norm.split())
    blueprint_words = set(blueprint_norm.split())
    overlap = len(candidate_words & blueprint_words)
    return overlap / max(len(blueprint_words), 1)


@app.get("/api/items")
async def items(
    query: str | None = None,
    category: str | None = None,
    section: str | None = None,
    size: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    page: int = Query(default=1, ge=1),
) -> list[dict[str, Any]]:
    return encode(await state().sources.lookup_items(query, category, section, size, limit, page))


@app.get("/api/items/{item_id}")
async def item(item_id: int) -> dict[str, Any]:
    result = await state().sources.lookup_item_by_id(item_id)
    if result is None:
        not_found(f"No item found for id {item_id}.")
    return encode(result)


@app.get("/api/autocomplete/items")
async def autocomplete_items(query: str = "") -> list[str]:
    return await state().sources.autocomplete_items(query)


@app.get("/api/trade/routes")
async def trade_routes(
    starting_point: str,
    ship: str = "Ironclad Assault",
    investment: float = Query(default=1_000_000, gt=0),
    cargo_capacity_scu: float | None = Query(default=None, gt=0),
    max_stops: int = Query(default=5, ge=2, le=5),
    stay_system: str | None = None,
) -> dict[str, Any]:
    capacity = cargo_capacity_scu
    if capacity is None:
        ship_result = await state().sources.lookup_ship(ship)
        capacity = ship_result.cargo_capacity if ship_result and ship_result.cargo_capacity else None
    if capacity is None:
        raise HTTPException(status_code=422, detail="Cargo capacity is required when the ship is unknown.")
    result = await state().sources.lookup_trade_routes(
        ship,
        capacity,
        starting_point,
        investment,
        max_stops,
        stay_system,
    )
    if result is None:
        not_found("No profitable circular route found.")
    return encode(result)


@app.get("/api/autocomplete/trade-locations")
async def autocomplete_trade_locations(query: str = "") -> list[str]:
    return await state().sources.autocomplete_trade_locations(query)


@app.get("/api/exec/status")
async def exec_status() -> dict[str, Any]:
    source_cycle_start = await fetch_exec_cycle_start_unix(state().settings.http_timeout_seconds)
    source_status = calculate_exec_hangar_status(source_cycle_start)
    override = await state().cache.get(EXEC_OVERRIDE_CACHE_KEY)
    active_status = source_status
    if isinstance(override, dict) and isinstance(override.get("cycle_start_unix"), int):
        active_status = calculate_exec_hangar_status(override["cycle_start_unix"])
    return {
        "source": encode(source_status),
        "active": encode(active_status),
        "override": override,
    }


@app.post("/api/exec/override", dependencies=[Depends(require_change_admin)])
async def set_exec_override(request: ExecOverrideRequest) -> dict[str, Any]:
    cycle_start = calculate_cycle_start_from_phase(request.phase, request.remaining_minutes)
    payload = {
        "cycle_start_unix": cycle_start,
        "phase": request.phase,
        "remaining_minutes": request.remaining_minutes,
        "corrected_by": request.corrected_by,
        "created_at": int(time.time()),
    }
    await state().cache.set(EXEC_OVERRIDE_CACHE_KEY, payload, 315360000)
    await state().cache.add_audit_event("Website Executive Hangar Override Set", payload)
    return {"status": "saved", "override": payload}


@app.delete("/api/exec/override", dependencies=[Depends(require_change_admin)])
async def clear_exec_override() -> dict[str, str]:
    await state().cache.delete(EXEC_OVERRIDE_CACHE_KEY)
    await state().cache.add_audit_event("Website Executive Hangar Override Cleared", {"Source": "Website"})
    return {"status": "cleared"}


@app.get("/api/cz/timers")
async def cz_timers() -> dict[str, Any]:
    return {
        "definitions": CZ_TIMER_DEFINITIONS,
        "timers": await get_cz_dashboard_timers(state().cache),
    }


@app.post("/api/cz/timers", dependencies=[Depends(require_change_admin)])
async def start_cz_timer(request: CZTimerRequest) -> dict[str, Any]:
    if request.timer not in CZ_TIMER_DEFINITIONS:
        raise HTTPException(status_code=422, detail="Unknown timer.")
    timers = await get_cz_dashboard_timers(state().cache)
    label, duration = CZ_TIMER_DEFINITIONS[request.timer]
    timers[request.timer] = {
        "label": label,
        "ends_at": calculate_countdown_end_unix(duration, request.started_minutes_ago),
        "duration_seconds": duration,
    }
    await state().cache.set(CZ_TIMERS_CACHE_KEY, timers, 315360000)
    await state().cache.add_audit_event("Website CZ Timer Started", {"Timer": label})
    return {"status": "saved", "timers": timers}


@app.delete("/api/cz/timers/{timer}", dependencies=[Depends(require_change_admin)])
async def reset_cz_timer(timer: str) -> dict[str, Any]:
    timers = await get_cz_dashboard_timers(state().cache)
    if timer == "all":
        timers = {}
    else:
        timers.pop(timer, None)
    await state().cache.set(CZ_TIMERS_CACHE_KEY, timers, 315360000)
    await state().cache.add_audit_event("Website CZ Timer Reset", {"Timer": timer})
    return {"status": "saved", "timers": timers}


@app.get("/api/audit/recent")
async def audit_recent(
    request: Request,
    limit: int = Query(default=10, ge=1, le=25),
    _: None = Depends(require_bot_admin),
) -> list[dict[str, Any]]:
    del request
    return await state().cache.recent_audit_events(limit)


app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        WEB_DIR / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )
