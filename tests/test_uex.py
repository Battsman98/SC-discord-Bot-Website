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
                "price_buy_avg": 32500,
                "status_buy": 1,
                "scu_buy": 50,
                "scu_buy_avg": 45,
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
                "price_sell_avg": 29500,
                "status_sell": 1,
                "scu_sell_stock": 120,
                "scu_sell_stock_avg": 100,
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
    assert result.buy_from[0].price == 29500
    assert result.buy_from[0].demand == 100
    assert result.buy_from[0].system == "Stanton"
    assert result.buy_from[0].planet == "Crusader"
    assert result.buy_from[0].location == "Mining Outpost"
    assert result.sell_to[0].terminal_name == "High Buy Price"
    assert result.sell_to[0].price == 32500
    assert result.sell_to[0].demand == 45
    assert result.sell_to[0].system == "Stanton"
    assert result.sell_to[0].planet == "ArcCorp"
    assert result.sell_to[0].location == "Area 18"


def test_autocomplete_commodities_prefers_starts_with_matches() -> None:
    source = UEXSource.__new__(UEXSource)
    source._commodities = [
        {"name": "Agricium", "code": "AGRI"},
        {"name": "Gold", "code": "GOLD"},
        {"name": "Golden Medmon", "code": "GMED"},
        {"name": "Diamond", "code": "DIAM"},
    ]

    matches = asyncio.run(source.autocomplete_commodities("go", limit=2))

    assert matches == ["Gold (GOLD)", "Golden Medmon (GMED)"]


def test_autocomplete_commodities_matches_codes() -> None:
    source = UEXSource.__new__(UEXSource)
    source._commodities = [
        {"name": "Agricium", "code": "AGRI"},
        {"name": "Gold", "code": "GOLD"},
    ]

    matches = asyncio.run(source.autocomplete_commodities("agri", limit=2))

    assert matches == ["Agricium (AGRI)"]


def test_find_commodity_accepts_display_name_with_code() -> None:
    source = UEXSource.__new__(UEXSource)
    source._commodities = [
        {"name": "Gold", "code": "GOLD"},
    ]

    match = asyncio.run(source._find_commodity("Gold (GOLD)"))

    assert match == {"name": "Gold", "code": "GOLD"}


def test_parse_commodity_filters_by_system_before_limiting() -> None:
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
                "terminal_name": "Pyro Sale",
                "price_buy": 60000,
                "price_buy_avg": 60000,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "price_sell": 10000,
                "price_sell_avg": 10000,
                "status_sell": 1,
                "scu_sell_stock_avg": 20,
                "outpost_name": "Pyro Outpost",
                "planet_name": "Bloom",
                "star_system_name": "Pyro",
            },
            {
                "terminal_name": "Stanton Sale",
                "price_buy": 30000,
                "price_buy_avg": 30000,
                "status_buy": 1,
                "scu_buy_avg": 30,
                "price_sell": 20000,
                "price_sell_avg": 20000,
                "status_sell": 1,
                "scu_sell_stock_avg": 40,
                "city_name": "Area 18",
                "planet_name": "ArcCorp",
                "star_system_name": "Stanton",
            },
        ],
        system="Stanton",
    )

    assert [market.system for market in result.buy_from] == ["Stanton"]
    assert [market.system for market in result.sell_to] == ["Stanton"]
    assert result.buy_from[0].terminal_name == "Stanton Sale"
    assert result.sell_to[0].terminal_name == "Stanton Sale"


def test_parse_commodity_can_filter_purchase_and_sell_systems_separately() -> None:
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
                "terminal_name": "Pyro Buyer",
                "price_buy": 60000,
                "price_buy_avg": 60000,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "price_sell": 0,
                "status_sell": 0,
                "outpost_name": "Pyro Outpost",
                "planet_name": "Bloom",
                "star_system_name": "Pyro",
            },
            {
                "terminal_name": "Stanton Seller",
                "price_buy": 0,
                "status_buy": 0,
                "price_sell": 20000,
                "price_sell_avg": 20000,
                "status_sell": 1,
                "scu_sell_stock_avg": 40,
                "city_name": "Area 18",
                "planet_name": "ArcCorp",
                "star_system_name": "Stanton",
            },
        ],
        purchase_system="Stanton",
        sell_system="Pyro",
    )

    assert [market.terminal_name for market in result.buy_from] == ["Stanton Seller"]
    assert [market.terminal_name for market in result.sell_to] == ["Pyro Buyer"]


