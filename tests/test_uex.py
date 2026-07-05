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
    assert result.buy_from[0].terminal_name == "High Buy Price"
    assert result.buy_from[0].price == 32500
    assert result.buy_from[0].demand == 45
    assert result.buy_from[0].system == "Stanton"
    assert result.buy_from[0].planet == "ArcCorp"
    assert result.buy_from[0].location == "Area 18"
    assert result.sell_to[0].terminal_name == "Low Sell Price"
    assert result.sell_to[0].price == 29500
    assert result.sell_to[0].demand == 100
    assert result.sell_to[0].system == "Stanton"
    assert result.sell_to[0].planet == "Crusader"
    assert result.sell_to[0].location == "Mining Outpost"


def test_parse_commodity_lists_sell_only_commodities_as_sell_locations() -> None:
    source = UEXSource.__new__(UEXSource)
    result = source._parse_commodity(
        {
            "name": "Janalite",
            "code": "JANA",
            "kind": "Mineral",
            "price_buy": 0,
            "price_sell": 1577080,
            "is_illegal": 0,
            "is_mineral": 1,
            "is_raw": 1,
            "is_refined": 0,
            "is_harvestable": 1,
            "wiki": "https://starcitizen.tools/Janalite",
        },
        [
            {
                "terminal_name": "TDD Area 18",
                "price_buy": 0,
                "price_buy_avg": 0,
                "status_buy": 0,
                "scu_buy": 0,
                "scu_buy_avg": 0,
                "price_sell": 1300000,
                "price_sell_avg": 1300000,
                "status_sell": 1,
                "scu_sell_stock": 1,
                "scu_sell_stock_avg": 1,
                "city_name": "Area 18",
                "planet_name": "ArcCorp",
                "star_system_name": "Stanton",
            },
        ],
    )

    assert result.buy_from == []
    assert len(result.sell_to) == 1
    assert result.sell_to[0].terminal_name == "TDD Area 18"
    assert result.sell_to[0].price == 1300000


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


def test_autocomplete_commodities_prefers_exact_code_matches() -> None:
    source = UEXSource.__new__(UEXSource)
    source._commodities = [
        {"name": "Construction Material Pebbles", "code": "CMATP"},
        {"name": "Construction Material Rubble", "code": "CMATR"},
        {"name": "Construction Materials", "code": "CMAT"},
    ]

    matches = asyncio.run(source.autocomplete_commodities("cmat", limit=3))

    assert matches == [
        "Construction Materials (CMAT)",
        "Construction Material Pebbles (CMATP)",
        "Construction Material Rubble (CMATR)",
    ]


def test_find_commodity_accepts_display_name_with_code() -> None:
    source = UEXSource.__new__(UEXSource)
    source._commodities = [
        {"name": "Gold", "code": "GOLD"},
    ]

    match = asyncio.run(source._find_commodity("Gold (GOLD)"))

    assert match == {"name": "Gold", "code": "GOLD"}


def test_autocomplete_mining_materials_uses_raw_materials() -> None:
    source = UEXSource.__new__(UEXSource)
    source._commodities = [
        {
            "name": "Gold",
            "code": "GOLD",
            "is_available": 1,
            "is_visible": 1,
            "is_raw": 0,
            "is_harvestable": 0,
            "is_inert": 0,
        },
        {
            "name": "Gold (Ore)",
            "code": "GOLD",
            "is_available": 1,
            "is_visible": 1,
            "is_raw": 1,
            "is_harvestable": 0,
            "is_inert": 0,
        },
        {
            "name": "Hadanite",
            "code": "HADA",
            "is_available": 1,
            "is_visible": 1,
            "is_raw": 1,
            "is_harvestable": 1,
            "is_inert": 0,
        },
        {
            "name": "Golden Medmon",
            "code": "GOLM",
            "is_available": 1,
            "is_visible": 1,
            "is_raw": 0,
            "is_mineral": 0,
            "is_harvestable": 1,
            "is_inert": 0,
        },
    ]

    matches = asyncio.run(source.autocomplete_mining_materials("go", limit=5))

    assert matches == ["Gold (Ore) (GOLD)"]


