from urllib.parse import quote

import aiohttp

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import CommodityMarket, CommodityResult


class UEXSource:
    name = "UEX"
    base_url = "https://api.uexcorp.uk/2.0"

    def __init__(self, settings: Settings, cache: SQLiteCache, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._cache = cache
        self._session = session
        self._commodities: list[dict] | None = None

    async def lookup(self, query: str):
        return None

    async def lookup_ship(self, query: str):
        return None

    async def autocomplete_ships(self, query: str, limit: int = 25) -> list[str]:
        return []

    async def lookup_commodity(self, query: str, system: str | None = None) -> CommodityResult | None:
        commodity = await self._find_commodity(query)
        if commodity is None:
            return None

        normalized_system = self._normalize(system)
        cache_key = f"uex:commodity:v5:{commodity['name'].lower()}:{normalized_system or 'all'}"
        cached = await self._cache.get(cache_key)
        if cached:
            return self._commodity_from_cache(cached)

        prices = await self._fetch_prices(str(commodity["name"]))
        result = self._parse_commodity(commodity, prices, system)
        await self._cache.set(cache_key, self._commodity_to_cache(result), self._settings.cache_ttl_seconds)
        return result

    async def autocomplete_commodities(self, query: str, limit: int = 25) -> list[str]:
        commodities = await self._get_commodities()
        normalized_query = self._normalize(query)
        names = [str(row["name"]) for row in commodities if row.get("name")]

        if not normalized_query:
            return names[:limit]

        starts = [name for name in names if self._normalize(name).startswith(normalized_query)]
        contains = [
            name
            for name in names
            if normalized_query in self._normalize(name) and name not in starts
        ]
        return (starts + contains)[:limit]

    async def _find_commodity(self, query: str) -> dict | None:
        normalized_query = self._normalize(query)
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

    async def _fetch_prices(self, commodity_name: str) -> list[dict]:
        url = f"{self.base_url}/commodities_prices?commodity_name={quote(commodity_name)}"
        payload = await self._fetch_json(url)
        rows = payload.get("data") if isinstance(payload, dict) else []
        return [row for row in rows if isinstance(row, dict)]

    async def _fetch_json(self, url: str) -> dict | None:
        try:
            async with self._session.get(url, headers={"Accept": "application/json"}) as response:
                response.raise_for_status()
                payload = await response.json()
                return payload if isinstance(payload, dict) else None
        except (aiohttp.ClientError, ValueError):
            return None

    def _parse_commodity(
        self,
        commodity: dict,
        prices: list[dict],
        system: str | None = None,
    ) -> CommodityResult:
        normalized_system = self._normalize(system)
        if normalized_system:
            prices = [
                row
                for row in prices
                if self._normalize(row.get("star_system_name")) == normalized_system
            ]

        buy_from = [
            self._market(row, "price_sell_avg", "scu_sell_stock_avg")
            for row in prices
            if self._positive(row.get("price_sell_avg") or row.get("price_sell"))
            and self._positive(row.get("status_sell"))
        ]
        sell_to = [
            self._market(row, "price_buy_avg", "scu_buy_avg")
            for row in prices
            if self._positive(row.get("price_buy_avg") or row.get("price_buy"))
            and self._positive(row.get("status_buy"))
        ]

        return CommodityResult(
            name=str(commodity.get("name") or "Unknown commodity"),
            code=self._string_or_none(commodity.get("code")),
            kind=self._string_or_none(commodity.get("kind")),
            average_buy_price=commodity.get("price_sell") or None,
            average_sell_price=commodity.get("price_buy") or None,
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

    async def close(self) -> None:
        return None
