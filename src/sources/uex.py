from urllib.parse import quote

import aiohttp

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import CommodityMarket, CommodityResult, TradeRouteLeg, TradeRouteResult


class UEXSource:
    name = "UEX"
    base_url = "https://api.uexcorp.uk/2.0"

    def __init__(self, settings: Settings, cache: SQLiteCache, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._cache = cache
        self._session = session
        self._commodities: list[dict] | None = None
        self._all_prices: list[dict] | None = None
        self._terminals_by_id: dict[str, dict] | None = None

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
            f"uex:commodity:v6:{commodity['name'].lower()}:"
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

        starts = [
            self._display_name(row)
            for row in commodities
            if self._normalize(row.get("name")).startswith(normalized_query)
            or self._normalize(row.get("code")).startswith(normalized_query)
        ]
        contains = [
            self._display_name(row)
            for row in commodities
            if (
                normalized_query in self._normalize(row.get("name"))
                or normalized_query in self._normalize(row.get("code"))
            )
            and self._display_name(row) not in starts
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
            self._market(row, "price_sell_avg", "scu_sell_stock_avg")
            for row in purchase_prices
            if self._positive(row.get("price_sell_avg") or row.get("price_sell"))
            and self._positive(row.get("status_sell"))
        ]
        sell_to = [
            self._market(row, "price_buy_avg", "scu_buy_avg")
            for row in sell_prices
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
                    if sell_price is None or sell_price <= buy_price:
                        continue

                    quantity_scu = min(
                        cargo_capacity_scu,
                        investment / buy_price,
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

        return self._best_circular_route(candidates, max_stops, normalized_start)

    def _best_circular_route(
        self,
        candidates: list[TradeRouteLeg],
        max_stops: int,
        normalized_start: str,
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
            if self._terminal_key(leg.buy_terminal) == normalized_start
        ][:1000]

        def route_profit(route: list[TradeRouteLeg]) -> float:
            return sum(float(leg.profit) for leg in route)

        def search(route: list[TradeRouteLeg], start_terminal: str, visited_terminals: set[str]) -> None:
            nonlocal best_route, best_profit

            current_terminal = self._terminal_key(route[-1].sell_terminal)
            if len(route) >= 2 and current_terminal == start_terminal:
                profit = route_profit(route)
                if profit > best_profit:
                    best_profit = profit
                    best_route = route.copy()
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

        return best_route

    def _terminal_key(self, terminal_name: str) -> str:
        return self._normalize(terminal_name)

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

    async def close(self) -> None:
        return None