def test_find_mining_material_accepts_quantanium_alias() -> None:
    source = UEXSource.__new__(UEXSource)
    source._commodities = [
        {
            "name": "Quantainium (Raw)",
            "code": "QUAN",
            "is_available": 1,
            "is_visible": 1,
            "is_raw": 1,
            "is_inert": 0,
        }
    ]

    match = asyncio.run(source._find_mining_material("Quantanium"))

    assert match is not None
    assert match["name"] == "Quantainium (Raw)"


def test_autocomplete_mining_materials_accepts_quantanium_alias() -> None:
    source = UEXSource.__new__(UEXSource)
    source._commodities = [
        {
            "name": "Quantainium (Raw)",
            "code": "QUAN",
            "is_available": 1,
            "is_visible": 1,
            "is_raw": 1,
            "is_inert": 0,
        }
    ]

    matches = asyncio.run(source.autocomplete_mining_materials("quantanium", limit=5))

    assert matches == ["Quantainium (Raw) (QUAN)"]


def test_filter_items_accepts_medpen_alias() -> None:
    source = UEXSource.__new__(UEXSource)
    items = [
        {
            "name": "ParaMed Medical Device",
            "category": "Medical",
            "section": "FPS Consumable",
            "company_name": "CureLife",
        },
        {
            "name": "LifeGuard Medical Attachment",
            "category": "Medical",
            "section": "FPS Weapon Attachment",
            "company_name": "Klaus & Werner",
        },
    ]

    matches = source._filter_items(items, query="medpen")

    assert [item["name"] for item in matches] == ["ParaMed Medical Device", "LifeGuard Medical Attachment"]


def test_parse_mining_location_result_groups_locations() -> None:
    source = UEXSource.__new__(UEXSource)
    result = source._parse_mining_location_result(
        {
            "name": "Gold (Ore)",
            "code": "GOLD",
            "kind": "Metal",
            "price_sell": 31000,
            "is_harvestable": 0,
            "is_volatile_qt": 0,
            "is_volatile_time": 0,
            "is_explosive": 0,
        },
        """
        <html><body>
        <h2>Gold (Ore)</h2>
        <a>Routes</a>
        <h3>Star Systems</h3>
        <a>Stanton</a>
        <h3>Lagrange Points</h3>
        <p>CRU-L4</p>
        <h3>Planets</h3>
        <p>Terminus</p>
        <h3>Moons</h3>
        <p>Daymar</p>
        <h3>Points of Interest</h3>
        <p>Pyro Clusters</p>
        <p>* Location data sourced from Star Citizen.</p>
        </body></html>
        """,
        "https://uexcorp.space/mining/locations/commodity/gold-ore/",
    )

    assert result.material_name == "Gold"
    assert result.systems == ["Stanton"]
    assert result.lagrange_points == ["CRU-L4"]
    assert result.planets == ["Terminus"]
    assert result.moons == ["Daymar"]
    assert result.points_of_interest == ["Pyro Clusters"]


