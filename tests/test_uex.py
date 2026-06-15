import asyncio

from src.sources.uex import UEXSource


def test_parse_commodity_orders_buy_and_sell_markets() -> None:
    source = UEXSource.__new__(UEXSource)
    result = source._parse_commodity(
        {
            "name": "Gold",
            "code": "GOLD",
            "kind": "Metal",
            "price_buy": 31000,
            "price_sell": 32000,
            "is_illegal": 0,
            "is_mineral": 1,
            "is_raw": 0,
            "is_refined": 1,
            "is_harvestable": 0,
            "wiki": "https://starcitizen.tools/Gold",
        },
        [
            {
                "terminal_name": "High Buy Price",
                "price_buy": 33000,
                "status_buy": 1,
                "scu_buy": 50,
                "price_sell": 0,
                "status_sell": 0,
                "city_name": "Area 18",
                "planet_name": "ArcCorp",
                "star_system_name": "Stanton",
                "game_version": "4.8.1",
            },
            {
                "terminal_name": "Low Sell Price",
                "price_sell": 30000,
                "status_sell": 1,
                "scu_sell_stock": 120,
                "price_buy": 0,
                "status_buy": 0,
                "outpost_name": "Mining Outpost",
                "moon_name": "Daymar",
                "planet_name": "Crusader",
                "star_system_name": "Stanton",
                "game_version": "4.8.1",
            },
        ],
    )

    assert result.name == "Gold"
    assert result.buy_from[0].terminal_name == "Low Sell Price"
    assert result.buy_from[0].location == "Mining Outpost / Daymar / Crusader / Stanton"
    assert result.sell_to[0].terminal_name == "High Buy Price"
    assert result.sell_to[0].location == "Area 18 / ArcCorp / Stanton"


def test_autocomplete_commodities_prefers_starts_with_matches() -> None:
    source = UEXSource.__new__(UEXSource)
    source._commodities = [
        {"name": "Agricium"},
        {"name": "Gold"},
        {"name": "Golden Medmon"},
        {"name": "Diamond"},
    ]

    matches = asyncio.run(source.autocomplete_commodities("go", limit=2))

    assert matches == ["Gold", "Golden Medmon"]
