from pathlib import Path

import asyncio

from src.sources.warbonds import WarbondTrackerSource


WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def test_latest_usd_prices_deduplicates_and_ignores_other_currencies() -> None:
    rows = [
        {"vehicle_name": "MOLE", "currency": "USD", "price": 315, "date_modified": 1},
        {"vehicle_name": "MOLE", "currency": "USD", "price": 320, "date_modified": 2},
        {"vehicle_name": "MOLE", "currency": "GBP", "price": 250, "date_modified": 3},
    ]

    latest = WarbondTrackerSource._latest_usd_prices(rows)

    assert latest["mole"]["price"] == 320


def test_best_warbond_source_uses_closest_eligible_ship() -> None:
    catalog = [
        {"name": "Constellation Taurus", "price": 200, "on_sale": True, "status": "flight ready"},
        {"name": "Apollo Medivac", "price": 290, "on_sale": False, "status": "concept"},
        {"name": "Vanguard Harbinger", "price": 290, "on_sale": False, "status": "flight ready"},
        {"name": "Too Expensive", "price": 300, "on_sale": True, "status": "flight ready"},
    ]

    assert WarbondTrackerSource._best_source(catalog, 295)["name"] == "Apollo Medivac"
    assert WarbondTrackerSource._best_source(catalog, 295, flight_ready=True) == {
        "name": "Vanguard Harbinger",
        "price": 5,
    }
    assert WarbondTrackerSource._best_source(catalog, 295, on_sale=True) == {
        "name": "Constellation Taurus",
        "price": 95,
    }


def test_active_warbonds_come_from_the_newest_live_price_cohort() -> None:
    prices = {
        "old": {"vehicle_name": "Old Sale", "price": 200, "price_warbond": 180, "on_sale": 1, "game_version": "4.8.0", "date_modified": 30},
        "newer": {"vehicle_name": "Newer", "price": 425, "price_warbond": 385, "on_sale": 1, "game_version": "4.8.2", "date_modified": 50},
        "newest": {"vehicle_name": "Newest", "price": 400, "price_warbond": 360, "on_sale": 1, "game_version": "4.8.2", "date_modified": 60},
        "not-sale": {"vehicle_name": "Unavailable", "price": 300, "price_warbond": 275, "on_sale": 0, "game_version": "4.9.0", "date_modified": 70},
        "not-discounted": {"vehicle_name": "Standard", "price": 100, "price_warbond": 0, "on_sale": 1, "game_version": "4.9.0", "date_modified": 80},
    }

    rows = WarbondTrackerSource._active_rows(prices)

    assert [row["vehicle_name"] for row in rows] == ["Newest", "Newer"]


def test_game_versions_are_compared_numerically() -> None:
    assert WarbondTrackerSource._version_key("4.10.0") > WarbondTrackerSource._version_key("4.9.9")


def test_warbond_prices_use_localized_pledge_currency_not_auec() -> None:
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    renderer = javascript.split("function renderWarbond", 1)[1].split("function intelGroup", 1)[0]

    assert "pledgeMoney(offer.warbond_price, offer.currency)" in renderer
    assert "pledgeMoney(offer.standard_price, offer.currency)" in renderer
    assert "money(offer.warbond_price)" not in renderer
    assert 'style: "currency"' in javascript


def test_forced_warbond_refresh_bypasses_cache_and_replaces_it() -> None:
    class Cache:
        def __init__(self) -> None:
            self.value = {"offers": [{"name": "Cached"}]}

        async def get(self, _key):
            return self.value

        async def set(self, _key, value, _ttl):
            self.value = value

    async def scenario() -> None:
        source = WarbondTrackerSource.__new__(WarbondTrackerSource)
        source._cache = Cache()
        source._refresh_lock = asyncio.Lock()
        source._last_good = None
        refreshes = 0

        async def refresh():
            nonlocal refreshes
            refreshes += 1
            return {"offers": [{"name": "Live"}], "checked_at": "2026-08-01T00:00:00+00:00"}

        source._refresh = refresh
        assert (await source.active())["offers"][0]["name"] == "Cached"
        assert (await source.active(force_refresh=True))["offers"][0]["name"] == "Live"
        assert refreshes == 1
        assert source._cache.value["offers"][0]["name"] == "Live"

    asyncio.run(scenario())