def test_with_mining_location_groups_skips_unscoped_system_fallback() -> None:
    source = UEXSource.__new__(UEXSource)
    commodity = {"name": "Iron (Ore)", "code": "IRONO"}
    result = source._parse_mining_location_result(
        commodity,
        """
        <html><body>
        <a>Routes</a>
        <h3>Star Systems</h3><p>Stanton</p><p>Pyro</p><p>Nyx</p>
        </body></html>
        """,
        "https://uexcorp.space/mining/locations/commodity/iron-ore/",
    )

    async def fake_fetch_mining_location_result(commodity: dict, system_code: str | None):
        html_by_code = {
            "ST": """
                <html><body><a>Routes</a>
                <h3>Star Systems</h3><p>Stanton</p>
                <h3>Lagrange Points</h3><p>ARC-L3</p>
                </body></html>
            """,
            "PY": """
                <html><body><a>Routes</a>
                <h3>Star Systems</h3><p>Pyro</p>
                <h3>Planets</h3><p>Bloom</p>
                </body></html>
            """,
            "NY": """
                <html><body><a>Routes</a>
                <h3>Star Systems</h3><p>Stanton</p><p>Pyro</p><p>Nyx</p>
                <h3>Lagrange Points</h3><p>ARC-L3</p>
                <h3>Planets</h3><p>Bloom</p>
                </body></html>
            """,
        }
        return source._parse_mining_location_result(
            commodity,
            html_by_code[system_code],
            f"https://uexcorp.space/mining/locations/commodity/iron-ore/system/{system_code}/",
        )

    source._fetch_mining_location_result = fake_fetch_mining_location_result

    grouped = asyncio.run(source._with_mining_location_groups(result, commodity, None))

    assert [group.system for group in grouped.location_groups] == ["Stanton", "Pyro"]
    assert grouped.location_groups[0].lagrange_points == ["ARC-L3"]
    assert grouped.location_groups[1].planets == ["Bloom"]


def test_parse_mining_location_result_does_not_use_buy_price_as_raw_sell() -> None:
    source = UEXSource.__new__(UEXSource)
    result = source._parse_mining_location_result(
        {
            "name": "Janalite",
            "code": "JANA",
            "kind": "Mineral",
            "price_buy": 999999,
            "price_sell": 1577080,
            "is_harvestable": 1,
            "is_volatile_qt": 0,
            "is_volatile_time": 0,
            "is_explosive": 0,
        },
        "<html><body><h3>Star Systems</h3><p>Stanton</p></body></html>",
        "https://uexcorp.space/mining/locations/commodity/janalite/",
    )

    assert result.raw_sell_price == 1577080
    assert result.refined_sell_price is None


def test_parse_mining_location_result_omits_missing_raw_sell_price() -> None:
    source = UEXSource.__new__(UEXSource)
    result = source._parse_mining_location_result(
        {
            "name": "Gold (Ore)",
            "code": "GOLD",
            "kind": "Metal",
            "price_buy": 12345,
            "price_sell": 0,
            "is_harvestable": 0,
            "is_volatile_qt": 0,
            "is_volatile_time": 0,
            "is_explosive": 0,
        },
        "<html><body><h3>Star Systems</h3><p>Stanton</p></body></html>",
        "https://uexcorp.space/mining/locations/commodity/gold-ore/",
    )

    assert result.raw_sell_price is None


def test_with_mining_sell_prices_uses_refined_commodity_sell_price() -> None:
    source = UEXSource.__new__(UEXSource)
    source._commodities = [
        {
            "name": "Gold",
            "price_sell": 30934,
        },
        {
            "name": "Gold (Ore)",
            "price_sell": 0,
        },
    ]
    result = source._parse_mining_location_result(
        {
            "name": "Gold (Ore)",
            "code": "GOLD",
            "kind": "Metal",
            "price_buy": 0,
            "price_sell": 0,
            "is_refinable": 1,
            "is_harvestable": 0,
            "is_volatile_qt": 0,
            "is_volatile_time": 0,
            "is_explosive": 0,
        },
        "<html><body><h3>Star Systems</h3><p>Stanton</p></body></html>",
        "https://uexcorp.space/mining/locations/commodity/gold-ore/",
    )

    enriched = asyncio.run(
        source._with_mining_sell_prices(
            result,
            {
                "name": "Gold (Ore)",
                "price_sell": 0,
                "is_refinable": 1,
            },
        )
    )

    assert enriched.raw_sell_price is None
    assert enriched.refined_sell_price == 30934