def test_calculate_trade_route_legs_builds_best_closed_loop() -> None:
    source = UEXSource.__new__(UEXSource)
    legs = source._calculate_trade_route_legs(
        [
            {
                "commodity_name": "Gold",
                "terminal_name": "A",
                "price_sell_avg": 100,
                "status_sell": 1,
                "scu_sell_stock_avg": 50,
                "outpost_name": "Mining Outpost",
                "planet_name": "Crusader",
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Gold",
                "terminal_name": "B",
                "price_buy_avg": 160,
                "status_buy": 1,
                "scu_buy_avg": 30,
                "city_name": "Checkmate",
                "planet_name": "Monox",
                "star_system_name": "Pyro",
            },
            {
                "commodity_name": "Diamond",
                "terminal_name": "B",
                "price_sell_avg": 50,
                "status_sell": 1,
                "scu_sell_stock_avg": 100,
                "outpost_name": "Elsewhere",
                "planet_name": "ArcCorp",
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Diamond",
                "terminal_name": "A",
                "price_buy_avg": 80,
                "status_buy": 1,
                "scu_buy_avg": 100,
                "city_name": "Area 18",
                "planet_name": "ArcCorp",
                "star_system_name": "Stanton",
            },
        ],
        cargo_capacity_scu=40,
        investment=10_000,
        max_stops=2,
        starting_point="A",
    )

    assert len(legs) == 2
    assert legs[0].commodity_name == "Gold"
    assert legs[0].quantity_scu == 30
    assert legs[0].investment_used == 3000
    assert legs[0].profit == 1800
    assert legs[0].sell_terminal == legs[1].buy_terminal
    assert legs[1].sell_terminal == legs[0].buy_terminal


def test_calculate_trade_route_legs_stays_inside_requested_system() -> None:
    source = UEXSource.__new__(UEXSource)
    legs = source._calculate_trade_route_legs(
        [
            {
                "commodity_name": "Agricium",
                "terminal_name": "A",
                "price_sell_avg": 1000,
                "status_sell": 1,
                "scu_sell_stock_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Agricium",
                "terminal_name": "B",
                "price_buy_avg": 1400,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Gold",
                "terminal_name": "B",
                "price_sell_avg": 500,
                "status_sell": 1,
                "scu_sell_stock_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Gold",
                "terminal_name": "A",
                "price_buy_avg": 900,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Gold",
                "terminal_name": "Pyro Buyer",
                "price_buy_avg": 2000,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Pyro",
            },
        ],
        cargo_capacity_scu=20,
        investment=20_000,
        max_stops=5,
        starting_point="A",
        stay_system="Stanton",
    )

    assert len(legs) == 2
    assert all(leg.buy_system == "Stanton" for leg in legs)
    assert all(leg.sell_system == "Stanton" for leg in legs)
    assert legs[-1].sell_terminal == "A"


def test_calculate_trade_route_legs_returns_empty_for_unknown_start() -> None:
    source = UEXSource.__new__(UEXSource)
    legs = source._calculate_trade_route_legs(
        [
            {
                "commodity_name": "Gold",
                "terminal_name": "A",
                "price_sell_avg": 100,
                "status_sell": 1,
                "scu_sell_stock_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Gold",
                "terminal_name": "B",
                "price_buy_avg": 150,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Stanton",
            },
        ],
        cargo_capacity_scu=20,
        investment=20_000,
        max_stops=5,
        starting_point="Area 18",
    )

    assert legs == []


