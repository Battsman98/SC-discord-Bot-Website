from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import aiohttp

from src.cache import SQLiteCache
class WarbondTrackerSource:
    """Build active warbond CCU summaries without relying on Discord messages."""

    PRICES_URL = "https://api.uexcorp.uk/2.0/vehicles_prices"
    VEHICLES_URL = "https://api.uexcorp.uk/2.0/vehicles"
    STORE_URL = "https://robertsspaceindustries.com/en/pledge/ship-upgrades"
    CACHE_KEY = "warbonds:active:v2"
    ACTIVE_OFFERS = {
        "railen": {"name": "Railen", "standard_price": 400, "warbond_price": 360},
        "tyilui": {"name": "Tyilui", "standard_price": 425, "warbond_price": 385},
        "basher": {"name": "Basher", "standard_price": 110, "warbond_price": 100},
        "hermes": {"name": "Hermes", "standard_price": 220, "warbond_price": 200},
        "mole": {"name": "MOLE", "standard_price": 315, "warbond_price": 295},
    }

    def __init__(self, cache: SQLiteCache, timeout_seconds: int = 15) -> None:
        self._cache = cache
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_seconds))

    async def active(self) -> dict[str, Any]:
        cached = await self._cache.get(self.CACHE_KEY)
        if isinstance(cached, dict):
            return cached

        prices_payload = await self._fetch(self.PRICES_URL)
        vehicles_payload = await self._fetch(self.VEHICLES_URL)
        rows = prices_payload.get("data") if isinstance(prices_payload, dict) else None
        vehicles = vehicles_payload.get("data") if isinstance(vehicles_payload, dict) else None
        if not isinstance(rows, list) or not isinstance(vehicles, list):
            return {"offers": [], "updated_at": None, "source": "UEX / RSI pledge store"}

        usd_prices = self._latest_usd_prices(rows)
        rsi_results = await asyncio.gather(*(self._verify_rsi_ship(offer["name"]) for offer in self.ACTIVE_OFFERS.values()))
        rsi_by_name = {
            self._normalize(result.get("title")): result
            for result in rsi_results
            if isinstance(result, dict) and result.get("title")
        }
        active_rows = self._active_rows(usd_prices, rsi_by_name)
        vehicle_by_name = {
            self._normalize(vehicle.get("name")): vehicle
            for vehicle in vehicles
            if isinstance(vehicle, dict) and vehicle.get("name")
        }

        price_catalog = [
            {
                "name": str(row.get("vehicle_name") or "").strip(),
                "price": self._number(row.get("price")),
                "on_sale": self._number(row.get("on_sale")) == 1,
                "status": "concept" if vehicle_by_name.get(self._normalize(row.get("vehicle_name")), {}).get("is_concept") else "flight ready",
            }
            for row in usd_prices.values()
            if self._number(row.get("price")) > 0 and row.get("vehicle_name")
        ]

        offers = []
        for row in active_rows:
            name = str(row.get("vehicle_name") or "").strip()
            standard = self._number(row.get("price"))
            warbond = self._number(row.get("price_warbond"))
            key = self._normalize(name)
            vehicle = vehicle_by_name.get(key, {})
            rsi_ship = rsi_by_name.get(key, {})
            offers.append({
                "name": name,
                "title": f"{name} - Warbond Edition",
                "warbond_price": warbond,
                "standard_price": standard,
                "saving": standard - warbond,
                "cheapest_source": self._best_source(price_catalog, warbond),
                "flight_ready_source": self._best_source(price_catalog, warbond, flight_ready=True),
                "unlimited_source": self._best_source(price_catalog, warbond, on_sale=True),
                "image_url": vehicle.get("url_photo"),
                "store_url": vehicle.get("url_store") or rsi_ship.get("url") or self.STORE_URL,
                "updated_at": self._iso_date(row.get("date_modified")),
            })

        result = {
            "offers": offers,
            "updated_at": max((offer["updated_at"] for offer in offers if offer["updated_at"]), default=None),
            "source": "UEX pledge prices and the RSI pledge store",
        }
        await self._cache.set(self.CACHE_KEY, result, 1800)
        return result

    def _active_rows(self, prices: dict[str, dict], rsi_ships: dict[str, dict]) -> list[dict]:
        rows = []
        for key, configured in self.ACTIVE_OFFERS.items():
            if key not in rsi_ships:
                continue
            rows.append({
                **prices.get(key, {}),
                "vehicle_name": configured["name"],
                "price": configured["standard_price"],
                "price_warbond": configured["warbond_price"],
            })
        return rows

    async def _fetch(self, url: str) -> dict | None:
        async with self._session.get(url, headers={"Accept": "application/json"}) as response:
            response.raise_for_status()
            payload = await response.json()
        return payload if isinstance(payload, dict) else None

    async def _verify_rsi_ship(self, name: str) -> dict | None:
        query = """
        query ActiveWarbondShip($query: SearchQuery) {
          store(name: "pledge", browse: true) {
            search(query: $query) {
              resources { ... on RSIShip { title url msrp productionStatus } }
            }
          }
        }
        """
        async with self._session.post(
            "https://robertsspaceindustries.com/graphql",
            json={"query": query, "variables": {"query": {"ships": {"name": name}}}},
            headers={"Accept": "application/json", "Content-Type": "application/json", "Referer": self.STORE_URL},
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        resources = payload.get("data", {}).get("store", {}).get("search", {}).get("resources", [])
        expected = self._normalize(name)
        for resource in resources if isinstance(resources, list) else []:
            if isinstance(resource, dict) and self._normalize(resource.get("title")) == expected:
                url = resource.get("url")
                if isinstance(url, str) and url.startswith("/"):
                    resource["url"] = f"https://robertsspaceindustries.com{url}"
                return resource
        return None

    @classmethod
    def _latest_usd_prices(cls, rows: list[Any]) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("currency") != "USD" or not row.get("vehicle_name"):
                continue
            key = cls._normalize(row.get("vehicle_name"))
            if key not in latest or cls._number(row.get("date_modified")) > cls._number(latest[key].get("date_modified")):
                latest[key] = row
        return latest

    @classmethod
    def _best_source(
        cls,
        catalog: list[dict],
        warbond_price: float,
        *,
        flight_ready: bool = False,
        on_sale: bool = False,
    ) -> dict[str, Any] | None:
        candidates = []
        for ship in catalog:
            if ship["price"] >= warbond_price:
                continue
            if flight_ready and "flight" not in str(ship.get("status") or "").lower():
                continue
            if on_sale and not ship.get("on_sale"):
                continue
            candidates.append(ship)
        if not candidates:
            return None
        source = max(candidates, key=lambda ship: ship["price"])
        return {"name": source["name"], "price": warbond_price - source["price"]}

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _normalize(value: Any) -> str:
        return " ".join(str(value or "").lower().replace("-", " ").split())

    @staticmethod
    def _iso_date(value: Any) -> str | None:
        timestamp = WarbondTrackerSource._number(value)
        if timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

    async def close(self) -> None:
        await self._session.close()