def test_parse_mining_mom_associations_links_shared_deposit_materials() -> None:
    source = UEXSource.__new__(UEXSource)
    script = '''
    "00000000-0000-0000-0000-000000000001":{id:"00000000-0000-0000-0000-000000000001",elementClusterFactor:.1,mineableResource:"Borase",resourceType:"commodity-borase"},
    "00000000-0000-0000-0000-000000000002":{id:"00000000-0000-0000-0000-000000000002",elementClusterFactor:.1,mineableResource:"Bexalite",resourceType:"commodity-bexalite"},
    "00000000-0000-0000-0000-000000000003":{id:"00000000-0000-0000-0000-000000000003",elementClusterFactor:.1,mineableResource:"Gold",resourceType:"commodity-gold"},
    compositionArray:{MineableCompositionPart:[
        {mineableElement:"00000000-0000-0000-0000-000000000001",probability:.1},
        {mineableElement:"00000000-0000-0000-0000-000000000002",probability:.1},
        {mineableElement:"00000000-0000-0000-0000-000000000003",probability:.1}
    ]},depositName:"@hud_mining_rock_name_1",minimumDistinctElements:2
    '''

    associations = source._parse_mining_mom_associations(script)

    assert associations["borase"] == ["Bexalite", "Gold"]
    assert associations["bexalite"] == ["Borase", "Gold"]


def test_mining_material_slug_preserves_raw_suffix() -> None:
    source = UEXSource.__new__(UEXSource)

    assert source._mining_material_slug({"name": "Bexalite (Raw)", "is_refinable": 1}) == "bexalite-raw"
    assert source._mining_material_slug({"name": "Gold (Ore)", "is_refinable": 1}) == "gold-ore"


def test_parse_star_head_signatures_groups_by_material() -> None:
    source = UEXSource.__new__(UEXSource)
    script = '''
    const Dt=[
        {signature:3185,materials:["Stileron","Taranite"]},
        {signature:3570,materials:["Borase","Gold","Bexalite"]},
        {signature:3585,materials:["Gold","Borase","Bexalite"]}
    ];
    '''

    signatures = source._parse_star_head_signatures(script)

    assert signatures["stileron"] == [3185]
    assert signatures["taranite"] == [3185]
    assert signatures["borase"] == [3570, 3585]


def test_find_mining_material_accepts_rock_signature() -> None:
    source = UEXSource.__new__(UEXSource)
    source._mining_signatures = {"iron": [4270]}
    source._commodities = [
        {
            "name": "Iron (Ore)",
            "code": "IRON",
            "is_available": 1,
            "is_visible": 1,
            "is_raw": 1,
            "is_inert": 0,
        }
    ]

    match = asyncio.run(source._find_mining_material("4,270"))

    assert match is not None
    assert match["name"] == "Iron (Ore)"


def test_autocomplete_mining_materials_accepts_rock_signature() -> None:
    source = UEXSource.__new__(UEXSource)
    source._mining_signatures = {"iron": [4270]}
    source._commodities = [
        {
            "name": "Iron (Ore)",
            "code": "IRON",
            "is_available": 1,
            "is_visible": 1,
            "is_raw": 1,
            "is_inert": 0,
        }
    ]

    matches = asyncio.run(source.autocomplete_mining_materials("4270"))

    assert matches == ["Iron (Ore) (IRON)"]


def test_autocomplete_mining_materials_accepts_cluster_signature() -> None:
    source = UEXSource.__new__(UEXSource)
    source._mining_signatures = {
        "bexalite": [3570, 3585, 3600],
        "borase": [3570, 3585, 3600],
        "gold": [3200, 3570, 3585, 3600],
    }
    source._commodities = [
        {
            "name": "Bexalite (Raw)",
            "code": "BEXA",
            "is_available": 1,
            "is_visible": 1,
            "is_raw": 1,
            "is_inert": 0,
        },
        {
            "name": "Borase (Ore)",
            "code": "BORA",
            "is_available": 1,
            "is_visible": 1,
            "is_raw": 1,
            "is_inert": 0,
        },
        {
            "name": "Gold (Ore)",
            "code": "GOLD",
            "is_available": 1,
            "is_visible": 1,
            "is_raw": 1,
            "is_inert": 0,
        },
    ]

    matches = asyncio.run(source.autocomplete_mining_materials("10710"))

    assert "Gold (Ore) (GOLD)" in matches
    assert "Borase (Ore) (BORA)" in matches
    assert "Bexalite (Raw) (BEXA)" in matches