def test_calculate_trade_route_legs_allows_lower_profit_leg_when_loop_is_profitable() -> None:
    source = UEXSource.__new__(UEXSource)
    legs = source._calculate_trade_route_legs(
        [
            {
                "commodity_name": "Compboard",
                "terminal_name": "A",
                "price_sell_avg": 100,
                "status_sell": 1,
                "scu_sell_stock_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Compboard",
                "terminal_name": "B",
                "price_buy_avg": 200,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Waste",
                "terminal_name": "B",
                "price_sell_avg": 50,
                "status_sell": 1,
                "scu_sell_stock_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Waste",
                "terminal_name": "A",
                "price_buy_avg": 10,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Stanton",
            },
        ],
        cargo_capacity_scu=10,
        investment=10_000,
        max_stops=2,
        starting_point="A",
    )

    assert len(legs) == 2
    assert sum(float(leg.profit) for leg in legs) == 600
    assert legs[0].buy_terminal == "A"
    assert legs[1].sell_terminal == "A"


def test_calculate_trade_route_legs_matches_location_alias_as_start() -> None:
    source = UEXSource.__new__(UEXSource)
    legs = source._calculate_trade_route_legs(
        [
            {
                "commodity_name": "Gold",
                "terminal_name": "ArcCorp 045",
                "outpost_name": "ArcCorp Mining Area 045",
                "price_sell_avg": 100,
                "status_sell": 1,
                "scu_sell_stock_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Gold",
                "terminal_name": "Area 18",
                "city_name": "Area 18",
                "price_buy_avg": 200,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Waste",
                "terminal_name": "Area 18",
                "city_name": "Area 18",
                "price_sell_avg": 1,
                "status_sell": 1,
                "scu_sell_stock_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Waste",
                "terminal_name": "ArcCorp 045",
                "outpost_name": "ArcCorp Mining Area 045",
                "price_buy_avg": 2,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Stanton",
            },
        ],
        cargo_capacity_scu=10,
        investment=10_000,
        max_stops=2,
        starting_point="ArcCorp Mining Area 045",
    )

    assert len(legs) == 2
    assert legs[0].buy_terminal == "ArcCorp 045"
    assert legs[-1].sell_terminal == "ArcCorp 045"


def test_calculate_trade_route_legs_falls_back_to_empty_return_route() -> None:
    source = UEXSource.__new__(UEXSource)
    legs = source._calculate_trade_route_legs(
        [
            {
                "commodity_name": "Scrap",
                "terminal_name": "Brio's Breaker",
                "outpost_name": "Brio's Breaker Yard",
                "price_sell_avg": 10,
                "status_sell": 1,
                "scu_sell_stock_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Scrap",
                "terminal_name": "Area 18",
                "city_name": "Area 18",
                "price_buy_avg": 100,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Processed Food",
                "terminal_name": "Area 18",
                "city_name": "Area 18",
                "price_sell_avg": 20,
                "status_sell": 1,
                "scu_sell_stock_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Processed Food",
                "terminal_name": "Lorville",
                "city_name": "Lorville",
                "price_buy_avg": 50,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Stanton",
            },
        ],
        cargo_capacity_scu=10,
        investment=10_000,
        max_stops=5,
        starting_point="Brio's Break",
        stay_system="Stanton",
    )

    assert len(legs) == 2
    assert legs[0].buy_terminal == "Brio's Breaker"
    assert legs[-1].sell_terminal == "Lorville"
    assert sum(float(leg.profit) for leg in legs) == 1200


def test_enrich_price_rows_adds_terminal_location_details() -> None:
    source = UEXSource.__new__(UEXSource)

    rows = source._enrich_price_rows(
        [{"id_terminal": 12, "terminal_name": "TDD Area 18", "commodity_name": "Gold"}],
        {
            "12": {
                "id": 12,
                "star_system_name": "Stanton",
                "planet_name": "ArcCorp",
                "city_name": "Area 18",
            }
        },
    )

    assert rows[0]["terminal_name"] == "TDD Area 18"
    assert rows[0]["star_system_name"] == "Stanton"
    assert rows[0]["planet_name"] == "ArcCorp"
    assert rows[0]["city_name"] == "Area 18"


def test_trade_location_value_accepts_autocomplete_display() -> None:
    source = UEXSource.__new__(UEXSource)

    assert source._trade_location_value("ARC-L3 - ARC-L3 Modern Express Station (Stanton)") == "ARC-L3"
    assert source._trade_location_value("Jackson's Swap (Pyro)") == "Jackson's Swap"
