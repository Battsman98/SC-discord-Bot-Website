import re
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import (
    CommodityMarket,
    CommodityResult,
    ItemLocatorResult,
    ItemPurchaseLocation,
    MiningLocationResult,
    MiningSystemLocations,
    TradeRouteLeg,
    TradeRouteResult,
)


class UEXSource:
    name = "UEX"
    base_url = "https://api.uexcorp.uk/2.0"

    def __init__(self, settings: Settings, cache: SQLiteCache, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._cache = cache
        self._session = session
        self._commodities: list[dict] | None = None
        self._all_prices: list[dict] | None = None
        self._item_categories: list[dict] | None = None
        self._items_by_category: dict[int, list[dict]] = {}
        self._all_item_prices: list[dict] | None = None
        self._buyable_items: list[dict] | None = None
        self._terminals_by_id: dict[str, dict] | None = None
        self._location_filter_names: list[str] | None = None
        self._mining_associations: dict[str, list[str]] | None = None
        self._mining_signatures: dict[str, list[int]] | None = None

    async def lookup(self, query: str):
        return None

    async def lookup_ship(self, query: str):
        return None

    async def autocomplete_ships(self, query: str, limit: int = 25) -> list[str]:
        return []

    async def lookup_commodity(
        self,
        query: str,
        system: str | None = None,
        purchase_system: str | None = None,
        sell_system: str | None = None,
    ) -> CommodityResult | None:
        commodity = await self._find_commodity(query)
        if commodity is None:
            return None

        normalized_system = self._normalize(system)
        normalized_purchase_system = self._normalize(purchase_system) or normalized_system
        normalized_sell_system = self._normalize(sell_system) or normalized_system
        cache_key = (
            f"uex:commodity:v7:{commodity['name'].lower()}:"
            f"buy-{normalized_purchase_system or 'all'}:"
            f"sell-{normalized_sell_system or 'all'}"
        )
        cached = await self._cache.get(cache_key)
        if cached:
            return self._commodity_from_cache(cached)

        prices = await self._fetch_prices(str(commodity["name"]))
        result = self._parse_commodity(commodity, prices, system, purchase_system, sell_system)
        await self._cache.set(cache_key, self._commodity_to_cache(result), self._settings.cache_ttl_seconds)
        return result

    async def autocomplete_commodities(self, query: str, limit: int = 25) -> list[str]:
        commodities = await self._get_commodities()
        normalized_query = self._normalize(query)
        names = [self._display_name(row) for row in commodities if row.get("name")]

        if not normalized_query:
            return names[:limit]

        exact_codes = [
            self._display_name(row)
            for row in commodities
            if self._normalize(row.get("code")) == normalized_query
        ]
        starts = [
            self._display_name(row)
            for row in commodities
            if (
                self._normalize(row.get("name")).startswith(normalized_query)
                or self._normalize(row.get("code")).startswith(normalized_query)
            )
            and self._display_name(row) not in exact_codes
        ]
        contains = [
            self._display_name(row)
            for row in commodities
            if (
                normalized_query in self._normalize(row.get("name"))
                or normalized_query in self._normalize(row.get("code"))
            )
            and self._display_name(row) not in exact_codes
            and self._display_name(row) not in starts
        ]
        return (exact_codes + starts + contains)[:limit]

    async def lookup_mining_material(
        self,
        material: str,
        system: str | None = None,
        planet: str | None = None,
    ) -> MiningLocationResult | None:
        commodity = await self._find_mining_material(material)
        if commodity is None:
            return None

        system_code = self._mining_system_code(system)
        result = await self._fetch_mining_location_result(commodity, system_code)
        if result is None:
            return None
        result = await self._with_mining_sell_prices(result, commodity)
        result = await self._with_mining_signatures(result, commodity)
        result = await self._with_mining_location_groups(result, commodity, system_code)

        filtered_result = self._filter_mining_result(result, planet)
        if self._has_mining_locations(filtered_result):
            return filtered_result

        expanded_result = await self._expand_mining_result_from_associated_deposits(result, commodity, system_code)
        filtered_expanded = self._filter_mining_result(expanded_result, planet)
        return filtered_expanded

    async def autocomplete_mining_materials(self, query: str, limit: int = 25) -> list[str]:
        materials = await self._get_mining_materials()
        normalized_query = self._mining_material_alias(self._normalize(self._strip_code_suffix(query)))
        names = [self._display_name(row) for row in materials]

        if not normalized_query:
            return names[:limit]

        signature = self._mining_signature_value(query)
        if signature is not None:
            signature_names = await self._get_mining_material_names_for_signature(signature)
            signature_matches = [
                self._display_name(material)
                for material in materials
                if self._normalize(self._mining_material_base_name(material)) in signature_names
            ]
            if signature_matches:
                return signature_matches[:limit]

        starts = [
            self._display_name(row)
            for row in materials
            if self._normalize(self._mining_material_base_name(row)).startswith(normalized_query)
            or self._normalize(row.get("code")).startswith(normalized_query)
        ]
        contains = [
            self._display_name(row)
            for row in materials
            if (
                normalized_query in self._normalize(self._mining_material_base_name(row))
                or normalized_query in self._normalize(row.get("code"))
            )
            and self._display_name(row) not in starts
        ]
        return (starts + contains)[:limit]

    async def autocomplete_mining_locations(
        self,
        query: str,
        system: str | None = None,
        limit: int = 25,
    ) -> list[str]:
        del system
        names = await self._get_location_filter_names()
        normalized_query = self._normalize(query)
        if not normalized_query:
            return names[:limit]

        starts = [name for name in names if self._normalize(name).startswith(normalized_query)]
        contains = [
            name
            for name in names
            if normalized_query in self._normalize(name)
            and name not in starts
        ]
        return (starts + contains)[:limit]

    async def lookup_items(
        self,
        query: str | None = None,
        category: str | None = None,
        section: str | None = None,
        size: str | None = None,
        limit: int = 25,
        page: int = 1,
    ) -> list[ItemLocatorResult]:
        items = await self._get_buyable_items()
        filtered = self._filter_items(items, query, category, section, size)
        start = max(0, page - 1) * limit
        return [self._item_result(row, []) for row in filtered[start : start + limit]]

    async def lookup_item_by_id(self, item_id: int) -> ItemLocatorResult | None:
        items = await self._get_buyable_items()
        item = next((row for row in items if self._int_or_none(row.get("id")) == item_id), None)
        if item is None:
            return None

        prices = await self._fetch_item_prices(item_id)
        purchases = [
            self._item_purchase_location(row)
            for row in prices
            if self._positive(row.get("price_buy"))
        ]
        purchases.sort(key=lambda purchase: (float(purchase.price), purchase.terminal_name.lower()))
        return self._item_result(item, purchases)

    async def autocomplete_items(self, query: str, limit: int = 25) -> list[str]:
        items = await self._get_buyable_items()
        normalized_query = self._normalize(query)
        names = [str(row.get("name")) for row in items if row.get("name")]
        if not normalized_query:
            return names[:limit]

        query_aliases = self._item_query_aliases(normalized_query)
        starts = [name for name in names if any(self._normalize(name).startswith(alias) for alias in query_aliases)]
        contains = [
            name
            for name in names
            if any(alias in self._normalize(name) for alias in query_aliases) and name not in starts
        ]
        return (starts + contains)[:limit]

    async def autocomplete_item_filter(self, filter_name: str, query: str, limit: int = 25) -> list[str]:
        items = await self._get_buyable_items()
        key_map = {"category": "category", "section": "section", "size": "size"}
        key = key_map.get(filter_name)
        if key is None:
            return []

        values = []
        for row in items:
            value = self._string_or_none(row.get(key))
            if value and value not in values:
                values.append(value)
        values.sort(key=str.lower)

        normalized_query = self._normalize(query)
        if not normalized_query:
            return values[:limit]
        starts = [value for value in values if self._normalize(value).startswith(normalized_query)]
        contains = [
            value
            for value in values
            if normalized_query in self._normalize(value) and value not in starts
        ]
        return (starts + contains)[:limit]

    async def lookup_trade_routes(
        self,
        ship: str,
        cargo_capacity_scu: int | float,
        starting_point: str,
        investment: int | float,
        max_stops: int = 5,
        stay_system: str | None = None,
    ) -> TradeRouteResult | None:
        if cargo_capacity_scu <= 0 or investment <= 0:
            return None

        prices = await self._fetch_all_prices()
        terminals_by_id = await self._fetch_terminals_by_id()
        enriched_prices = self._enrich_price_rows(prices, terminals_by_id)
        normalized_start = self._normalize(self._trade_location_value(starting_point))
        start_keys = self._trade_start_keys(enriched_prices, normalized_start)
        legs = self._calculate_trade_route_legs(
            enriched_prices,
            float(cargo_capacity_scu),
            float(investment),
            max_stops,
            starting_point,
            stay_system,
        )
        return TradeRouteResult(
            ship=ship,
            cargo_capacity_scu=cargo_capacity_scu,
            investment=investment,
            legs=legs,
            source_name=self.name,
            requires_empty_return_to_start=bool(legs)
            and self._terminal_key(legs[-1].sell_terminal) not in start_keys,
        )

    async def autocomplete_trade_locations(self, query: str, limit: int = 25) -> list[str]:
        prices = await self._fetch_all_prices()
        terminals_by_id = await self._fetch_terminals_by_id()
        enriched_prices = self._enrich_price_rows(prices, terminals_by_id)
        normalized_query = self._normalize(query)
        display_by_terminal: dict[str, str] = {}

        for row in enriched_prices:
            if not self._positive(row.get("price_sell_avg") or row.get("price_sell")):
                continue
            if not self._positive(row.get("status_sell")):
                continue
            terminal_name = self._string_or_none(row.get("terminal_name"))
            if not terminal_name:
                continue
            key = self._terminal_key(terminal_name)
            display_by_terminal.setdefault(key, self._trade_location_display(row))

        displays = sorted(display_by_terminal.values(), key=str.lower)
        if not normalized_query:
            return displays[:limit]

        starts = [
            display
            for display in displays
            if self._normalize(display).startswith(normalized_query)
            or self._normalize(self._trade_location_value(display)).startswith(normalized_query)
        ]
        contains = [
            display
            for display in displays
            if normalized_query in self._normalize(display)
            and display not in starts
        ]
        return (starts + contains)[:limit]

    async def _find_commodity(self, query: str) -> dict | None:
        normalized_query = self._normalize(self._strip_code_suffix(query))
        if not normalized_query:
            return None

        commodities = await self._get_commodities()
        for commodity in commodities:
            if self._normalize(commodity.get("name")) == normalized_query:
                return commodity
        for commodity in commodities:
            if self._normalize(commodity.get("code")) == normalized_query:
                return commodity
        for commodity in commodities:
            if normalized_query in self._normalize(commodity.get("name")):
                return commodity
        for commodity in commodities:
            if normalized_query in self._normalize(commodity.get("code")):
                return commodity
        return None

    async def _get_commodities(self) -> list[dict]:
        if self._commodities is not None:
            return self._commodities

        cached = await self._cache.get("uex:commodities:v1")
        if isinstance(cached, list):
            self._commodities = [row for row in cached if isinstance(row, dict)]
            return self._commodities

        payload = await self._fetch_json(f"{self.base_url}/commodities")
        rows = payload.get("data") if isinstance(payload, dict) else []
        self._commodities = [row for row in rows if isinstance(row, dict)]
        self._commodities.sort(key=lambda row: str(row.get("name", "")).lower())
        await self._cache.set("uex:commodities:v1", self._commodities, 86400)
        return self._commodities

    async def _get_mining_materials(self) -> list[dict]:
        commodities = await self._get_commodities()
        materials = [row for row in commodities if self._is_mining_material(row)]
        return sorted(
            materials,
            key=lambda row: (self._mining_material_base_name(row).lower(), self._mining_material_priority(row)),
        )

    async def _find_mining_material(self, query: str) -> dict | None:
        normalized_query = self._mining_material_alias(self._normalize(self._strip_code_suffix(query).replace("(ore)", "")))
        if not normalized_query:
            return None

        signature = self._mining_signature_value(query)
        if signature is not None:
            match = await self._find_mining_material_by_signature(signature)
            if match is not None:
                return match

        materials = await self._get_mining_materials()
        for material in materials:
            if self._normalize(self._mining_material_base_name(material)) == normalized_query:
                return material
        for material in materials:
            if self._normalize(material.get("code")) == normalized_query:
                return material
        for material in materials:
            if normalized_query in self._normalize(self._mining_material_base_name(material)):
                return material
        for material in materials:
            if normalized_query in self._normalize(material.get("code")):
                return material
        return None

    async def _find_mining_material_by_signature(self, signature: int) -> dict | None:
        signature_names = await self._get_mining_material_names_for_signature(signature)
        if not signature_names:
            return None

        materials = await self._get_mining_materials()
        for material in materials:
            if self._normalize(self._mining_material_base_name(material)) in signature_names:
                return material
        return None

    async def _get_mining_material_names_for_signature(self, signature: int) -> set[str]:
        signatures = await self._get_mining_signature_map()
        return {
            material
            for material, values in signatures.items()
            if any(self._mining_signature_matches_cluster(signature, base_signature) for base_signature in values)
        }

    def _mining_signature_matches_cluster(self, signature: int, base_signature: int) -> bool:
        if signature == base_signature:
            return True
        return signature % base_signature == 0 and 1 <= signature // base_signature <= 6

    async def _get_location_filter_names(self) -> list[str]:
        if self._location_filter_names is not None:
            return self._location_filter_names

        cached = await self._cache.get("uex:mining-location-filters:v1")
        if isinstance(cached, list) and all(isinstance(name, str) for name in cached):
            self._location_filter_names = cached
            return self._location_filter_names

        names: set[str] = set()
        for endpoint in ["planets", "moons", "orbits", "poi"]:
            payload = await self._fetch_json(f"{self.base_url}/{endpoint}")
            rows = payload.get("data") if isinstance(payload, dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = self._string_or_none(row.get("name") or row.get("nickname"))
                if name:
                    names.add(name)

        self._location_filter_names = sorted(names, key=str.lower)
        await self._cache.set("uex:mining-location-filters:v1", self._location_filter_names, 86400)
        return self._location_filter_names

    async def _fetch_prices(self, commodity_name: str) -> list[dict]:
        url = f"{self.base_url}/commodities_prices?commodity_name={quote(commodity_name)}"
        payload = await self._fetch_json(url)
        rows = payload.get("data") if isinstance(payload, dict) else []
        return [row for row in rows if isinstance(row, dict)]

    async def _fetch_all_prices(self) -> list[dict]:
        if self._all_prices is not None:
            return self._all_prices

        cached = await self._cache.get("uex:commodities-prices-all:v1")
        if isinstance(cached, list):
            self._all_prices = [row for row in cached if isinstance(row, dict)]
            return self._all_prices

        payload = await self._fetch_json(f"{self.base_url}/commodities_prices_all")
        rows = payload.get("data") if isinstance(payload, dict) else []
        self._all_prices = [row for row in rows if isinstance(row, dict)]
        await self._cache.set(
            "uex:commodities-prices-all:v1",
            self._all_prices,
            self._settings.cache_ttl_seconds,
        )
        return self._all_prices

    async def _get_item_categories(self) -> list[dict]:
        if self._item_categories is not None:
            return self._item_categories

        cached = await self._cache.get("uex:item-categories:v1")
        if isinstance(cached, list):
            self._item_categories = [row for row in cached if isinstance(row, dict)]
            return self._item_categories

        payload = await self._fetch_json(f"{self.base_url}/categories?type=item")
        rows = payload.get("data") if isinstance(payload, dict) else []
        self._item_categories = [row for row in rows if isinstance(row, dict)]
        await self._cache.set("uex:item-categories:v1", self._item_categories, 86400)
        return self._item_categories

    async def _fetch_items_by_category(self, category_id: int) -> list[dict]:
        if category_id in self._items_by_category:
            return self._items_by_category[category_id]

        cache_key = f"uex:items:category:{category_id}:v1"
        cached = await self._cache.get(cache_key)
        if isinstance(cached, list):
            self._items_by_category[category_id] = [row for row in cached if isinstance(row, dict)]
            return self._items_by_category[category_id]

        payload = await self._fetch_json(f"{self.base_url}/items?id_category={category_id}")
        rows = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            rows = []
        self._items_by_category[category_id] = [row for row in rows if isinstance(row, dict)]
        await self._cache.set(cache_key, self._items_by_category[category_id], 86400)
        return self._items_by_category[category_id]

    async def _fetch_all_item_prices(self) -> list[dict]:
        if self._all_item_prices is not None:
            return self._all_item_prices

        cached = await self._cache.get("uex:items-prices-all:v1")
        if isinstance(cached, list):
            self._all_item_prices = [row for row in cached if isinstance(row, dict)]
            return self._all_item_prices

        payload = await self._fetch_json(f"{self.base_url}/items_prices_all")
        rows = payload.get("data") if isinstance(payload, dict) else []
        self._all_item_prices = [row for row in rows if isinstance(row, dict)]
        await self._cache.set("uex:items-prices-all:v1", self._all_item_prices, self._settings.cache_ttl_seconds)
        return self._all_item_prices

    async def _fetch_item_prices(self, item_id: int) -> list[dict]:
        cache_key = f"uex:items-prices:item:{item_id}:v1"
        cached = await self._cache.get(cache_key)
        if isinstance(cached, list):
            return [row for row in cached if isinstance(row, dict)]

        payload = await self._fetch_json(f"{self.base_url}/items_prices?id_item={item_id}")
        rows = payload.get("data") if isinstance(payload, dict) else []
        prices = [row for row in rows if isinstance(row, dict)]
        await self._cache.set(cache_key, prices, self._settings.cache_ttl_seconds)
        return prices

    async def _get_buyable_items(self) -> list[dict]:
        if self._buyable_items is not None:
            return self._buyable_items

        categories = [
            row
            for row in await self._get_item_categories()
            if self._item_category_is_supported(row)
        ]
        prices = await self._fetch_all_item_prices()
        buyable_ids = {
            self._int_or_none(row.get("id_item"))
            for row in prices
            if self._positive(row.get("price_buy"))
        }
        buyable_ids.discard(None)

        items = []
        for category in categories:
            category_id = self._int_or_none(category.get("id"))
            if category_id is None:
                continue
            for item in await self._fetch_items_by_category(category_id):
                if self._int_or_none(item.get("id")) in buyable_ids:
                    items.append(item)

        unique: dict[int, dict] = {}
        for item in items:
            item_id = self._int_or_none(item.get("id"))
            if item_id is not None:
                unique[item_id] = item
        self._buyable_items = sorted(unique.values(), key=lambda row: str(row.get("name", "")).lower())
        return self._buyable_items

    async def _fetch_terminals_by_id(self) -> dict[str, dict]:
        if self._terminals_by_id is not None:
            return self._terminals_by_id

        cached = await self._cache.get("uex:commodity-terminals:v1")
        if isinstance(cached, dict):
            self._terminals_by_id = {
                str(terminal_id): terminal
                for terminal_id, terminal in cached.items()
                if isinstance(terminal, dict)
            }
            return self._terminals_by_id

        payload = await self._fetch_json(f"{self.base_url}/terminals?type=commodity")
        rows = payload.get("data") if isinstance(payload, dict) else []
        self._terminals_by_id = {
            str(row.get("id")): row
            for row in rows
            if isinstance(row, dict) and row.get("id") is not None
        }
        await self._cache.set("uex:commodity-terminals:v1", self._terminals_by_id, 12 * 60 * 60)
        return self._terminals_by_id

    async def _fetch_json(self, url: str) -> dict | None:
        try:
            async with self._session.get(url, headers={"Accept": "application/json"}) as response:
                response.raise_for_status()
                payload = await response.json()
                return payload if isinstance(payload, dict) else None
        except (aiohttp.ClientError, ValueError):
            return None

    async def _fetch_text(self, url: str) -> str | None:
        try:
            async with self._session.get(url, headers={"Accept": "text/html"}) as response:
                response.raise_for_status()
                return await response.text()
        except aiohttp.ClientError:
            return None

    def _parse_commodity(
        self,
        commodity: dict,
        prices: list[dict],
        system: str | None = None,
        purchase_system: str | None = None,
        sell_system: str | None = None,
    ) -> CommodityResult:
        normalized_system = self._normalize(system)
        normalized_purchase_system = self._normalize(purchase_system) or normalized_system
        normalized_sell_system = self._normalize(sell_system) or normalized_system
        purchase_prices = self._filter_prices_by_system(prices, normalized_purchase_system)
        sell_prices = self._filter_prices_by_system(prices, normalized_sell_system)

        buy_from = [
            self._market(row, "price_buy_avg", "scu_buy_avg")
            for row in purchase_prices
            if self._positive(row.get("price_buy_avg") or row.get("price_buy"))
            and self._positive(row.get("status_buy"))
        ]
        sell_to = [
            self._market(row, "price_sell_avg", "scu_sell_stock_avg")
            for row in sell_prices
            if self._positive(row.get("price_sell_avg") or row.get("price_sell"))
            and self._positive(row.get("status_sell"))
        ]

        return CommodityResult(
            name=str(commodity.get("name") or "Unknown commodity"),
            code=self._string_or_none(commodity.get("code")),
            kind=self._string_or_none(commodity.get("kind")),
            average_buy_price=commodity.get("price_buy") or None,
            average_sell_price=commodity.get("price_sell") or None,
            is_illegal=bool(commodity.get("is_illegal")),
            is_mineral=bool(commodity.get("is_mineral")),
            is_raw=bool(commodity.get("is_raw")),
            is_refined=bool(commodity.get("is_refined")),
            is_harvestable=bool(commodity.get("is_harvestable")),
            wiki_url=self._string_or_none(commodity.get("wiki")),
            buy_from=sorted(buy_from, key=lambda market: float(market.price))[:3],
            sell_to=sorted(sell_to, key=lambda market: float(market.price), reverse=True)[:3],
            source_name=self.name,
        )

    async def _fetch_mining_location_result(
        self,
        commodity: dict,
        system_code: str | None,
    ) -> MiningLocationResult | None:
        slug = self._mining_material_slug(commodity)
        url = f"https://uexcorp.space/mining/locations/commodity/{slug}/"
        if system_code:
            url = f"{url}system/{system_code}/"

        cache_key = f"uex:mining-location:v1:{slug}:system-{system_code or 'all'}"
        cached = await self._cache.get(cache_key)
        if cached:
            return self._mining_result_from_cache(cached)

        html = await self._fetch_text(url)
        if not html:
            return None

        result = self._parse_mining_location_result(commodity, html, url)
        await self._cache.set(cache_key, self._mining_result_to_cache(result), self._settings.cache_ttl_seconds)
        return result

    async def _with_mining_signatures(
        self,
        result: MiningLocationResult,
        commodity: dict,
    ) -> MiningLocationResult:
        signatures = await self._get_mining_signatures(self._mining_material_base_name(commodity))
        return MiningLocationResult(
            material_name=result.material_name,
            code=result.code,
            kind=result.kind,
            refined_sell_price=result.refined_sell_price,
            raw_sell_price=result.raw_sell_price,
            is_harvestable=result.is_harvestable,
            is_volatile_qt=result.is_volatile_qt,
            is_volatile_time=result.is_volatile_time,
            is_explosive=result.is_explosive,
            systems=result.systems,
            lagrange_points=result.lagrange_points,
            planets=result.planets,
            moons=result.moons,
            points_of_interest=result.points_of_interest,
            source_url=result.source_url,
            source_name=result.source_name,
            location_basis=result.location_basis,
            rock_signatures=signatures,
            location_groups=result.location_groups or [],
        )

    async def _with_mining_location_groups(
        self,
        result: MiningLocationResult,
        commodity: dict,
        system_code: str | None,
    ) -> MiningLocationResult:
        if system_code:
            system = self._mining_system_name(system_code)
            groups = [
                self._mining_system_group(result, system)
            ] if self._is_mining_system_scoped_result(result, system) else []
        else:
            groups = []
            for system in sorted(result.systems, key=self._mining_system_sort_key):
                code = self._mining_system_code(system)
                if code is None:
                    groups.append(self._mining_system_group(result, system))
                    continue
                system_result = await self._fetch_mining_location_result(commodity, code)
                if system_result is None:
                    continue
                if not self._is_mining_system_scoped_result(system_result, system):
                    continue
                groups.append(self._mining_system_group(system_result, system))

        return MiningLocationResult(
            material_name=result.material_name,
            code=result.code,
            kind=result.kind,
            refined_sell_price=result.refined_sell_price,
            raw_sell_price=result.raw_sell_price,
            is_harvestable=result.is_harvestable,
            is_volatile_qt=result.is_volatile_qt,
            is_volatile_time=result.is_volatile_time,
            is_explosive=result.is_explosive,
            systems=result.systems,
            lagrange_points=result.lagrange_points,
            planets=result.planets,
            moons=result.moons,
            points_of_interest=result.points_of_interest,
            source_url=result.source_url,
            source_name=result.source_name,
            location_basis=result.location_basis,
            rock_signatures=result.rock_signatures or [],
            location_groups=groups,
        )

    async def _get_mining_signatures(self, material_name: str) -> list[int]:
        signatures = await self._get_mining_signature_map()
        return signatures.get(self._normalize(material_name), [])

    async def _get_mining_signature_map(self) -> dict[str, list[int]]:
        if self._mining_signatures is not None:
            return self._mining_signatures

        cached = await self._cache.get("star-head:mining-signatures:v1")
        if isinstance(cached, dict):
            self._mining_signatures = {
                str(key): sorted(
                    {
                        int(value)
                        for value in values
                        if self._int_or_none(value) is not None
                    }
                )
                for key, values in cached.items()
                if isinstance(values, list)
            }
            return self._mining_signatures

        html = await self._fetch_text("https://star-head.de/database/mining/locations/")
        if not html:
            self._mining_signatures = {}
            return self._mining_signatures

        app_match = re.search(r'href="([^"]*/entry/app\.[^"]+\.js)"', html)
        if not app_match:
            self._mining_signatures = {}
            return self._mining_signatures

        app_url = app_match.group(1)
        if app_url.startswith("/"):
            app_url = f"https://star-head.de{app_url}"

        app_script = await self._fetch_text(app_url)
        if not app_script:
            self._mining_signatures = {}
            return self._mining_signatures

        node_match = re.search(r"_app/immutable/nodes/14\.[^\"']+\.js", app_script)
        if not node_match:
            self._mining_signatures = {}
            return self._mining_signatures

        node_script = await self._fetch_text(f"https://star-head.de/{node_match.group(0)}")
        self._mining_signatures = self._parse_star_head_signatures(node_script or "")
        await self._cache.set("star-head:mining-signatures:v1", self._mining_signatures, 24 * 60 * 60)
        return self._mining_signatures

    def _parse_star_head_signatures(self, script: str) -> dict[str, list[int]]:
        signatures: dict[str, set[int]] = {}
        for match in re.finditer(r"\{signature:(?P<signature>\d+),materials:\[(?P<materials>[^\]]+)\]\}", script):
            signature = int(match.group("signature"))
            materials = re.findall(r'"([^"]+)"', match.group("materials"))
            for material in materials:
                signatures.setdefault(self._normalize(material), set()).add(signature)

        return {
            material: sorted(values)
            for material, values in signatures.items()
        }

    async def _expand_mining_result_from_associated_deposits(
        self,
        result: MiningLocationResult,
        commodity: dict,
        system_code: str | None,
    ) -> MiningLocationResult:
        associated_names = await self._get_associated_mining_material_names(self._mining_material_base_name(commodity))
        if not associated_names:
            return result

        merged = result
        used_names: list[str] = []
        for name in associated_names[:8]:
            associated_commodity = await self._find_mining_material(name)
            if associated_commodity is None:
                continue
            associated_result = await self._fetch_mining_location_result(associated_commodity, system_code)
            if associated_result is None or not self._has_mining_locations(associated_result):
                continue
            merged = self._merge_mining_location_results(merged, associated_result)
            used_names.append(associated_result.material_name)

        if not used_names:
            return result

        basis = "Direct UEX locations plus shared deposit composition"
        return MiningLocationResult(
            material_name=merged.material_name,
            code=merged.code,
            kind=merged.kind,
            refined_sell_price=merged.refined_sell_price,
            raw_sell_price=merged.raw_sell_price,
            is_harvestable=merged.is_harvestable,
            is_volatile_qt=merged.is_volatile_qt,
            is_volatile_time=merged.is_volatile_time,
            is_explosive=merged.is_explosive,
            systems=merged.systems,
            lagrange_points=merged.lagrange_points,
            planets=merged.planets,
            moons=merged.moons,
            points_of_interest=merged.points_of_interest,
            source_url=merged.source_url,
            source_name="UEX + Star Citizen Mining Mom",
            location_basis=basis,
            rock_signatures=merged.rock_signatures or [],
            location_groups=merged.location_groups or [],
        )

    async def _get_associated_mining_material_names(self, material_name: str) -> list[str]:
        associations = await self._get_mining_associations()
        return associations.get(self._normalize(material_name), [])

    async def _get_mining_associations(self) -> dict[str, list[str]]:
        if self._mining_associations is not None:
            return self._mining_associations

        cached = await self._cache.get("mining-mom:deposit-associations:v1")
        if isinstance(cached, dict):
            self._mining_associations = {
                str(key): [str(value) for value in values if value]
                for key, values in cached.items()
                if isinstance(values, list)
            }
            return self._mining_associations

        html = await self._fetch_text("https://www.scminingmom.com/mining/locations/deposits")
        if not html:
            self._mining_associations = {}
            return self._mining_associations

        asset_match = re.search(r'<script[^>]+src="([^"]*index-[^"]+\.js)"', html)
        if not asset_match:
            self._mining_associations = {}
            return self._mining_associations

        asset_url = asset_match.group(1)
        if asset_url.startswith("/"):
            asset_url = f"https://www.scminingmom.com{asset_url}"

        script = await self._fetch_text(asset_url)
        self._mining_associations = self._parse_mining_mom_associations(script or "")
        await self._cache.set("mining-mom:deposit-associations:v1", self._mining_associations, 24 * 60 * 60)
        return self._mining_associations

    def _parse_mining_mom_associations(self, script: str) -> dict[str, list[str]]:
        element_names: dict[str, str] = {}
        for match in re.finditer(
            r'"(?P<key>[0-9a-f-]{36})":\{id:"(?P<id>[0-9a-f-]{36})".*?mineableResource:"(?P<name>[^"]+)".*?\}',
            script,
            re.DOTALL,
        ):
            element_names[match.group("id")] = match.group("name")

        associations: dict[str, set[str]] = {}
        for match in re.finditer(r"MineableCompositionPart:\[(?P<parts>.*?)\]\},depositName:", script, re.DOTALL):
            names = {
                element_names[element_id]
                for element_id in re.findall(r'mineableElement:"([0-9a-f-]{36})"', match.group("parts"))
                if element_id in element_names
            }
            if len(names) < 2:
                continue
            for name in names:
                normalized_name = self._normalize(name)
                associations.setdefault(normalized_name, set()).update(
                    other for other in names if self._normalize(other) != normalized_name
                )

        return {
            name: sorted(values, key=str.lower)
            for name, values in associations.items()
        }

    def _market(self, row: dict, price_key: str, demand_key: str) -> CommodityMarket:
        return CommodityMarket(
            terminal_name=str(row.get("terminal_name") or "Unknown terminal"),
            system=self._string_or_none(row.get("star_system_name")),
            planet=self._string_or_none(row.get("planet_name") or row.get("orbit_name")),
            location=self._location(row),
            price=row.get(price_key) or row.get(price_key.replace("_avg", "")),
            demand=row.get(demand_key) or row.get(demand_key.replace("_avg", "")) or None,
            game_version=self._string_or_none(row.get("game_version")),
        )

    def _parse_mining_location_result(self, commodity: dict, html: str, source_url: str) -> MiningLocationResult:
        lines = [
            line.strip()
            for line in BeautifulSoup(html, "html.parser").get_text("\n", strip=True).split("\n")
            if line.strip()
        ]
        sections = self._parse_mining_sections(lines)
        return MiningLocationResult(
            material_name=self._mining_material_base_name(commodity),
            code=self._string_or_none(commodity.get("code")),
            kind=self._string_or_none(commodity.get("kind")),
            refined_sell_price=None,
            raw_sell_price=commodity.get("price_sell") or None,
            is_harvestable=bool(commodity.get("is_harvestable")),
            is_volatile_qt=bool(commodity.get("is_volatile_qt")),
            is_volatile_time=bool(commodity.get("is_volatile_time")),
            is_explosive=bool(commodity.get("is_explosive")),
            systems=sections["Star Systems"],
            lagrange_points=sections["Lagrange Points"],
            planets=sections["Planets"],
            moons=sections["Moons"],
            points_of_interest=sections["Points of Interest"],
            source_url=source_url,
            source_name=self.name,
            rock_signatures=[],
            location_groups=[],
        )

    async def _with_mining_sell_prices(
        self,
        result: MiningLocationResult,
        commodity: dict,
    ) -> MiningLocationResult:
        raw_sell_price = commodity.get("price_sell") or result.raw_sell_price
        refined_sell_price = None

        base_name = self._normalize(self._mining_material_base_name(commodity))
        if commodity.get("is_refinable") or str(commodity.get("name") or "").endswith(("(Ore)", "(Raw)")):
            commodities = await self._get_commodities()
            for row in commodities:
                if self._normalize(row.get("name")) != base_name:
                    continue
                if not self._positive(row.get("price_sell")):
                    continue
                refined_sell_price = row.get("price_sell")
                break

        return MiningLocationResult(
            material_name=result.material_name,
            code=result.code,
            kind=result.kind,
            refined_sell_price=refined_sell_price,
            raw_sell_price=raw_sell_price,
            is_harvestable=result.is_harvestable,
            is_volatile_qt=result.is_volatile_qt,
            is_volatile_time=result.is_volatile_time,
            is_explosive=result.is_explosive,
            systems=result.systems,
            lagrange_points=result.lagrange_points,
            planets=result.planets,
            moons=result.moons,
            points_of_interest=result.points_of_interest,
            source_url=result.source_url,
            source_name=result.source_name,
            location_basis=result.location_basis,
            rock_signatures=result.rock_signatures,
            location_groups=result.location_groups,
        )

    def _parse_mining_sections(self, lines: list[str]) -> dict[str, list[str]]:
        section_names = ["Star Systems", "Lagrange Points", "Planets", "Moons", "Points of Interest"]
        sections: dict[str, list[str]] = {name: [] for name in section_names}
        active_section: str | None = None
        seen_routes = False

        for index, line in enumerate(lines):
            if line == "Routes" and index + 1 < len(lines) and lines[index + 1] == "Star Systems":
                seen_routes = True
                active_section = None
                continue
            if not seen_routes:
                continue
            if line in section_names:
                active_section = line
                continue
            if line.startswith("* Location data") or line in {"Pricing", "Components", "About"}:
                active_section = None
                continue
            if active_section is None or line in {"—", "/ SCU"}:
                continue
            if line not in sections[active_section]:
                sections[active_section].append(line)

        return sections

    def _filter_mining_result(self, result: MiningLocationResult, planet: str | None) -> MiningLocationResult:
        normalized_planet = self._normalize(planet)
        if not normalized_planet:
            return result

        return MiningLocationResult(
            material_name=result.material_name,
            code=result.code,
            kind=result.kind,
            refined_sell_price=result.refined_sell_price,
            raw_sell_price=result.raw_sell_price,
            is_harvestable=result.is_harvestable,
            is_volatile_qt=result.is_volatile_qt,
            is_volatile_time=result.is_volatile_time,
            is_explosive=result.is_explosive,
            systems=result.systems,
            lagrange_points=self._filter_location_names(result.lagrange_points, normalized_planet),
            planets=self._filter_location_names(result.planets, normalized_planet),
            moons=self._filter_location_names(result.moons, normalized_planet),
            points_of_interest=self._filter_location_names(result.points_of_interest, normalized_planet),
            source_url=result.source_url,
            source_name=result.source_name,
            location_basis=result.location_basis,
            rock_signatures=result.rock_signatures or [],
            location_groups=[
                MiningSystemLocations(
                    system=group.system,
                    lagrange_points=self._filter_location_names(group.lagrange_points, normalized_planet),
                    planets=self._filter_location_names(group.planets, normalized_planet),
                    moons=self._filter_location_names(group.moons, normalized_planet),
                    points_of_interest=self._filter_location_names(group.points_of_interest, normalized_planet),
                )
                for group in result.location_groups or []
            ],
        )

    def _has_mining_locations(self, result: MiningLocationResult) -> bool:
        return any(
            [
                result.systems,
                result.lagrange_points,
                result.planets,
                result.moons,
                result.points_of_interest,
            ]
        )

    def _merge_mining_location_results(
        self,
        primary: MiningLocationResult,
        secondary: MiningLocationResult,
    ) -> MiningLocationResult:
        return MiningLocationResult(
            material_name=primary.material_name,
            code=primary.code,
            kind=primary.kind,
            refined_sell_price=primary.refined_sell_price,
            raw_sell_price=primary.raw_sell_price,
            is_harvestable=primary.is_harvestable,
            is_volatile_qt=primary.is_volatile_qt,
            is_volatile_time=primary.is_volatile_time,
            is_explosive=primary.is_explosive,
            systems=self._merge_location_names(primary.systems, secondary.systems),
            lagrange_points=self._merge_location_names(primary.lagrange_points, secondary.lagrange_points),
            planets=self._merge_location_names(primary.planets, secondary.planets),
            moons=self._merge_location_names(primary.moons, secondary.moons),
            points_of_interest=self._merge_location_names(primary.points_of_interest, secondary.points_of_interest),
            source_url=primary.source_url,
            source_name=primary.source_name,
            location_basis=primary.location_basis,
            rock_signatures=primary.rock_signatures or [],
            location_groups=primary.location_groups or [],
        )

    def _merge_location_names(self, first: list[str], second: list[str]) -> list[str]:
        names: dict[str, str] = {}
        for name in [*first, *second]:
            names.setdefault(self._normalize(name), name)
        return sorted(names.values(), key=str.lower)

    def _mining_system_group(self, result: MiningLocationResult, system: str) -> MiningSystemLocations:
        return MiningSystemLocations(
            system=system,
            lagrange_points=result.lagrange_points,
            planets=result.planets,
            moons=result.moons,
            points_of_interest=result.points_of_interest,
        )

    def _is_mining_system_scoped_result(self, result: MiningLocationResult, system: str) -> bool:
        normalized_system = self._normalize(system)
        normalized_systems = {
            self._normalize(candidate)
            for candidate in result.systems
        }
        return normalized_systems == {normalized_system}

    def _mining_system_name(self, system_code: str) -> str:
        return {
            "ST": "Stanton",
            "PY": "Pyro",
            "NY": "Nyx",
        }.get(system_code, system_code)

    def _mining_system_sort_key(self, system: str) -> tuple[int, str]:
        order = {
            "stanton": 0,
            "pyro": 1,
            "nyx": 2,
        }
        normalized = self._normalize(system)
        return order.get(normalized, 99), normalized

    def _filter_location_names(self, names: list[str], normalized_filter: str) -> list[str]:
        return [name for name in names if normalized_filter in self._normalize(name)]

    def _is_mining_material(self, row: dict) -> bool:
        name = str(row.get("name") or "")
        return bool(
            row.get("is_available")
            and row.get("is_visible")
            and (
                row.get("is_raw")
                or name.endswith("(Ore)")
                or name.endswith("(Raw)")
                or (row.get("is_harvestable") and row.get("is_mineral"))
            )
            and not row.get("is_inert")
        )

    def _mining_material_base_name(self, row: dict) -> str:
        name = str(row.get("name") or "Unknown material")
        return name.replace(" (Ore)", "").replace(" (Raw)", "").strip()

    def _mining_material_slug(self, row: dict) -> str:
        name = self._mining_material_base_name(row).lower()
        slug = "".join(character if character.isalnum() else "-" for character in name)
        slug = "-".join(part for part in slug.split("-") if part)
        row_name = str(row.get("name") or "")
        if row_name.endswith("(Raw)"):
            return f"{slug}-raw"
        if row.get("is_refinable") or row_name.endswith("(Ore)"):
            return f"{slug}-ore"
        return slug

    def _mining_material_priority(self, row: dict) -> int:
        name = str(row.get("name") or "")
        if name.endswith("(Ore)") or name.endswith("(Raw)") or row.get("is_raw"):
            return 0
        return 1

    def _mining_material_alias(self, normalized_query: str) -> str:
        return {
            "quantanium": "quantainium",
            "quantanium raw": "quantainium",
        }.get(normalized_query, normalized_query)

    def _mining_signature_value(self, value: object) -> int | None:
        text = str(value or "").replace(",", "").strip()
        return int(text) if text.isdigit() else None

    def _mining_system_code(self, system: str | None) -> str | None:
        normalized_system = self._normalize(system)
        if not normalized_system:
            return None
        return {
            "stanton": "ST",
            "pyro": "PY",
            "nyx": "NY",
        }.get(normalized_system)

    def _item_category_is_supported(self, row: dict) -> bool:
        if not self._positive(row.get("is_game_related")):
            return False
        section = self._normalize(row.get("section"))
        name = self._normalize(row.get("name"))
        supported_sections = {
            "armor",
            "clothing",
            "personal weapons",
            "systems",
            "undersuits",
            "utility",
            "vehicle weapons",
            "avionics",
            "propulsion",
            "module",
        }
        supported_names = {
            "bombs",
            "bomb racks",
            "coolers",
            "flight blade",
            "guns",
            "helmets",
            "jump modules",
            "missile racks",
            "missiles",
            "personal weapons",
            "power plants",
            "quantum drives",
            "radar",
            "shield generators",
            "tractor beams",
            "turrets",
            "undersuits",
        }
        return section in supported_sections or name in supported_names

    def _filter_items(
        self,
        items: list[dict],
        query: str | None = None,
        category: str | None = None,
        section: str | None = None,
        size: str | None = None,
    ) -> list[dict]:
        normalized_queries = self._item_query_aliases(self._normalize(query))
        normalized_category = self._normalize(category)
        normalized_section = self._normalize(section)
        normalized_size = self._normalize(size)

        filtered = []
        for item in items:
            if normalized_queries and not any(
                query in self._normalize(item.get("name"))
                or query in self._normalize(item.get("category"))
                or query in self._normalize(item.get("section"))
                or query in self._normalize(item.get("company_name"))
                for query in normalized_queries
            ):
                continue
            if normalized_category and self._normalize(item.get("category")) != normalized_category:
                continue
            if normalized_section and self._normalize(item.get("section")) != normalized_section:
                continue
            if normalized_size and self._normalize(item.get("size")) != normalized_size:
                continue
            filtered.append(item)
        return filtered

    def _item_query_aliases(self, normalized_query: str) -> list[str]:
        if not normalized_query:
            return []

        aliases = {
            "medpen": ["medpen", "med pen", "paramed", "medical"],
            "med pen": ["med pen", "medpen", "paramed", "medical"],
        }
        return aliases.get(normalized_query, [normalized_query])

    def _item_result(self, row: dict, purchases: list[ItemPurchaseLocation]) -> ItemLocatorResult:
        item_id = self._int_or_none(row.get("id")) or 0
        slug = self._string_or_none(row.get("slug")) or str(item_id)
        return ItemLocatorResult(
            id=item_id,
            name=str(row.get("name") or "Unknown item"),
            section=self._string_or_none(row.get("section")),
            category=self._string_or_none(row.get("category")),
            company_name=self._string_or_none(row.get("company_name")),
            size=self._string_or_none(row.get("size")),
            wiki_url=self._string_or_none(row.get("wiki")),
            source_url=f"https://uexcorp.space/items/info/{quote(slug)}",
            source_name=self.name,
            purchases=purchases,
        )

    def _item_purchase_location(self, row: dict) -> ItemPurchaseLocation:
        return ItemPurchaseLocation(
            terminal_name=str(row.get("terminal_name") or "Unknown terminal"),
            system=self._string_or_none(row.get("star_system_name")),
            planet=self._string_or_none(row.get("planet_name") or row.get("orbit_name") or row.get("moon_name")),
            location=self._location(row),
            price=row.get("price_buy"),
            game_version=self._string_or_none(row.get("game_version")),
        )

    def _enrich_price_rows(self, prices: list[dict], terminals_by_id: dict[str, dict]) -> list[dict]:
        enriched: list[dict] = []
        for row in prices:
            terminal_id = self._string_or_none(row.get("id_terminal") or row.get("terminal_id"))
            terminal = terminals_by_id.get(terminal_id or "")
            if terminal is None:
                enriched.append(row)
                continue

            merged = terminal.copy()
            merged.update(row)
            if not merged.get("terminal_name"):
                merged["terminal_name"] = terminal.get("displayname") or terminal.get("name")
            enriched.append(merged)
        return enriched

    def _calculate_trade_route_legs(
        self,
        prices: list[dict],
        cargo_capacity_scu: float,
        investment: float,
        max_stops: int,
        starting_point: str,
        stay_system: str | None = None,
    ) -> list[TradeRouteLeg]:
        normalized_start = self._normalize(self._trade_location_value(starting_point))
        normalized_stay_system = self._normalize(stay_system)
        start_keys = self._trade_start_keys(prices, normalized_start)
        rows_by_commodity: dict[str, list[dict]] = {}

        for row in prices:
            commodity = self._string_or_none(row.get("commodity_name") or row.get("commodity"))
            if not commodity:
                continue
            rows_by_commodity.setdefault(commodity, []).append(row)

        candidates: list[TradeRouteLeg] = []
        for commodity, rows in rows_by_commodity.items():
            purchase_rows = [
                row
                for row in rows
                if self._positive(row.get("price_sell_avg") or row.get("price_sell"))
                and self._positive(row.get("status_sell"))
                and self._matches_system(row, normalized_stay_system)
            ]
            sell_rows = [
                row
                for row in rows
                if self._positive(row.get("price_buy_avg") or row.get("price_buy"))
                and self._positive(row.get("status_buy"))
                and self._matches_system(row, normalized_stay_system)
            ]

            for purchase in purchase_rows:
                buy_price = self._number(purchase.get("price_sell_avg") or purchase.get("price_sell"))
                if buy_price is None or buy_price <= 0:
                    continue

                for sale in sell_rows:
                    if self._same_terminal(purchase, sale):
                        continue
                    sell_price = self._number(sale.get("price_buy_avg") or sale.get("price_buy"))
                    if sell_price is None:
                        continue

                    quantity_scu = min(
                        cargo_capacity_scu,
                        self._available_scu(purchase, "scu_sell_stock_avg", "scu_sell_stock"),
                        self._available_scu(sale, "scu_buy_avg", "scu_buy"),
                    )
                    if quantity_scu <= 0:
                        continue

                    investment_used = buy_price * quantity_scu
                    profit = (sell_price - buy_price) * quantity_scu
                    candidates.append(
                        TradeRouteLeg(
                            commodity_name=commodity,
                            buy_price=buy_price,
                            sell_price=sell_price,
                            quantity_scu=quantity_scu,
                            investment_used=investment_used,
                            profit=profit,
                            buy_system=self._string_or_none(purchase.get("star_system_name")),
                            buy_planet=self._string_or_none(purchase.get("planet_name") or purchase.get("orbit_name")),
                            buy_location=self._location(purchase),
                            buy_terminal=str(purchase.get("terminal_name") or "Unknown terminal"),
                            sell_system=self._string_or_none(sale.get("star_system_name")),
                            sell_planet=self._string_or_none(sale.get("planet_name") or sale.get("orbit_name")),
                            sell_location=self._location(sale),
                            sell_terminal=str(sale.get("terminal_name") or "Unknown terminal"),
                        )
                    )

        return self._best_circular_route(candidates, max_stops, start_keys, investment)

    def _best_circular_route(
        self,
        candidates: list[TradeRouteLeg],
        max_stops: int,
        start_keys: set[str],
        investment: float,
    ) -> list[TradeRouteLeg]:
        max_stops = max(2, max_stops)
        candidates.sort(key=lambda leg: float(leg.profit), reverse=True)

        best_by_pair: dict[tuple[str, str], TradeRouteLeg] = {}
        for leg in candidates:
            key = (self._terminal_key(leg.buy_terminal), self._terminal_key(leg.sell_terminal))
            current = best_by_pair.get(key)
            if current is None or float(leg.profit) > float(current.profit):
                best_by_pair[key] = leg

        outgoing: dict[str, list[TradeRouteLeg]] = {}
        for leg in best_by_pair.values():
            outgoing.setdefault(self._terminal_key(leg.buy_terminal), []).append(leg)

        for legs in outgoing.values():
            legs.sort(key=lambda leg: float(leg.profit), reverse=True)
            del legs[25:]

        best_route: list[TradeRouteLeg] = []
        best_profit = 0.0
        start_candidates = [
            leg
            for leg in sorted(best_by_pair.values(), key=lambda leg: float(leg.profit), reverse=True)
            if self._terminal_key(leg.buy_terminal) in start_keys
        ][:1000]

        def search(route: list[TradeRouteLeg], start_terminal: str, visited_terminals: set[str]) -> None:
            nonlocal best_route, best_profit

            current_terminal = self._terminal_key(route[-1].sell_terminal)
            if len(route) >= 2 and current_terminal == start_terminal:
                simulated_route = self._simulate_trade_route_wallet(route, investment)
                profit = self._route_profit(simulated_route)
                if profit > best_profit:
                    best_profit = profit
                    best_route = simulated_route
                return

            if len(route) >= max_stops:
                return

            used_edges = {
                (self._terminal_key(leg.buy_terminal), self._terminal_key(leg.sell_terminal), leg.commodity_name)
                for leg in route
            }
            for next_leg in outgoing.get(current_terminal, []):
                next_terminal = self._terminal_key(next_leg.sell_terminal)
                edge_key = (
                    self._terminal_key(next_leg.buy_terminal),
                    self._terminal_key(next_leg.sell_terminal),
                    next_leg.commodity_name,
                )
                if edge_key in used_edges:
                    continue
                if next_terminal in visited_terminals and next_terminal != start_terminal:
                    continue

                added_terminal = None
                if next_terminal != start_terminal:
                    visited_terminals.add(next_terminal)
                    added_terminal = next_terminal
                route.append(next_leg)
                search(route, start_terminal, visited_terminals)
                route.pop()
                if added_terminal is not None:
                    visited_terminals.remove(added_terminal)

        for start_leg in start_candidates:
            start_terminal = self._terminal_key(start_leg.buy_terminal)
            first_sell_terminal = self._terminal_key(start_leg.sell_terminal)
            visited = {start_terminal}
            if first_sell_terminal != start_terminal:
                visited.add(first_sell_terminal)
            search([start_leg], start_terminal, visited)

        if best_route:
            return best_route

        return self._best_route_with_empty_return(start_candidates, outgoing, max_stops, investment)

    def _best_route_with_empty_return(
        self,
        start_candidates: list[TradeRouteLeg],
        outgoing: dict[str, list[TradeRouteLeg]],
        max_stops: int,
        investment: float,
    ) -> list[TradeRouteLeg]:
        best_route: list[TradeRouteLeg] = []
        best_profit = 0.0

        def search(route: list[TradeRouteLeg], visited_terminals: set[str]) -> None:
            nonlocal best_route, best_profit

            simulated_route = self._simulate_trade_route_wallet(route, investment)
            profit = self._route_profit(simulated_route)
            if profit > best_profit:
                best_profit = profit
                best_route = simulated_route

            if len(route) >= max_stops:
                return

            used_edges = {
                (self._terminal_key(leg.buy_terminal), self._terminal_key(leg.sell_terminal), leg.commodity_name)
                for leg in route
            }
            current_terminal = self._terminal_key(route[-1].sell_terminal)
            for next_leg in outgoing.get(current_terminal, []):
                next_terminal = self._terminal_key(next_leg.sell_terminal)
                edge_key = (
                    self._terminal_key(next_leg.buy_terminal),
                    self._terminal_key(next_leg.sell_terminal),
                    next_leg.commodity_name,
                )
                if edge_key in used_edges or next_terminal in visited_terminals:
                    continue

                visited_terminals.add(next_terminal)
                route.append(next_leg)
                search(route, visited_terminals)
                route.pop()
                visited_terminals.remove(next_terminal)

        for start_leg in start_candidates:
            start_terminal = self._terminal_key(start_leg.buy_terminal)
            first_sell_terminal = self._terminal_key(start_leg.sell_terminal)
            visited = {start_terminal, first_sell_terminal}
            search([start_leg], visited)

        return best_route

    def _simulate_trade_route_wallet(
        self,
        route: list[TradeRouteLeg],
        starting_cash: float,
    ) -> list[TradeRouteLeg]:
        cash = starting_cash
        simulated_route: list[TradeRouteLeg] = []

        for leg in route:
            quantity_scu = min(float(leg.quantity_scu), cash / float(leg.buy_price))
            if quantity_scu <= 0:
                return []

            investment_used = float(leg.buy_price) * quantity_scu
            payout = float(leg.sell_price) * quantity_scu
            profit = payout - investment_used
            cash = cash - investment_used + payout
            simulated_route.append(
                TradeRouteLeg(
                    commodity_name=leg.commodity_name,
                    buy_price=leg.buy_price,
                    sell_price=leg.sell_price,
                    quantity_scu=quantity_scu,
                    investment_used=investment_used,
                    profit=profit,
                    buy_system=leg.buy_system,
                    buy_planet=leg.buy_planet,
                    buy_location=leg.buy_location,
                    buy_terminal=leg.buy_terminal,
                    sell_system=leg.sell_system,
                    sell_planet=leg.sell_planet,
                    sell_location=leg.sell_location,
                    sell_terminal=leg.sell_terminal,
                )
            )

        return simulated_route

    def _route_profit(self, route: list[TradeRouteLeg]) -> float:
        return sum(float(leg.profit) for leg in route)

    def _terminal_key(self, terminal_name: str) -> str:
        return self._normalize(terminal_name)

    def _trade_start_keys(self, rows: list[dict], normalized_start: str) -> set[str]:
        start_keys = {normalized_start}
        for row in rows:
            terminal_name = self._string_or_none(row.get("terminal_name"))
            if not terminal_name:
                continue
            aliases = {
                self._normalize(terminal_name),
                self._normalize(self._location(row)),
                self._normalize(row.get("outpost_name")),
                self._normalize(row.get("city_name")),
                self._normalize(row.get("space_station_name")),
                self._normalize(row.get("poi_name")),
                self._normalize(self._trade_location_display(row)),
                self._normalize(self._trade_location_value(self._trade_location_display(row))),
            }
            if any(
                normalized_start == alias
                or normalized_start in alias
                or (len(alias) >= 5 and alias in normalized_start)
                for alias in aliases
            ):
                start_keys.add(self._terminal_key(terminal_name))
        return {key for key in start_keys if key}

    def _trade_location_display(self, row: dict) -> str:
        terminal_name = str(row.get("terminal_name") or "Unknown terminal")
        system = self._string_or_none(row.get("star_system_name"))
        location = self._location(row)
        if system and location and location != terminal_name:
            return f"{terminal_name} - {location} ({system})"
        if system:
            return f"{terminal_name} ({system})"
        return terminal_name

    def _trade_location_value(self, value: object) -> str:
        text = str(value or "").strip()
        if " - " in text:
            return text.split(" - ", 1)[0].strip()
        if text.endswith(")") and "(" in text:
            return text.rsplit("(", 1)[0].strip()
        return text

    def _filter_prices_by_system(self, prices: list[dict], normalized_system: str) -> list[dict]:
        if not normalized_system:
            return prices
        return [
            row
            for row in prices
            if self._normalize(row.get("star_system_name")) == normalized_system
        ]

    def _matches_system(self, row: dict, normalized_system: str) -> bool:
        return not normalized_system or self._normalize(row.get("star_system_name")) == normalized_system

    def _same_terminal(self, first: dict, second: dict) -> bool:
        first_id = self._string_or_none(first.get("id_terminal") or first.get("terminal_id"))
        second_id = self._string_or_none(second.get("id_terminal") or second.get("terminal_id"))
        if first_id and second_id:
            return first_id == second_id
        return self._normalize(first.get("terminal_name")) == self._normalize(second.get("terminal_name"))

    def _available_scu(self, row: dict, average_key: str, fallback_key: str) -> float:
        value = self._number(row.get(average_key) or row.get(fallback_key))
        if value is None or value <= 0:
            return float("inf")
        return value

    def _number(self, value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _int_or_none(self, value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _display_name(self, commodity: dict) -> str:
        name = str(commodity.get("name") or "")
        code = self._string_or_none(commodity.get("code"))
        return f"{name} ({code})" if code else name

    def _location(self, row: dict) -> str | None:
        return self._string_or_none(
            row.get("outpost_name")
            or row.get("city_name")
            or row.get("space_station_name")
            or row.get("poi_name")
            or row.get("terminal_name")
        )

    def _positive(self, value: object) -> bool:
        try:
            return float(value or 0) > 0
        except (TypeError, ValueError):
            return False

    def _normalize(self, value: object) -> str:
        return " ".join(str(value or "").lower().replace("-", " ").split())

    def _strip_code_suffix(self, value: object) -> str:
        text = str(value or "").strip()
        return text.split("(", 1)[0].strip() if "(" in text and text.endswith(")") else text

    def _string_or_none(self, value: object) -> str | None:
        return str(value) if value not in (None, "") else None

    def _commodity_to_cache(self, result: CommodityResult) -> dict:
        data = result.__dict__.copy()
        data["buy_from"] = [market.__dict__ for market in result.buy_from]
        data["sell_to"] = [market.__dict__ for market in result.sell_to]
        return data

    def _commodity_from_cache(self, data: dict) -> CommodityResult:
        cached = data.copy()
        cached["buy_from"] = [CommodityMarket(**market) for market in cached.get("buy_from", [])]
        cached["sell_to"] = [CommodityMarket(**market) for market in cached.get("sell_to", [])]
        return CommodityResult(**cached)

    def _mining_result_to_cache(self, result: MiningLocationResult) -> dict:
        data = result.__dict__.copy()
        data["location_groups"] = [
            group.__dict__.copy()
            for group in result.location_groups or []
        ]
        return data

    def _mining_result_from_cache(self, data: dict) -> MiningLocationResult:
        cached = data.copy()
        cached.setdefault("location_basis", None)
        cached.setdefault("rock_signatures", [])
        cached["location_groups"] = [
            MiningSystemLocations(**group)
            for group in cached.get("location_groups", [])
            if isinstance(group, dict)
        ]
        return MiningLocationResult(**cached)

    async def close(self) -> None:
        return None
