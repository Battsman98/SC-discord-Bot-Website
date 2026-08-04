"""Domain helpers shared by the website and Discord bot.

This module must not import Discord or FastAPI so either service can start and
deploy without loading the other application's runtime.
"""

from __future__ import annotations

import re

from src.cache import SQLiteCache
from src.sources.base import MiningLocationResult, MiningSystemLocations


CZ_TIMERS_CACHE_KEY = "cz:dashboard:timers"
EXEC_OVERRIDE_CACHE_KEY = "exec:cycle-start-override"
MINING_COMMUNITY_LOCATIONS_CACHE_KEY = "mining:community-locations:v1"
CZ_TIMER_DEFINITIONS = {
    "blue_keycard": ("Blue Keycards", 15 * 60),
    "compboard": ("Compboards / Tablets", 30 * 60),
    "red_keycard": ("Red Keycards", 30 * 60),
    "timer_door": ("Timer Doors", 20 * 60),
}


async def get_cz_dashboard_timers(cache: SQLiteCache) -> dict:
    timers = await cache.get(CZ_TIMERS_CACHE_KEY)
    return timers if isinstance(timers, dict) else {}


def _normalize_text(value: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _has_mining_multi_separator(value: str) -> bool:
    return bool(re.search(r"\s*(,|;|\+|&|\band\b)\s*", value, flags=re.IGNORECASE))


def _mining_multi_search_terms(value: str) -> list[str]:
    if not _has_mining_multi_separator(value):
        return [value.strip()] if value.strip() else []
    return [
        term.strip()
        for term in re.split(r"\s*(?:,|;|\+|&|\band\b)\s*", value, flags=re.IGNORECASE)
        if term.strip()
    ]


def _mining_space_search_terms(value: str) -> list[str]:
    return [term.strip() for term in value.split() if term.strip()]


def _mining_term_signatures(result: MiningLocationResult, term: str) -> list[int]:
    signatures = result.rock_signatures or []
    text = str(term or "").replace(",", "").strip()
    signature = int(text) if text.isdigit() else None
    if signature is None:
        return signatures
    return [
        base for base in signatures
        if signature == base or (signature % base == 0 and 1 <= signature // base <= 6)
    ]


def _shared_mining_signatures(signature_groups: list[list[int]]) -> list[int]:
    if not signature_groups or any(not signatures for signatures in signature_groups):
        return []
    shared = set(signature_groups[0])
    for signatures in signature_groups[1:]:
        shared.intersection_update(signatures)
    return sorted(shared)


def _unique_preserve_order(values) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = _normalize_text(value)
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


async def _community_mining_entries(cache: SQLiteCache) -> dict:
    entries = await cache.get(MINING_COMMUNITY_LOCATIONS_CACHE_KEY)
    return entries if isinstance(entries, dict) else {}


async def add_community_mining_location(cache: SQLiteCache, entry: dict) -> None:
    entries = await _community_mining_entries(cache)
    material_entries = entries.setdefault(_normalize_text(entry.get("material")), [])
    new_entry = {
        key: str(entry.get(key) or "").strip()
        for key in ("material", "system", "location_type", "location", "reported_by")
    }
    duplicate = any(
        all(_normalize_text(existing.get(key)) == _normalize_text(new_entry[key])
            for key in ("system", "location_type", "location"))
        for existing in material_entries if isinstance(existing, dict)
    )
    if not duplicate:
        material_entries.append(new_entry)
    await cache.set(MINING_COMMUNITY_LOCATIONS_CACHE_KEY, entries, 315360000)


def _append_unique(values: list[str], value: str) -> None:
    if all(_normalize_text(existing) != _normalize_text(value) for existing in values):
        values.append(value)


async def apply_community_mining_locations(
    cache: SQLiteCache, result: MiningLocationResult,
) -> MiningLocationResult:
    entries = await _community_mining_entries(cache)
    material_entries = entries.get(_normalize_text(result.material_name), [])
    if not material_entries:
        return result

    groups = list(result.location_groups or [])
    groups_by_system = {_normalize_text(group.system): group for group in groups}
    systems, lagrange_points = list(result.systems), list(result.lagrange_points)
    planets, moons = list(result.planets), list(result.moons)
    points_of_interest = list(result.points_of_interest)
    destinations = {
        "lagrange_points": lagrange_points, "planets": planets,
        "moons": moons, "points_of_interest": points_of_interest,
    }
    for entry in material_entries:
        if not isinstance(entry, dict):
            continue
        system = str(entry.get("system") or "").strip()
        kind = str(entry.get("location_type") or "").strip()
        location = str(entry.get("location") or "").strip()
        if not system or kind not in destinations or not location:
            continue
        system_key = _normalize_text(system)
        if system_key not in groups_by_system:
            group = MiningSystemLocations(system=system, lagrange_points=[], planets=[], moons=[], points_of_interest=[])
            groups_by_system[system_key] = group
            groups.append(group)
        display = f"{location} (Community)"
        _append_unique(getattr(groups_by_system[system_key], kind), display)
        _append_unique(systems, system)
        _append_unique(destinations[kind], display)

    values = dict(result.__dict__)
    values.update(systems=systems, lagrange_points=lagrange_points, planets=planets,
                  moons=moons, points_of_interest=points_of_interest, location_groups=groups)
    return MiningLocationResult(**values)
