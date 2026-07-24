import json
import time
from pathlib import Path
from urllib.parse import urlencode

import aiohttp

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import (
    BlueprintIngredient,
    BlueprintMission,
    BlueprintResult,
    MissionBlueprintReward,
    MissionResult,
)


class SCCraftToolsSource:
    name = ""
    base_url = ""

    def __init__(self, settings: Settings, cache: SQLiteCache, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._cache = cache
        self._session = session
        self._config: dict | None = None
        self._config_expires_at = 0.0
        self._snapshot: dict | None = None
        self._snapshot_mtime_ns: int | None = None

    async def lookup(self, query: str):
        return None

    async def lookup_ship(self, query: str):
        return None

    async def autocomplete_ships(self, query: str, limit: int = 25) -> list[str]:
        return []

    async def lookup_blueprints(
        self,
        query: str | None = None,
        category: str | None = None,
        material: str | None = None,
        mission_type: str | None = None,
        contractor: str | None = None,
        location: str | None = None,
        limit: int = 3,
        page: int = 1,
    ) -> list[BlueprintResult]:
        category_values = await self._category_filter_values(category) if category else [None]
        all_results: list[BlueprintResult] = []
        seen_names: set[str] = set()
        offset = max(0, page - 1) * limit
        required_results = offset + limit
        for category_value in category_values:
            results = await self._lookup_blueprints_all(
                query=query,
                category=category_value,
                material=material,
                mission_type=mission_type,
                contractor=contractor,
                location=location,
            )
            for result in results:
                if result.name in seen_names:
                    continue
                seen_names.add(result.name)
                all_results.append(result)
                if len(all_results) >= required_results:
                    return all_results[offset:required_results]
        return all_results[offset:required_results]

    async def _lookup_blueprints_all(
        self,
        query: str | None = None,
        category: str | None = None,
        material: str | None = None,
        mission_type: str | None = None,
        contractor: str | None = None,
        location: str | None = None,
    ) -> list[BlueprintResult]:
        params = {"limit": 25, "page": 1}
        if query:
            params["search"] = query
        if category:
            params["category"] = category
        if material:
            params["resource"] = material
        if mission_type:
            params["mission_type"] = mission_type
        if contractor:
            params["contractor"] = contractor
        if location:
            params["location"] = location

        rows = self._snapshot_rows(params)
        return [
            self._parse_blueprint(row, {})
            for row in rows
            if isinstance(row, dict)
        ]

    def _snapshot_rows(self, params: dict) -> list[dict]:
        path = Path(__file__).resolve().parents[2] / "data" / "blueprints_snapshot.json"
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = None
        if (
            getattr(self, "_snapshot", None) is None
            or (
                hasattr(self, "_snapshot_mtime_ns")
                and self._snapshot_mtime_ns != mtime_ns
            )
        ):
            try:
                self._snapshot = json.loads(path.read_text(encoding="utf-8"))
                self._snapshot_mtime_ns = mtime_ns
            except (OSError, ValueError):
                self._snapshot = {}
                self._snapshot_mtime_ns = mtime_ns
        rows = self._snapshot.get("items") if isinstance(self._snapshot, dict) else []
        if not isinstance(rows, list):
            return []

        def contains(value: object, query: object) -> bool:
            return self._normalize(query) in self._normalize(value)

        matches = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if params.get("search") and not contains(row.get("name"), params["search"]):
                continue
            if params.get("category") and not contains(row.get("category"), params["category"]):
                continue
            ingredients = row.get("ingredients") if isinstance(row.get("ingredients"), list) else []
            if params.get("resource") and not any(contains(item.get("name"), params["resource"]) for item in ingredients if isinstance(item, dict)):
                continue
            missions = row.get("missions") if isinstance(row.get("missions"), list) else []
            if params.get("mission_type") and not any(contains(item.get("mission_type"), params["mission_type"]) for item in missions if isinstance(item, dict)):
                continue
            if params.get("contractor") and not any(contains(item.get("contractor"), params["contractor"]) for item in missions if isinstance(item, dict)):
                continue
            if params.get("location") and not any(contains(item.get("locations"), params["location"]) for item in missions if isinstance(item, dict)):
                continue
            matches.append(row)
        return matches

    async def lookup_missions(
        self,
        query: str | None = None,
        region: str | None = None,
        contractor: str | None = None,
        reputation_level: str | None = None,
        mission_type: str | None = None,
        limit: int = 25,
        page: int = 1,
    ) -> list[MissionResult]:
        self._snapshot_rows({})
        direct_rows = self._snapshot.get("missions") if isinstance(self._snapshot, dict) else []
        if isinstance(direct_rows, list) and direct_rows:
            return self._filter_direct_missions(
                direct_rows, query, region, contractor, reputation_level,
                mission_type, limit, page,
            )
        rows = self._snapshot_rows({})
        missions: dict[str, dict] = {}
        for blueprint in rows:
            blueprint_name = self._string_or_none(blueprint.get("name"))
            version = self._string_or_none(blueprint.get("version"))
            for row in blueprint.get("missions", []) if isinstance(blueprint.get("missions"), list) else []:
                if not isinstance(row, dict):
                    continue
                mission_name = str(row.get("name") or "Unknown mission")
                mission_id = self._string_or_none(row.get("mission_id"))
                key = mission_id or "|".join(
                    self._normalize(row.get(field)) for field in ("name", "contractor", "locations")
                )
                standing = row.get("min_standing") if isinstance(row.get("min_standing"), dict) else {}
                entry = missions.setdefault(key, {
                    "mission_id": mission_id,
                    "name": mission_name,
                    "contractor": self._string_or_none(row.get("contractor")),
                    "mission_type": self._string_or_none(row.get("mission_type")),
                    "region": self._string_or_none(row.get("locations")),
                    "min_standing_name": self._string_or_none(standing.get("name")),
                    "min_standing_reputation": self._number_or_none(standing.get("reputation")),
                    "version": version,
                    "rewards": {},
                })
                if blueprint_name:
                    entry["rewards"][blueprint_name] = self._number_or_none(row.get("drop_chance"))

        def matches(value: object, wanted: str | None) -> bool:
            return not wanted or self._normalize(wanted) in self._normalize(value)

        results = []
        for entry in missions.values():
            searchable = " ".join(str(entry.get(field) or "") for field in (
                "name", "contractor", "mission_type", "region", "min_standing_name"
            ))
            if not matches(searchable, query):
                continue
            if not matches(entry["region"], region) or not matches(entry["contractor"], contractor):
                continue
            if not matches(entry["min_standing_name"], reputation_level):
                continue
            if not matches(entry["mission_type"], mission_type):
                continue
            results.append(MissionResult(
                mission_id=entry["mission_id"],
                name=entry["name"],
                contractor=entry["contractor"],
                mission_type=entry["mission_type"],
                region=entry["region"],
                min_standing_name=entry["min_standing_name"],
                min_standing_reputation=entry["min_standing_reputation"],
                version=entry["version"],
                blueprint_rewards=[
                    MissionBlueprintReward(name=name, drop_chance=chance)
                    for name, chance in sorted(entry["rewards"].items())
                ],
                source_name=self.name,
            source_url="",
            ))
        results.sort(key=lambda item: (
            self._normalize(item.contractor),
            item.min_standing_reputation if item.min_standing_reputation is not None else -1,
            self._normalize(item.name),
        ))
        offset = max(0, page - 1) * limit
        return results[offset:offset + limit]

    def _filter_direct_missions(
        self, rows: list, query: str | None, region: str | None,
        contractor: str | None, reputation_level: str | None,
        mission_type: str | None, limit: int, page: int,
    ) -> list[MissionResult]:
        def matches(value: object, wanted: str | None) -> bool:
            return not wanted or self._normalize(wanted) in self._normalize(value)

        results = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            standing = row.get("min_standing") if isinstance(row.get("min_standing"), dict) else {}
            searchable = " ".join(str(row.get(field) or "") for field in (
                "name", "contractor", "mission_type", "locations"
            ))
            if not matches(searchable, query):
                continue
            if not matches(row.get("locations"), region) or not matches(row.get("contractor"), contractor):
                continue
            if not matches(standing.get("name"), reputation_level):
                continue
            if not matches(row.get("mission_type"), mission_type):
                continue
            rewards = row.get("blueprint_rewards") if isinstance(row.get("blueprint_rewards"), list) else []
            results.append(MissionResult(
                mission_id=self._string_or_none(row.get("mission_id")),
                name=str(row.get("name") or "Unknown mission"),
                contractor=self._string_or_none(row.get("contractor")),
                mission_type=self._string_or_none(row.get("mission_type")),
                region=self._string_or_none(row.get("locations")),
                min_standing_name=self._string_or_none(standing.get("name")),
                min_standing_reputation=self._number_or_none(standing.get("reputation")),
                version=self._string_or_none(row.get("version")),
                blueprint_rewards=[
                    MissionBlueprintReward(
                        name=str(reward.get("name") or "Unknown blueprint"),
                        drop_chance=self._number_or_none(reward.get("drop_chance")),
                    )
                    for reward in rewards if isinstance(reward, dict)
                ],
                source_name=self.name,
                source_url="",
            ))
        results.sort(key=lambda item: (
            self._normalize(item.contractor),
            item.min_standing_reputation if item.min_standing_reputation is not None else -1,
            self._normalize(item.name),
        ))
        offset = max(0, page - 1) * limit
        return results[offset:offset + limit]

    async def autocomplete_missions(self, filter_name: str, query: str, limit: int = 25) -> list[str]:
        results = await self.lookup_missions(limit=10000)
        attribute = {
            "name": "name",
            "region": "region",
            "contractor": "contractor",
            "reputation_level": "min_standing_name",
            "mission_type": "mission_type",
        }.get(filter_name, "name")
        values = sorted({
            str(getattr(result, attribute))
            for result in results
            if getattr(result, attribute)
        })
        normalized = self._normalize(query)
        starts = [value for value in values if self._normalize(value).startswith(normalized)]
        contains = [value for value in values if normalized in self._normalize(value) and value not in starts]
        return (starts + contains)[:limit]

    async def autocomplete_blueprints(self, query: str, limit: int = 25) -> list[str]:
        if not query.strip():
            return []
        rows = self._snapshot_rows({"search": query})
        return [
            str(row.get("name"))
            for row in rows
            if isinstance(row, dict) and row.get("name")
        ][:limit]

    async def autocomplete_blueprint_filter(self, filter_name: str, query: str, limit: int = 25) -> list[str]:
        filter_name = self._api_filter_name(filter_name)
        rows = self._snapshot_rows({})
        names = []
        for row in rows:
            if filter_name == "category":
                name = self._display_category(row.get("category"))
                if name:
                    names.append(name)
            elif filter_name == "resource":
                ingredients = row.get("ingredients") if isinstance(row.get("ingredients"), list) else []
                names.extend(
                    str(item.get("name"))
                    for item in ingredients
                    if isinstance(item, dict) and item.get("name")
                )
            else:
                missions = row.get("missions") if isinstance(row.get("missions"), list) else []
                names.extend(
                    str(item.get(filter_name))
                    for item in missions
                    if isinstance(item, dict) and item.get(filter_name)
                )
        names = list(dict.fromkeys(names))

        normalized_query = self._normalize(query)
        if not normalized_query:
            return names[:limit]

        starts = [name for name in names if self._normalize(name).startswith(normalized_query)]
        contains = [name for name in names if normalized_query in self._normalize(name) and name not in starts]
        return (starts + contains)[:limit]

    def _api_filter_name(self, filter_name: str) -> str:
        return {
            "material": "resource",
        }.get(filter_name, filter_name)

    async def _get_config(self) -> dict:
        if self._config is not None and (
            not hasattr(self, "_config_expires_at") or time.monotonic() < self._config_expires_at
        ):
            return self._config

        cached = await self._cache.get("sc-craft:config:v2")
        if isinstance(cached, dict):
            self._config = cached
            self._config_expires_at = time.monotonic() + 5 * 60
            return self._config

        payload = await self._fetch_json(f"{self.base_url}/api/config")
        self._config = payload if isinstance(payload, dict) else {}
        self._config_expires_at = time.monotonic() + 5 * 60
        if self._config:
            await self._cache.set("sc-craft:config:v2", self._config, 5 * 60)
        return self._config

    def _active_data_version(self, config: dict) -> str:
        versions = config.get("versions") if isinstance(config, dict) else []
        active = []
        for row in versions if isinstance(versions, list) else []:
            if not isinstance(row, dict) or not row.get("active"):
                continue
            version = self._string_or_none(row.get("version"))
            if version:
                active.append(version)
        return ",".join(sorted(active)) or "unknown"

    async def _fetch_json(self, url: str) -> dict | None:
        try:
            async with self._session.get(url, headers={"Accept": "application/json"}) as response:
                response.raise_for_status()
                payload = await response.json()
                return payload if isinstance(payload, dict) else None
        except (aiohttp.ClientError, ValueError):
            return None

    def _parse_blueprint(self, row: dict, missions_by_id: dict) -> BlueprintResult:
        mission_rows = row.get("missions") if isinstance(row.get("missions"), list) else []
        name = str(row.get("name") or "Unknown blueprint")
        raw_category = row.get("category")
        return BlueprintResult(
            name=name,
            category=self._display_category(raw_category),
            craft_time_seconds=self._int_or_none(row.get("craft_time_seconds")),
            tiers=self._int_or_none(row.get("tiers")),
            version=self._string_or_none(row.get("version")),
            ingredients=self._parse_ingredients(row.get("ingredients")),
            missions=[
                self._parse_mission(mission, missions_by_id)
                for mission in mission_rows
                if isinstance(mission, dict)
            ],
            source_name=self.name,
            source_url="",
            component_size=self._component_size(raw_category),
        )

    def _parse_ingredients(self, value: object) -> list[BlueprintIngredient]:
        if not isinstance(value, list):
            return []

        ingredients = []
        for row in value:
            if not isinstance(row, dict):
                continue
            ingredients.append(
                BlueprintIngredient(
                    name=str(row.get("name") or "Unknown material"),
                    quantity=self._number_or_none(row.get("quantity_scu")),
                    unit=self._string_or_none(self._first_option_value(row, "unit")) or "SCU",
                    slot=self._string_or_none(row.get("slot")),
                )
            )
        return ingredients

    def _parse_mission(self, row: dict, missions_by_id: dict) -> BlueprintMission:
        mission_id = str(row.get("mission_id") or "")
        details = missions_by_id.get(mission_id)
        if not isinstance(details, dict):
            details = {}
        min_standing = details.get("min_standing") if isinstance(details.get("min_standing"), dict) else {}
        row_min_standing = row.get("min_standing") if isinstance(row.get("min_standing"), dict) else {}
        return BlueprintMission(
            name=str(row.get("name") or details.get("name") or "Unknown mission"),
            contractor=self._string_or_none(details.get("contractor") or row.get("contractor")),
            mission_type=self._string_or_none(details.get("mission_type") or row.get("mission_type")),
            locations=self._string_or_none(details.get("locations") or row.get("locations")),
            min_standing_name=self._string_or_none(min_standing.get("name") or row_min_standing.get("name")),
            min_standing_reputation=self._number_or_none(min_standing.get("reputation") if min_standing.get("reputation") is not None else row_min_standing.get("reputation")),
            drop_chance=self._number_or_none(row.get("drop_chance")),
        )

    def _first_option_value(self, row: dict, key: str) -> object:
        options = row.get("options")
        if isinstance(options, list) and options and isinstance(options[0], dict):
            return options[0].get(key)
        return None

    async def _category_filter_values(self, category: str | None) -> list[str | None]:
        if not category:
            return [None]
        raw_categories = [
            str(row.get("category"))
            for row in self._snapshot_rows({})
            if row.get("category")
        ]

        normalized_category = self._normalize(category)
        matches = [
            raw
            for raw in raw_categories
            if self._normalize(raw) == normalized_category
            or self._normalize(self._display_category(raw)) == normalized_category
        ]
        return matches or [category]

    def _display_category(self, value: object) -> str | None:
        raw = self._string_or_none(value)
        if raw is None:
            return None

        parts = [part.strip() for part in raw.split("/") if part.strip()]
        if not parts:
            return raw

        root = parts[0].lower()
        rest = parts[1:]
        if root == "vehiclegear":
            return self._display_vehicle_category(rest)
        if root == "armour":
            return self._display_armour_category(rest)
        if root == "ammo" and rest:
            return f"{self._title_category(' '.join(rest))} Ammo"
        if root == "weapons":
            return self._title_category(" ".join(rest) if rest else "Weapons")
        return self._title_category(" ".join(rest or parts))

    def _component_size(self, value: object) -> str | None:
        raw = self._string_or_none(value)
        if raw is None:
            return None

        for part in raw.split("/"):
            normalized = self._normalize(part)
            if normalized.startswith("size"):
                number = normalized.removeprefix("size").strip()
                return f"Size {number}" if number else self._title_category(normalized)
        return None

    def _display_vehicle_category(self, parts: list[str]) -> str:
        cleaned = [part for part in parts if not self._normalize(part).startswith("size")]
        if not cleaned:
            return "Vehicle Gear"
        aliases = {
            "mininglaser": "Mining Laser",
            "powerplant": "Power Plant",
            "quantumdrive": "Quantum Drive",
            "tractorbeam": "Tractor Beam",
            "refuelling nozzle": "Refueling Nozzle",
        }
        key = self._normalize(" ".join(cleaned))
        if key in aliases:
            return aliases[key]
        if cleaned[0].lower() == "weapons":
            return self._title_category(" ".join(cleaned[1:] or cleaned))
        return self._title_category(" ".join(cleaned))

    def _display_armour_category(self, parts: list[str]) -> str:
        normalized_parts = [self._normalize(part) for part in parts]
        if "flightsuit" in normalized_parts or "undersuit" in normalized_parts:
            return "Flight Suits"
        for weight in ("heavy", "medium", "light"):
            if weight in normalized_parts:
                return f"{weight.title()} Armor"
        if parts:
            return f"{self._title_category(' '.join(parts))} Armor"
        return "Armor"

    def _title_category(self, value: str) -> str:
        aliases = {
            "lmg": "LMG",
            "smg": "SMG",
        }
        words = []
        for word in value.replace("-", " ").split():
            normalized = word.lower()
            words.append(aliases.get(normalized, normalized.title()))
        return " ".join(words)

    def _blueprint_to_cache(self, result: BlueprintResult) -> dict:
        data = result.__dict__.copy()
        data["ingredients"] = [ingredient.__dict__ for ingredient in result.ingredients]
        data["missions"] = [mission.__dict__ for mission in result.missions]
        return data

    def _blueprint_from_cache(self, data: dict) -> BlueprintResult:
        cached = data.copy()
        cached["category"] = self._display_category(cached.get("category"))
        cached.setdefault("component_size", None)
        cached["ingredients"] = [
            BlueprintIngredient(**ingredient)
            for ingredient in cached.get("ingredients", [])
            if isinstance(ingredient, dict)
        ]
        cached["missions"] = [
            BlueprintMission(**mission)
            for mission in cached.get("missions", [])
            if isinstance(mission, dict)
        ]
        return BlueprintResult(**cached)

    def _normalize(self, value: object) -> str:
        return " ".join(str(value or "").lower().replace("-", " ").split())

    def _string_or_none(self, value: object) -> str | None:
        return str(value) if value not in (None, "") else None

    def _int_or_none(self, value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _number_or_none(self, value: object) -> int | float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return int(number) if number.is_integer() else number

    async def close(self) -> None:
        return None
