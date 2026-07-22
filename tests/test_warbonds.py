from pathlib import Path

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


def test_active_warbonds_are_limited_to_the_curated_rsi_verified_set() -> None:
    source = WarbondTrackerSource.__new__(WarbondTrackerSource)
    verified = {name: {"title": offer["name"]} for name, offer in source.ACTIVE_OFFERS.items()}

    rows = source._active_rows({}, verified)

    assert [row["vehicle_name"] for row in rows] == ["Railen", "Tyilui", "Basher", "Hermes", "MOLE"]
    assert [(row["price_warbond"], row["price"]) for row in rows] == [
        (360, 400), (385, 425), (100, 110), (200, 220), (295, 315)
    ]


def test_warbond_prices_use_localized_pledge_currency_not_auec() -> None:
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    renderer = javascript.split("function renderWarbond", 1)[1].split("function intelGroup", 1)[0]

    assert "pledgeMoney(offer.warbond_price, offer.currency)" in renderer
    assert "pledgeMoney(offer.standard_price, offer.currency)" in renderer
    assert "money(offer.warbond_price)" not in renderer
    assert 'style: "currency"' in javascript
