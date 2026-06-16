from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import LookupResult, ShipPledge, ShipPurchase, ShipResult


class StarCitizenWikiSource:
    name = "Star Citizen Wiki"
    base_url = "https://api.star-citizen.wiki"

    def __init__(self, settings: Settings, cache: SQLiteCache, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._cache = cache
        self._session = session
        self._ship_names: list[str] | None = None

    async def lookup(self, query: str) -> LookupResult | None:
        normalized_query = " ".join(query.strip().split())
        if not normalized_query:
            return None

        cache_key = f"star-citizen-wiki:{normalized_query.lower()}"
        cached = await self._cache.get(cache_key)
        if cached:
            return LookupResult(**cached)

        search_url = f"{self.base_url}/search/{quote(normalized_query)}"
        html = await self._fetch_text(search_url)
        if not html:
            return None

        result = self._parse_result(html, normalized_query, search_url)
        if result is not None:
            await self._cache.set(cache_key, result.__dict__, self._settings.cache_ttl_seconds)
        return result

    async def lookup_ship(self, query: str) -> ShipResult | None:
        normalized_query = " ".join(query.strip().split())
        if not normalized_query:
            return None

        cache_key = f"star-citizen-wiki:ship:v2:{normalized_query.lower()}"
        cached = await self._cache.get(cache_key)
        if cached:
            return self._ship_from_cache(cached)

        data = None
        for candidate in await self._ship_lookup_candidates(normalized_query):
            api_url = f"{self.base_url}/api/v2/vehicles/{quote(candidate)}"
            payload = await self._fetch_json(api_url)
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                break

        if not isinstance(data, dict):
            return None

        pledge_data = await self._fetch_pledge_price(data)
        result = self._parse_ship_result(data, pledge_data)
        await self._cache.set(cache_key, self._ship_to_cache(result), self._settings.cache_ttl_seconds)
        return result

    async def autocomplete_ships(self, query: str, limit: int = 25) -> list[str]:
        ship_names = await self._get_ship_names()
        normalized_query = self._normalize_name(query)

        if not normalized_query:
            return ship_names[:limit]

        whole_name_starts = []
        word_starts = []
        contains = []

        for name in ship_names:
            normalized_name = self._normalize_name(name)
            words = normalized_name.split()
            if normalized_name.startswith(normalized_query):
                whole_name_starts.append(name)
            elif any(word.startswith(normalized_query) for word in words):
                word_starts.append(name)
            elif normalized_query in normalized_name:
                contains.append(name)

        return (whole_name_starts + word_starts + contains)[:limit]

    async def _get_ship_names(self) -> list[str]:
        if self._ship_names is not None:
            return self._ship_names

        cached = await self._cache.get("star-citizen-wiki:ship-names:v1")
        if isinstance(cached, list) and all(isinstance(name, str) for name in cached):
            self._ship_names = cached
            return self._ship_names

        names = await self._fetch_ship_names()
        self._ship_names = names
        await self._cache.set("star-citizen-wiki:ship-names:v1", names, 86400)
        return names

    async def _ship_lookup_candidates(self, query: str) -> list[str]:
        normalized_query = self._normalize_name(query)
        candidates = [query]

        try:
            ship_names = await self._get_ship_names()
        except Exception:
            return candidates

        exact_matches = [
            name
            for name in ship_names
            if self._normalize_name(name) == normalized_query
        ]
        word_matches = [
            name
            for name in ship_names
            if normalized_query in self._normalize_name(name).split()
            and name not in exact_matches
        ]
        contains_matches = [
            name
            for name in ship_names
            if normalized_query in self._normalize_name(name)
            and name not in exact_matches
            and name not in word_matches
        ]

        for candidate in exact_matches + word_matches + contains_matches:
            if candidate not in candidates:
                candidates.append(candidate)

        return candidates[:5]

    async def _fetch_ship_names(self) -> list[str]:
        names: set[str] = set()
        page = 1
        last_page = 1

        while page <= last_page:
            payload = await self._fetch_json(f"{self.base_url}/api/v2/vehicles?page[number]={page}")
            if not payload:
                break

            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            last_page = int(meta.get("last_page") or last_page)

            for vehicle in payload.get("data", []):
                if not isinstance(vehicle, dict):
                    continue
                name = vehicle.get("game_name") or vehicle.get("name")
                if isinstance(name, str) and name.strip():
                    names.add(name.strip())

            page += 1

        return sorted(names, key=lambda name: name.lower())

    async def _fetch_text(self, url: str) -> str | None:
        try:
            async with self._session.get(url) as response:
                response.raise_for_status()
                return await response.text()
        except aiohttp.ClientError:
            return None

    async def _fetch_json(self, url: str) -> dict | None:
        try:
            async with self._session.get(url, headers={"Accept": "application/json"}) as response:
                response.raise_for_status()
                payload = await response.json()
                return payload if isinstance(payload, dict) else None
        except (aiohttp.ClientError, ValueError):
            return None

    async def _fetch_pledge_price(self, data: dict) -> dict | None:
        url = "https://api.uexcorp.uk/2.0/vehicles_prices"
        payload = await self._fetch_json(url)
        prices = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(prices, list):
            return None

        names = {
            self._normalize_name(data.get("game_name")),
            self._normalize_name(data.get("name")),
            self._normalize_name(data.get("shipmatrix_name")),
        }
        names.discard("")

        exact_matches = [
            price
            for price in prices
            if isinstance(price, dict)
            and self._normalize_name(price.get("vehicle_name")) in names
        ]
        if exact_matches:
            return self._preferred_pledge_price(exact_matches)

        fallback_matches = [
            price
            for price in prices
            if isinstance(price, dict)
            and any(name in self._normalize_name(price.get("vehicle_name")) for name in names)
        ]
        return self._preferred_pledge_price(fallback_matches)

    def _parse_result(self, html: str, query: str, fallback_url: str) -> LookupResult | None:
        soup = BeautifulSoup(html, "html.parser")

        title = self._meta_content(soup, "og:title")
        description = self._meta_content(soup, "description") or self._meta_content(soup, "og:description")
        canonical = self._canonical_url(soup) or fallback_url

        if not title:
            page_title = soup.title.get_text(strip=True) if soup.title else ""
            title = page_title or query

        if "No results found" in soup.get_text(" ", strip=True):
            return None

        summary = description or f"Found Star Citizen information for {query}."
        if len(summary) > 350:
            summary = f"{summary[:347].rstrip()}..."

        return LookupResult(
            title=title,
            summary=summary,
            url=canonical,
            source_name=self.name,
        )

    def _meta_content(self, soup: BeautifulSoup, name: str) -> str | None:
        tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
        if tag is None:
            return None
        content = tag.get("content")
        return str(content).strip() if content else None

    def _canonical_url(self, soup: BeautifulSoup) -> str | None:
        tag = soup.find("link", attrs={"rel": "canonical"})
        if tag is None:
            return None
        href = tag.get("href")
        return str(href).strip() if href else None

    def _parse_ship_result(self, data: dict, pledge_data: dict | None) -> ShipResult:
        dimensions = data.get("dimension") if isinstance(data.get("dimension"), dict) else {}
        description = self._localized(data.get("description")) or self._localized(data.get("game_description"))
        if description and len(description) > 700:
            description = f"{description[:697].rstrip()}..."

        pledge_url = data.get("pledge_url")
        pledge = self._parse_pledge(data, pledge_data, pledge_url if isinstance(pledge_url, str) else None)
        uex_prices = data.get("uex_prices") if isinstance(data.get("uex_prices"), dict) else {}
        purchases = self._parse_purchases(uex_prices.get("purchase") if isinstance(uex_prices, dict) else None)

        manufacturer = data.get("manufacturer")
        manufacturer_name = manufacturer.get("name") if isinstance(manufacturer, dict) else None

        return ShipResult(
            name=str(data.get("game_name") or data.get("name") or "Unknown ship"),
            manufacturer=manufacturer_name,
            career=self._string_or_none(data.get("career")),
            role=self._string_or_none(data.get("role")),
            vehicle_type=self._localized(data.get("type")),
            size=self._localized(data.get("size")),
            status=self._localized(data.get("production_status")),
            cargo_capacity=data.get("cargo_capacity"),
            crew=self._format_crew(data.get("crew")),
            length=dimensions.get("length"),
            beam=dimensions.get("width") or dimensions.get("beam"),
            height=dimensions.get("height"),
            description=description,
            pledge=pledge,
            purchases=purchases,
            source_url=str(data.get("web_url") or f"{self.base_url}/vehicles/{data.get('slug', '')}"),
            source_name=self.name,
        )

    def _parse_pledge(self, data: dict, pledge_data: dict | None, pledge_url: str | None) -> ShipPledge | None:
        if pledge_data:
            return ShipPledge(
                price=pledge_data.get("price") or data.get("msrp"),
                currency=str(pledge_data.get("currency") or "USD"),
                is_on_sale=bool(pledge_data.get("on_sale")) or bool(pledge_data.get("on_sale_package")),
                pledge_url=pledge_url,
                warbond_price=pledge_data.get("price_warbond") or None,
                package_price=pledge_data.get("price_package") or None,
            )

        msrp = data.get("msrp")
        if msrp is None and pledge_url is None:
            return None

        return ShipPledge(
            price=msrp,
            currency="USD",
            is_on_sale=None,
            pledge_url=pledge_url,
        )

    def _parse_purchases(self, purchase_rows: object) -> list[ShipPurchase]:
        if not isinstance(purchase_rows, list):
            return []

        purchases: list[ShipPurchase] = []
        for row in purchase_rows:
            if not isinstance(row, dict) or row.get("price_buy") is None:
                continue

            location = row.get("starmap_location")
            location_name = None
            if isinstance(location, dict):
                parts = [
                    location.get("name"),
                    location.get("parent_name"),
                    location.get("star_system_name"),
                ]
                location_name = " / ".join(str(part) for part in parts if part)

            purchases.append(
                ShipPurchase(
                    price=row["price_buy"],
                    terminal_name=str(row.get("terminal_name") or "Unknown terminal"),
                    location=location_name,
                    uex_link=row.get("uex_link") if isinstance(row.get("uex_link"), str) else None,
                )
            )

        return sorted(purchases, key=lambda purchase: float(purchase.price))[:5]

    def _localized(self, value: object) -> str | None:
        if isinstance(value, dict):
            localized = value.get("en_EN") or next((item for item in value.values() if item), None)
            return str(localized) if localized else None
        return self._string_or_none(value)

    def _string_or_none(self, value: object) -> str | None:
        return str(value) if value not in (None, "") else None

    def _format_crew(self, value: object) -> str | None:
        if isinstance(value, dict):
            minimum = value.get("min")
            maximum = value.get("max")
            if minimum is not None and maximum is not None:
                return f"{minimum}-{maximum}"
            return self._string_or_none(minimum or maximum)
        return self._string_or_none(value)

    def _normalize_name(self, value: object) -> str:
        return " ".join(str(value or "").lower().replace("-", " ").split())

    def _preferred_pledge_price(self, prices: list[dict]) -> dict | None:
        if not prices:
            return None
        for price in prices:
            if price.get("currency") == "USD":
                return price
        return prices[0]

    def _ship_to_cache(self, result: ShipResult) -> dict:
        data = result.__dict__.copy()
        data["pledge"] = result.pledge.__dict__ if result.pledge else None
        data["purchases"] = [purchase.__dict__ for purchase in result.purchases]
        return data

    def _ship_from_cache(self, data: dict) -> ShipResult:
        cached = data.copy()
        cached["pledge"] = ShipPledge(**cached["pledge"]) if cached.get("pledge") else None
        cached["purchases"] = [ShipPurchase(**purchase) for purchase in cached.get("purchases", [])]
        return ShipResult(**cached)

    async def close(self) -> None:
        return None
