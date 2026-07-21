from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import ItemLocatorResult, LookupResult, ShipPledge, ShipPurchase, ShipResult


class StarCitizenWikiSource:
    name = "Star Citizen Wiki"
    base_url = "https://api.star-citizen.wiki"

    def __init__(self, settings: Settings, cache: SQLiteCache, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._cache = cache
        self._session = session
        self._ship_names: list[str] | None = None
        self._ship_summaries: list[ShipResult] | None = None

    async def lookup_inventory_items(self, query: str, limit: int = 10) -> list[ItemLocatorResult]:
        normalized_query = " ".join(str(query or "").strip().split())
        if not normalized_query:
            return []

        cache_key = f"star-citizen-wiki:inventory-items:v1:{normalized_query.lower()}"
        cached = await self._cache.get(cache_key)
        if isinstance(cached, list):
            return [self._item_from_cache(row) for row in cached if isinstance(row, dict)]

        payload = await self._fetch_json(f"{self.base_url}/api/v2/items?filter[name]={quote(normalized_query)}")
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []

        results = [
            self._parse_item_result(row)
            for row in rows
            if isinstance(row, dict) and row.get("name")
        ]
        results = [result for result in results if result is not None]
        results.sort(key=lambda item: self._inventory_item_match_rank(normalized_query, item.name))
        results = results[:limit]
        await self._cache.set(cache_key, [self._item_to_cache(item) for item in results], 86400)
        return results

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

        cache_key = f"star-citizen-wiki:ship:v6:{normalized_query.lower()}"
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
            result = await self._lookup_rsi_ship(normalized_query)
            if result is not None:
                await self._cache.set(cache_key, self._ship_to_cache(result), self._settings.cache_ttl_seconds)
            return result

        pledge_data = await self._fetch_pledge_price(data)
        rsi_pledge_status = await self._fetch_rsi_pledge_status(data)
        if rsi_pledge_status is not None:
            pledge_data = {**(pledge_data or {}), **rsi_pledge_status}
        result = self._parse_ship_result(data, pledge_data)
        if not result.image_url:
            rsi_result = await self._lookup_rsi_ship(normalized_query)
            if rsi_result and rsi_result.image_url:
                result.image_url = rsi_result.image_url
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
        ships = await self._get_ship_summaries()
        filters = {
            "query": self._normalize_name(query),
            "manufacturer": self._normalize_name(manufacturer),
            "vehicle_type": self._normalize_name(vehicle_type),
            "size": self._normalize_name(size),
            "role": self._normalize_name(role),
            "status": self._normalize_name(status),
        }

        matches = []
        for ship in ships:
            if not self._ship_matches(ship, filters, min_cargo, max_cargo):
                continue
            matches.append(ship)

        if not matches and filters["query"] and not any(
            filters[key] for key in ("manufacturer", "vehicle_type", "size", "role", "status")
        ) and min_cargo is None and max_cargo is None:
            matches = await self._search_rsi_ships(str(query or ""))

        start = max(0, (page - 1) * limit)
        return await self._enrich_ship_results(
            matches[start : start + limit],
            include_pledge=bool(filters["query"]),
        )

    async def _enrich_ship_results(
        self,
        ships: list[ShipResult],
        include_pledge: bool = False,
    ) -> list[ShipResult]:
        if not hasattr(self, "_cache"):
            return ships
        enriched = []
        for ship in ships:
            pledge_needs_detail = include_pledge and (
                ship.pledge is None
                or ship.pledge.is_on_sale is None
                or not ship.pledge.pledge_url
            )
            if ship.image_url and not pledge_needs_detail:
                enriched.append(ship)
                continue
            detail = await self.lookup_ship(ship.name)
            enriched.append(detail or ship)
        return enriched

    async def ship_facets(self) -> dict[str, list[str]]:
        ships = await self._get_ship_summaries()
        return {
            "manufacturers": self._facet_values(ship.manufacturer for ship in ships),
            "types": self._facet_values(ship.vehicle_type for ship in ships),
            "sizes": self._facet_values(ship.size for ship in ships),
            "roles": self._facet_values(
                " / ".join(value for value in [ship.career, ship.role] if value)
                for ship in ships
            ),
            "statuses": self._facet_values(ship.status for ship in ships),
        }

    def _facet_values(self, values) -> list[str]:
        unique = {str(value).strip() for value in values if value}
        return sorted(unique, key=lambda value: value.lower())

    def _ship_matches(
        self,
        ship: ShipResult,
        filters: dict[str, str],
        min_cargo: int | float | None,
        max_cargo: int | float | None,
    ) -> bool:
        query = filters["query"]
        if query:
            haystack = self._normalize_name(
                " ".join(
                    value
                    for value in [
                        ship.name,
                        ship.manufacturer,
                        ship.career,
                        ship.role,
                        ship.vehicle_type,
                        ship.size,
                        ship.status,
                    ]
                    if value
                )
            )
            if query not in haystack:
                return False

        field_values = {
            "manufacturer": ship.manufacturer,
            "vehicle_type": ship.vehicle_type,
            "size": ship.size,
            "status": ship.status,
        }
        for key, value in field_values.items():
            if filters[key] and filters[key] not in self._normalize_name(value):
                return False

        if filters["role"]:
            role_text = self._normalize_name(" ".join(value for value in [ship.career, ship.role] if value))
            if filters["role"] not in role_text:
                return False

        cargo = ship.cargo_capacity
        if min_cargo is not None and (cargo is None or float(cargo) < float(min_cargo)):
            return False
        if max_cargo is not None and (cargo is None or float(cargo) > float(max_cargo)):
            return False

        return True

    async def _lookup_rsi_ship(self, query: str) -> ShipResult | None:
        results = await self._search_rsi_ships(query, limit=1)
        return results[0] if results else None

    async def _search_rsi_ships(self, query: str, limit: int = 24) -> list[ShipResult]:
        seen: set[str] = set()
        results: list[ShipResult] = []
        for candidate in self._rsi_ship_search_candidates(query):
            if not candidate:
                continue
            payload = await self._post_rsi_graphql(
                self._rsi_ship_search_query(),
                {"query": {"ships": {"name": candidate}}},
            )
            resources = (
                payload.get("data", {})
                .get("store", {})
                .get("search", {})
                .get("resources")
                if isinstance(payload, dict)
                else None
            )
            if not isinstance(resources, list):
                continue
            for resource in resources:
                if not isinstance(resource, dict):
                    continue
                ship = self._parse_rsi_ship_result(resource)
                if ship is None or self._normalize_name(ship.name) in seen:
                    continue
                seen.add(self._normalize_name(ship.name))
                results.append(ship)
                if len(results) >= limit:
                    return results
            if results:
                return results
        return results

    def _rsi_ship_search_candidates(self, query: str) -> list[str]:
        normalized = " ".join(str(query or "").strip().split())
        candidates = [normalized]
        manufacturer_prefixes = [
            "aegis",
            "anvil",
            "argo",
            "banu",
            "cnou",
            "consolidated outland",
            "crusader",
            "drake",
            "esperia",
            "gatac",
            "greycat",
            "kruger",
            "misc",
            "mirai",
            "origin",
            "rsi",
            "roberts space industries",
            "tumbril",
        ]
        normalized_lower = normalized.lower()
        for prefix in manufacturer_prefixes:
            if normalized_lower.startswith(f"{prefix} "):
                candidates.append(normalized[len(prefix):].strip())
        return [candidate for index, candidate in enumerate(candidates) if candidate and candidate not in candidates[:index]]

    def _rsi_ship_search_query(self) -> str:
        return """
        query ShipSearch($query: SearchQuery) {
          store(name: "pledge", browse: true) {
            search(query: $query) {
              resources {
                ... on RSIShip {
                  title
                  name
                  url
                  msrp
                  focus
                  productionStatus
                  type
                  media {
                    thumbnail {
                      wallpaperMedium
                      storeSmall
                      slideshow
                    }
                  }
                  manufacturer {
                    name
                  }
                  upgrades {
                    stock {
                      available
                      backOrder
                    }
                  }
                }
              }
            }
          }
        }
        """

    def _parse_rsi_ship_result(self, resource: dict) -> ShipResult | None:
        name = resource.get("title") or resource.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        manufacturer = resource.get("manufacturer")
        media = resource.get("media") if isinstance(resource.get("media"), dict) else {}
        thumbnail = media.get("thumbnail") if isinstance(media.get("thumbnail"), dict) else {}
        upgrades = resource.get("upgrades")
        stocks = [
            upgrade.get("stock")
            for upgrade in upgrades
            if isinstance(upgrade, dict) and isinstance(upgrade.get("stock"), dict)
        ] if isinstance(upgrades, list) else []
        is_on_sale = any(bool(stock.get("available")) or bool(stock.get("backOrder")) for stock in stocks)
        msrp = resource.get("msrp")
        relative_url = resource.get("url")
        source_url = (
            f"https://robertsspaceindustries.com{relative_url}"
            if isinstance(relative_url, str) and relative_url.startswith("/")
            else str(relative_url or "https://robertsspaceindustries.com/en/pledge")
        )
        return ShipResult(
            name=name.strip(),
            manufacturer=manufacturer.get("name") if isinstance(manufacturer, dict) else None,
            career=None,
            role=self._string_or_none(resource.get("focus")),
            vehicle_type=self._string_or_none(resource.get("type")),
            size=None,
            status=self._string_or_none(resource.get("productionStatus")),
            cargo_capacity=None,
            crew=None,
            length=None,
            beam=None,
            height=None,
            description=None,
            pledge=ShipPledge(
                price=float(msrp) / 100 if msrp is not None else None,
                currency="USD",
                is_on_sale=is_on_sale,
                pledge_url=source_url,
            ),
            purchases=[],
            source_url=source_url,
            source_name="Roberts Space Industries",
            image_url=next(
                (
                    thumbnail.get(key)
                    for key in ("wallpaperMedium", "slideshow", "storeSmall")
                    if isinstance(thumbnail.get(key), str) and thumbnail.get(key)
                ),
                None,
            ),
        )

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

    async def _get_ship_summaries(self) -> list[ShipResult]:
        if self._ship_summaries is not None:
            return self._ship_summaries

        cached = await self._cache.get("star-citizen-wiki:ship-summaries:v2")
        if isinstance(cached, list):
            self._ship_summaries = [self._ship_from_cache(item) for item in cached if isinstance(item, dict)]
            return self._ship_summaries

        summaries = await self._fetch_ship_summaries()
        self._ship_summaries = summaries
        await self._cache.set(
            "star-citizen-wiki:ship-summaries:v2",
            [self._ship_to_cache(ship) for ship in summaries],
            86400,
        )
        return summaries

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

    async def _fetch_ship_summaries(self) -> list[ShipResult]:
        ships: dict[str, ShipResult] = {}
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
                ship = self._parse_ship_result(vehicle, pledge_data=None)
                ships[ship.name] = ship

            page += 1

        return sorted(ships.values(), key=lambda ship: ship.name.lower())

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
        cache_key = "uex:vehicles-prices:v1"
        cached_prices = await self._cache.get(cache_key)
        if isinstance(cached_prices, list):
            prices = cached_prices
        else:
            url = "https://api.uexcorp.uk/2.0/vehicles_prices"
            payload = await self._fetch_json(url)
            prices = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(prices, list):
                return None
            await self._cache.set(cache_key, prices, 86400)

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

    async def _fetch_rsi_pledge_status(self, data: dict) -> dict | None:
        ship_name = self._rsi_store_ship_name(data)
        if not ship_name:
            return None

        cache_key = f"rsi:pledge-status:v2:{self._normalize_name(ship_name)}"
        cached = await self._cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

        query = """
        query ShipPledgeAvailability($query: SearchQuery) {
          store(name: "pledge", browse: true) {
            search(query: $query) {
              resources {
                ... on RSIShip {
                  title
                  url
                  msrp
                  productionStatus
                  upgrades {
                    stock {
                      unlimited
                      show
                      available
                      backOrder
                      qty
                      backOrderQty
                      level
                    }
                  }
                }
              }
            }
          }
        }
        """
        payload = await self._post_rsi_graphql(
            query,
            {"query": {"ships": {"name": ship_name}}},
        )
        resources = (
            payload.get("data", {})
            .get("store", {})
            .get("search", {})
            .get("resources")
            if isinstance(payload, dict)
            else None
        )
        if not isinstance(resources, list) or not resources:
            return None

        preferred = self._preferred_rsi_ship_resource(resources, ship_name)
        if not isinstance(preferred, dict):
            return None

        upgrades = preferred.get("upgrades")
        stocks = [
            upgrade.get("stock")
            for upgrade in upgrades
            if isinstance(upgrade, dict) and isinstance(upgrade.get("stock"), dict)
        ] if isinstance(upgrades, list) else []
        is_on_sale = any(bool(stock.get("available")) or bool(stock.get("backOrder")) for stock in stocks)
        msrp = preferred.get("msrp")
        status = {
            "on_sale": is_on_sale,
            "rsi_checked": True,
            "rsi_stock": stocks,
        }
        relative_url = preferred.get("url")
        if isinstance(relative_url, str) and relative_url.strip():
            status["pledge_url"] = (
                f"https://robertsspaceindustries.com{relative_url}"
                if relative_url.startswith("/")
                else relative_url
            )
        if msrp is not None:
            status["price"] = float(msrp) / 100

        await self._cache.set(cache_key, status, 86400)
        return status

    async def _post_rsi_graphql(self, query: str, variables: dict) -> dict | None:
        if not hasattr(self, "_session"):
            return None
        try:
            async with self._session.post(
                "https://robertsspaceindustries.com/graphql",
                json={"query": query, "variables": variables},
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Referer": "https://robertsspaceindustries.com/en/pledge",
                },
            ) as response:
                response.raise_for_status()
                payload = await response.json()
                return payload if isinstance(payload, dict) else None
        except (aiohttp.ClientError, ValueError):
            return None

    def _rsi_store_ship_name(self, data: dict) -> str | None:
        for key in ("name", "shipmatrix_name", "game_name"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        pledge_url = data.get("pledge_url")
        if isinstance(pledge_url, str) and pledge_url.strip():
            return pledge_url.rstrip("/").split("/")[-1].replace("-", " ")
        return None

    def _preferred_rsi_ship_resource(self, resources: list, ship_name: str) -> dict | None:
        normalized = self._normalize_name(ship_name)
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            title = self._normalize_name(resource.get("title"))
            if title == normalized:
                return resource
        return next((resource for resource in resources if isinstance(resource, dict)), None)

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
            image_url=self._ship_image_url(data),
        )

    def _parse_pledge(self, data: dict, pledge_data: dict | None, pledge_url: str | None) -> ShipPledge | None:
        if pledge_data:
            return ShipPledge(
                price=pledge_data.get("price") or data.get("msrp"),
                currency=str(pledge_data.get("currency") or "USD"),
                is_on_sale=bool(pledge_data.get("on_sale")) or bool(pledge_data.get("on_sale_package")),
                pledge_url=pledge_data.get("pledge_url") or pledge_url,
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

    def _parse_item_result(self, data: dict) -> ItemLocatorResult | None:
        name = self._string_or_none(data.get("name"))
        if not name:
            return None

        category, item_type = self._inventory_item_category_type(data)
        source_url = self._string_or_none(data.get("web_url")) or f"{self.base_url}/items/{data.get('slug', '')}"
        uuid = self._string_or_none(data.get("uuid")) or self._string_or_none(data.get("slug")) or name
        manufacturer = data.get("manufacturer") if isinstance(data.get("manufacturer"), dict) else {}

        return ItemLocatorResult(
            id=self._stable_item_id(uuid),
            name=name,
            section=item_type,
            category=category,
            company_name=self._string_or_none(manufacturer.get("name")) if isinstance(manufacturer, dict) else None,
            size=self._string_or_none(data.get("size")),
            wiki_url=source_url,
            source_url=source_url,
            source_name=self.name,
            purchases=[],
        )

    def _inventory_item_category_type(self, data: dict) -> tuple[str | None, str | None]:
        type_code = self._string_or_none(data.get("type")) or ""
        type_label = self._string_or_none(data.get("type_label")) or ""
        sub_type = self._string_or_none(data.get("sub_type")) or ""
        sub_type_label = self._string_or_none(data.get("sub_type_label")) or ""
        classification = self._string_or_none(data.get("classification")) or ""
        item_type_value = self._description_data_value(data, "Item Type") or sub_type_label or sub_type

        haystack = self._normalize_name(" ".join([type_code, type_label, sub_type, sub_type_label, classification]))
        if "weaponpersonal" in haystack or "fps weapon" in haystack or "fps weapon" in self._normalize_name(type_label):
            return "Personal Weapons", self._personal_weapon_type(item_type_value, classification)
        if "attachment" in haystack or type_code in {"FPSAttachment", "WeaponAttachment"}:
            return "Personal Weapons", "Attachments"
        if "armor" in haystack or "armour" in haystack:
            return "Armor", sub_type_label or item_type_value or None
        if "clothing" in haystack:
            return "Clothing", sub_type_label or item_type_value or None
        if "med" in haystack or "medical" in haystack:
            return "Utility", "Medical"
        if "food" in haystack or "drink" in haystack:
            return "Consumables", sub_type_label or type_label or None
        if "harvestable" in haystack:
            return "Commodities", "Harvestable"
        if type_label:
            return type_label, sub_type_label or item_type_value or None
        return None, None

    def _personal_weapon_type(self, item_type_value: str | None, classification: str) -> str:
        normalized = self._normalize_name(" ".join(value for value in [item_type_value, classification] if value))
        sidearm_terms = {"pistol", "sidearm"}
        primary_terms = {"lmg", "rifle", "shotgun", "sniper", "smg", "launcher", "railgun"}
        if any(term in normalized.split() or term in normalized for term in sidearm_terms):
            return "Sidearm"
        if any(term in normalized.split() or term in normalized for term in primary_terms):
            return "Primary"
        if "melee" in normalized or "knife" in normalized:
            return "Melee"
        return "Primary"

    def _description_data_value(self, data: dict, name: str) -> str | None:
        rows = data.get("description_data")
        if not isinstance(rows, list):
            return None
        normalized_name = self._normalize_name(name)
        for row in rows:
            if not isinstance(row, dict):
                continue
            if self._normalize_name(row.get("name")) == normalized_name:
                return self._string_or_none(row.get("value") or row.get("type"))
        return None

    def _inventory_item_match_rank(self, query: str, name: str) -> tuple[int, int, str]:
        normalized_query = self._normalize_name(query)
        normalized_name = self._normalize_name(name)
        if normalized_name == normalized_query:
            return (0, len(name), name.lower())
        if normalized_name.startswith(normalized_query):
            return (1, len(name), name.lower())
        if normalized_query in normalized_name:
            return (2, len(name), name.lower())
        return (3, len(name), name.lower())

    def _stable_item_id(self, value: str) -> int:
        total = 0
        for char in value:
            total = ((total * 31) + ord(char)) % 2_000_000_000
        return total

    def _item_to_cache(self, result: ItemLocatorResult) -> dict:
        return result.__dict__.copy()

    def _item_from_cache(self, data: dict) -> ItemLocatorResult:
        cached = data.copy()
        cached.setdefault("purchases", [])
        return ItemLocatorResult(**cached)

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

    def _ship_image_url(self, data: dict) -> str | None:
        images = data.get("images")
        if not isinstance(images, list):
            return None
        for image in images:
            if not isinstance(image, dict):
                continue
            original = image.get("original_url")
            if isinstance(original, str) and original:
                return original
            thumbnail = image.get("thumbnail_url")
            if isinstance(thumbnail, str) and thumbnail:
                return thumbnail
        return None

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
