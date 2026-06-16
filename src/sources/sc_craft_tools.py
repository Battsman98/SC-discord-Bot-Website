from urllib.parse import urlencode

import aiohttp

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import BlueprintIngredient, BlueprintMission, BlueprintResult


class SCCraftToolsSource:
    name = "SC Craft Tools"
    base_url = "https://sc-craft.tools"

    def __init__(self, settings: Settings, cache: SQLiteCache, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._cache = cache
        self._session = session
        self._config: dict | None = None

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
    ) -> list[BlueprintResult]:
        params = {
            "limit": max(1, min(limit, 5)),
            "page": 1,
        }
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

        cache_key = f"sc-craft:blueprints:v1:{urlencode(params, doseq=True)}"
        cached = await self._cache.get(cache_key)
        if isinstance(cached, list):
            return [self._blueprint_from_cache(row) for row in cached if isinstance(row, dict)]

        payload = await self._fetch_json(f"{self.base_url}/api/blueprints?{urlencode(params)}")
        rows = payload.get("items") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return []

        config = await self._get_config()
        missions = config.get("missions") if isinstance(config, dict) else {}
        results = [
            self._parse_blueprint(row, missions if isinstance(missions, dict) else {})
            for row in rows
            if isinstance(row, dict)
        ]
        await self._cache.set(
            cache_key,
            [self._blueprint_to_cache(result) for result in results],
            self._settings.cache_ttl_seconds,
        )
        return results

    async def autocomplete_blueprints(self, query: str, limit: int = 25) -> list[str]:
        if not query.strip():
            return []

        payload = await self._fetch_json(
            f"{self.base_url}/api/blueprints?{urlencode({'search': query, 'limit': limit, 'page': 1})}"
        )
        rows = payload.get("items") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return []
        return [
            str(row.get("name"))
            for row in rows
            if isinstance(row, dict) and row.get("name")
        ][:limit]

    async def autocomplete_blueprint_filter(self, filter_name: str, query: str, limit: int = 25) -> list[str]:
        config = await self._get_config()
        hints = config.get("filterHints") if isinstance(config, dict) else {}
        values = hints.get(filter_name) if isinstance(hints, dict) else []
        names = []
        for value in values if isinstance(values, list) else []:
            if isinstance(value, dict):
                name = value.get("name")
            else:
                name = value
            if name:
                names.append(str(name))

        normalized_query = self._normalize(query)
        if not normalized_query:
            return names[:limit]

        starts = [name for name in names if self._normalize(name).startswith(normalized_query)]
        contains = [name for name in names if normalized_query in self._normalize(name) and name not in starts]
        return (starts + contains)[:limit]

    async def _get_config(self) -> dict:
        if self._config is not None:
            return self._config

        cached = await self._cache.get("sc-craft:config:v1")
        if isinstance(cached, dict):
            self._config = cached
            return self._config

        payload = await self._fetch_json(f"{self.base_url}/api/config")
        self._config = payload if isinstance(payload, dict) else {}
        await self._cache.set("sc-craft:config:v1", self._config, 6 * 60 * 60)
        return self._config

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
        return BlueprintResult(
            name=str(row.get("name") or "Unknown blueprint"),
            category=self._string_or_none(row.get("category")),
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
            source_url=f"{self.base_url}/?search={str(row.get('name') or '').replace(' ', '+')}",
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
        return BlueprintMission(
            name=str(row.get("name") or details.get("name") or "Unknown mission"),
            contractor=self._string_or_none(details.get("contractor")),
            mission_type=self._string_or_none(details.get("mission_type")),
            locations=self._string_or_none(details.get("locations")),
            min_standing_name=self._string_or_none(min_standing.get("name")),
            min_standing_reputation=self._number_or_none(min_standing.get("reputation")),
            drop_chance=self._number_or_none(row.get("drop_chance")),
        )

    def _first_option_value(self, row: dict, key: str) -> object:
        options = row.get("options")
        if isinstance(options, list) and options and isinstance(options[0], dict):
            return options[0].get(key)
        return None

    def _blueprint_to_cache(self, result: BlueprintResult) -> dict:
        data = result.__dict__.copy()
        data["ingredients"] = [ingredient.__dict__ for ingredient in result.ingredients]
        data["missions"] = [mission.__dict__ for mission in result.missions]
        return data

    def _blueprint_from_cache(self, data: dict) -> BlueprintResult:
        cached = data.copy()
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
