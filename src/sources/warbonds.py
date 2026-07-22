from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aiohttp

from src.cache import SQLiteCache
class WarbondTrackerSource:
    """Build active warbond CCU summaries without relying on Discord messages."""

    PRICES_URL = "https://api.uexcorp.uk/2.0/vehicles_prices"
    VEHICLES_URL = "https://api.uexcorp.uk/2.0/vehicles"
    STORE_URL = "https://robertsspaceindustries.com/en/pledge/ship-upgrades"
    CACHE_KEY = "warbonds:active:v1"

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
        active_rows = [
            row for row in usd_prices.values()
            if self._number(row.get("on_sale_warbond")) == 1
            and self._number(row.get("on_sale")) == 1
            and 0 < self._number(row.get("price_warbond")) < self._number(row.get("price"))
        ]
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
            vehicle = vehicle_by_name.get(self._normalize(name), {})
            offers.append({
                "name": name,
                "title": f"{name} (CCU) - Warbond Edition",
                "warbond_price": warbond,
                "standard_price": standard,
                "saving": standard - warbond,
                "cheapest_source": self._best_source(price_catalog, warbond),
                "flight_ready_source": self._best_source(price_catalog, warbond, flight_ready=True),
                "unlimited_source": self._best_source(price_catalog, warbond, on_sale=True),
                "image_url": vehicle.get("url_photo"),
                "store_url": vehicle.get("url_store") or self.STORE_URL,
                "updated_at": self._iso_date(row.get("date_modified")),
            })

        offers.sort(key=lambda offer: (-offer["saving"], offer["name"].lower()))
        result = {
            "offers": offers,
            "updated_at": max((offer["updated_at"] for offer in offers if offer["updated_at"]), default=None),
            "source": "UEX pledge prices and the RSI pledge store",
        }
        await self._cache.set(self.CACHE_KEY, result, 1800)
        return result

    async def _fetch(self, url: str) -> dict | None:
        async with self._session.get(url, headers={"Accept": "application/json"}) as response:
            response.raise_for_status()
            payload = await response.json()
        return payload if isinstance(payload, dict) else None

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