def test_merge_mining_location_results_keeps_primary_material() -> None:
    source = UEXSource.__new__(UEXSource)
    primary = source._parse_mining_location_result(
        {"name": "Borase (Ore)", "code": "BORA"},
        "<html><body><a>Routes</a><h3>Star Systems</h3></body></html>",
        "https://uexcorp.space/mining/locations/commodity/borase-ore/",
    )
    secondary = source._parse_mining_location_result(
        {"name": "Bexalite (Raw)", "code": "BEXA"},
        """
        <html><body>
        <a>Routes</a>
        <h3>Star Systems</h3><p>Stanton</p>
        <h3>Lagrange Points</h3><p>CRU-L1</p>
        <h3>Planets</h3><p>Crusader</p>
        <h3>Moons</h3><p>Daymar</p>
        </body></html>
        """,
        "https://uexcorp.space/mining/locations/commodity/bexalite/",
    )

    merged = source._merge_mining_location_results(primary, secondary)

    assert merged.material_name == "Borase"
    assert merged.code == "BORA"
    assert merged.systems == ["Stanton"]
    assert merged.lagrange_points == ["CRU-L1"]
    assert merged.planets == ["Crusader"]
    assert merged.moons == ["Daymar"]


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
        purchase_system="Pyro",
        sell_system="Stanton",
    )

    assert [market.terminal_name for market in result.buy_from] == ["Pyro Buyer"]
    assert [market.terminal_name for market in result.sell_to] == ["Stanton Seller"]


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


def test_calculate_trade_route_legs_reuses_updated_wallet_balance() -> None:
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
                "price_buy_avg": 200,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Diamond",
                "terminal_name": "B",
                "price_sell_avg": 200,
                "status_sell": 1,
                "scu_sell_stock_avg": 10,
                "star_system_name": "Stanton",
            },
            {
                "commodity_name": "Diamond",
                "terminal_name": "A",
                "price_buy_avg": 300,
                "status_buy": 1,
                "scu_buy_avg": 10,
                "star_system_name": "Stanton",
            },
        ],
        cargo_capacity_scu=10,
        investment=1_000,
        max_stops=2,
        starting_point="A",
    )

    assert len(legs) == 2
    assert legs[0].quantity_scu == 10
    assert legs[0].profit == 1000
    assert legs[1].quantity_scu == 10
    assert legs[1].investment_used == 2000
    assert sum(float(leg.profit) for leg in legs) == 2000


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


def test_item_category_is_supported_for_buyable_locator_categories() -> None:
    source = UEXSource.__new__(UEXSource)

    assert source._item_category_is_supported(
        {"section": "Systems", "name": "Quantum Drives", "is_game_related": 1}
    )
    assert source._item_category_is_supported(
        {"section": "Vehicle Weapons", "name": "Guns", "is_game_related": 1}
    )
    assert not source._item_category_is_supported(
        {"section": "Miscellaneous", "name": "Foods", "is_game_related": 1}
    )


def test_filter_items_matches_query_category_section_and_size() -> None:
    source = UEXSource.__new__(UEXSource)
    items = [
        {
            "name": "Atlas",
            "section": "Systems",
            "category": "Quantum Drives",
            "company_name": "Roberts Space Industries",
            "size": "1",
        },
        {
            "name": "Durango",
            "section": "Systems",
            "category": "Power Plants",
            "company_name": "Juno Starwerk",
            "size": "3",
        },
    ]

    assert source._filter_items(items, query="atlas", category="Quantum Drives", section="Systems", size="1") == [
        items[0]
    ]
