import aiohttp

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import (
    BlueprintResult,
    CommodityResult,
    GameInfoSource,
    ItemLocatorResult,
    LookupResult,
    MiningLocationResult,
    ShipResult,
    TradeRouteResult,
)
from src.sources.sc_craft_tools import SCCraftToolsSource
from src.sources.star_citizen_wiki import StarCitizenWikiSource
from src.sources.uex import UEXSource


class SourceRegistry:
    def __init__(self, sources: list[GameInfoSource], session: aiohttp.ClientSession) -> None:
        self._sources = sources
        self._session = session

    async def lookup(self, query: str) -> LookupResult | None:
        for source in self._sources:
            result = await source.lookup(query)
            if result is not None:
                return result
        return None

    async def lookup_ship(self, query: str) -> ShipResult | None:
        for source in self._sources:
            result = await source.lookup_ship(query)
            if result is not None:
                return result
        return None

    async def search_ships(
        self,
        query: str | None = None,
        manufacturer: str | None = None,
        vehicle_type: str | None = None,
        size: str | None = None,
        role: str | None = None,
        status: str | None = None,
        min_cargo: int | float | None = None,
        max_cargo: int | float | None = None,
        limit: int = 24,
        page: int = 1,
    ) -> list[ShipResult]:
        for source in self._sources:
            search = getattr(source, "search_ships", None)
            if search is None:
                continue
            results = await search(query, manufacturer, vehicle_type, size, role, status, min_cargo, max_cargo, limit, page)
            if results:
                return results
        return []

    async def ship_facets(self) -> dict[str, list[str]]:
        for source in self._sources:
            facets = getattr(source, "ship_facets", None)
            if facets is None:
                continue
            result = await facets()
            if result:
                return result
        return {"manufacturers": [], "types": [], "sizes": [], "roles": [], "statuses": []}

    async def autocomplete_ships(self, query: str, limit: int = 25) -> list[str]:
        seen: set[str] = set()
        matches: list[str] = []

        for source in self._sources:
            for name in await source.autocomplete_ships(query, limit):
                if name in seen:
                    continue
                seen.add(name)
                matches.append(name)
                if len(matches) >= limit:
                    return matches

        return matches

    async def lookup_commodity(
        self,
        query: str,
        system: str | None = None,
        purchase_system: str | None = None,
        sell_system: str | None = None,
    ) -> CommodityResult | None:
        for source in self._sources:
            lookup = getattr(source, "lookup_commodity", None)
            if lookup is None:
                continue
            result = await lookup(query, system, purchase_system, sell_system)
            if result is not None:
                return result
        return None

    async def autocomplete_commodities(self, query: str, limit: int = 25) -> list[str]:
        seen: set[str] = set()
        matches: list[str] = []

        for source in self._sources:
            autocomplete = getattr(source, "autocomplete_commodities", None)
            if autocomplete is None:
                continue
            for name in await autocomplete(query, limit):
                if name in seen:
                    continue
                seen.add(name)
                matches.append(name)
                if len(matches) >= limit:
                    return matches

        return matches

    async def lookup_mining_material(
        self,
        material: str,
        system: str | None = None,
        planet: str | None = None,
    ) -> MiningLocationResult | None:
        for source in self._sources:
            lookup = getattr(source, "lookup_mining_material", None)
            if lookup is None:
                continue
            result = await lookup(material, system, planet)
            if result is not None:
                return result
        return None

    async def autocomplete_mining_materials(self, query: str, limit: int = 25) -> list[str]:
        seen: set[str] = set()
        matches: list[str] = []

        for source in self._sources:
            autocomplete = getattr(source, "autocomplete_mining_materials", None)
            if autocomplete is None:
                continue
            for name in await autocomplete(query, limit):
                if name in seen:
                    continue
                seen.add(name)
                matches.append(name)
                if len(matches) >= limit:
                    return matches

        return matches

    async def autocomplete_mining_locations(
        self,
        query: str,
        system: str | None = None,
        limit: int = 25,
    ) -> list[str]:
        seen: set[str] = set()
        matches: list[str] = []

        for source in self._sources:
            autocomplete = getattr(source, "autocomplete_mining_locations", None)
            if autocomplete is None:
                continue
            for name in await autocomplete(query, system, limit):
                if name in seen:
                    continue
                seen.add(name)
                matches.append(name)
                if len(matches) >= limit:
                    return matches

        return matches

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
        for source in self._sources:
            lookup = getattr(source, "lookup_blueprints", None)
            if lookup is None:
                continue
            results = await lookup(query, category, material, mission_type, contractor, location, limit, page)
            if results:
                return results
        return []

    async def autocomplete_blueprints(self, query: str, limit: int = 25) -> list[str]:
        seen: set[str] = set()
        matches: list[str] = []

        for source in self._sources:
            autocomplete = getattr(source, "autocomplete_blueprints", None)
            if autocomplete is None:
                continue
            for name in await autocomplete(query, limit):
                if name in seen:
                    continue
                seen.add(name)
                matches.append(name)
                if len(matches) >= limit:
                    return matches

        return matches

    async def autocomplete_blueprint_filter(self, filter_name: str, query: str, limit: int = 25) -> list[str]:
        seen: set[str] = set()
        matches: list[str] = []

        for source in self._sources:
            autocomplete = getattr(source, "autocomplete_blueprint_filter", None)
            if autocomplete is None:
                continue
            for name in await autocomplete(filter_name, query, limit):
                if name in seen:
                    continue
                seen.add(name)
                matches.append(name)
                if len(matches) >= limit:
                    return matches

        return matches

    async def lookup_items(
        self,
        query: str | None = None,
        category: str | None = None,
        section: str | None = None,
        size: str | None = None,
        limit: int = 25,
        page: int = 1,
    ) -> list[ItemLocatorResult]:
        for source in self._sources:
            lookup = getattr(source, "lookup_items", None)
            if lookup is None:
                continue
            results = await lookup(query, category, section, size, limit, page)
            if results:
                return results
        return []

    async def lookup_item_by_id(self, item_id: int) -> ItemLocatorResult | None:
        for source in self._sources:
            lookup = getattr(source, "lookup_item_by_id", None)
            if lookup is None:
                continue
            result = await lookup(item_id)
            if result is not None:
                return result
        return None

    async def lookup_inventory_items(self, query: str, limit: int = 10) -> list[ItemLocatorResult]:
        seen: set[str] = set()
        matches: list[ItemLocatorResult] = []
        for source in self._sources:
            lookup = getattr(source, "lookup_inventory_items", None)
            if lookup is None:
                continue
            for result in await lookup(query, limit):
                key = result.name.casefold()
                if key in seen:
                    continue
                seen.add(key)
                matches.append(result)
                if len(matches) >= limit:
                    return matches
        if matches:
            return matches
        return await self.lookup_items(query=query, limit=limit)

    async def autocomplete_items(self, query: str, limit: int = 25) -> list[str]:
        seen: set[str] = set()
        matches: list[str] = []

        for source in self._sources:
            autocomplete = getattr(source, "autocomplete_items", None)
            if autocomplete is None:
                continue
            for name in await autocomplete(query, limit):
                if name in seen:
                    continue
                seen.add(name)
                matches.append(name)
                if len(matches) >= limit:
                    return matches

        return matches

    async def autocomplete_item_filter(self, filter_name: str, query: str, limit: int = 25) -> list[str]:
        seen: set[str] = set()
        matches: list[str] = []

        for source in self._sources:
            autocomplete = getattr(source, "autocomplete_item_filter", None)
            if autocomplete is None:
                continue
            for name in await autocomplete(filter_name, query, limit):
                if name in seen:
                    continue
                seen.add(name)
                matches.append(name)
                if len(matches) >= limit:
                    return matches

        return matches

    async def lookup_trade_routes(
        self,
        ship: str,
        cargo_capacity_scu: int | float,
        starting_point: str,
        investment: int | float,
        max_stops: int = 5,
        stay_system: str | None = None,
    ) -> TradeRouteResult | None:
        for source in self._sources:
            lookup = getattr(source, "lookup_trade_routes", None)
            if lookup is None:
                continue
            result = await lookup(ship, cargo_capacity_scu, starting_point, investment, max_stops, stay_system)
            if result is not None:
                return result
        return None

    async def autocomplete_trade_locations(self, query: str, limit: int = 25) -> list[str]:
        seen: set[str] = set()
        matches: list[str] = []

        for source in self._sources:
            autocomplete = getattr(source, "autocomplete_trade_locations", None)
            if autocomplete is None:
                continue
            for name in await autocomplete(query, limit):
                if name in seen:
                    continue
                seen.add(name)
                matches.append(name)
                if len(matches) >= limit:
                    return matches

        return matches

    async def close(self) -> None:
        for source in self._sources:
            await source.close()
        await self._session.close()


async def build_default_registry(settings: Settings, cache: SQLiteCache) -> SourceRegistry:
    timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)
    session = aiohttp.ClientSession(
        timeout=timeout,
        headers={
            "User-Agent": "GameAssistBot/0.1 (Discord bot; Star Citizen lookup)",
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        },
    )
    sources: list[GameInfoSource] = [
        StarCitizenWikiSource(settings, cache, session),
        UEXSource(settings, cache, session),
        SCCraftToolsSource(settings, cache, session),
    ]
    return SourceRegistry(sources, session)
