import asyncio
from types import SimpleNamespace

from src.sources.base import ShipResult
from src.sources.star_citizen_wiki import StarCitizenWikiSource


def test_parse_result_uses_metadata() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    html = """
    <html>
      <head>
        <title>Carrack by Anvil Aerospace - Star Citizen</title>
        <meta name="description" content="The Anvil Carrack is an expedition ship.">
        <link rel="canonical" href="https://api.star-citizen.wiki/vehicles/anvl-carrack">
      </head>
      <body>Carrack</body>
    </html>
    """

    result = source._parse_result(html, "Carrack", "https://api.star-citizen.wiki/search/Carrack")

    assert result is not None
    assert result.title == "Carrack by Anvil Aerospace - Star Citizen"
    assert result.summary == "The Anvil Carrack is an expedition ship."
    assert result.url == "https://api.star-citizen.wiki/vehicles/anvl-carrack"


def test_parse_result_returns_none_for_no_results() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)

    result = source._parse_result("<html><body>No results found</body></html>", "nope", "https://example.com")

    assert result is None


def test_parse_item_result_maps_fs9_to_personal_weapon_primary() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)

    result = source._parse_item_result(
        {
            "uuid": "6f1674b1-fb58-4661-9114-f418862751d2",
            "slug": "fs-9-lmg",
            "name": "FS-9 LMG",
            "classification": "FPS.Weapon.Medium",
            "type": "WeaponPersonal",
            "type_label": "FPS Weapon",
            "sub_type": "Medium",
            "sub_type_label": "Medium",
            "size": 4,
            "description_data": [
                {"name": "Item Type", "value": "LMG"},
                {"name": "Manufacturer", "value": "Behring"},
            ],
            "manufacturer": {"name": "Behring Applied Technology"},
            "web_url": "https://api.star-citizen.wiki/items/fs-9-lmg",
        }
    )

    assert result is not None
    assert result.name == "FS-9 LMG"
    assert result.category == "Personal Weapons"
    assert result.section == "Primary"
    assert result.size == "4"
    assert result.company_name == "Behring Applied Technology"


def test_parse_ship_result_includes_pledge_and_purchase_data() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    ship = source._parse_ship_result(
        {
            "game_name": "Drake Cutlass Black",
            "manufacturer": {"name": "Drake Interplanetary"},
            "career": "Transporter",
            "role": "Medium Freight",
            "type": {"en_EN": "multi"},
            "size": {"en_EN": "medium"},
            "production_status": {"en_EN": "flight-ready"},
            "cargo_capacity": 46,
            "crew": {"min": 1, "max": 3},
            "dimension": {"length": 37.5, "width": 26.5, "height": 14},
            "description": {"en_EN": "A rugged Drake ship."},
            "msrp": 110,
            "pledge_url": "https://robertsspaceindustries.com/pledge/ships/drake-cutlass/Cutlass-Black",
            "web_url": "https://api.star-citizen.wiki/vehicles/drak-cutlass-black",
            "uex_prices": {
                "purchase": [
                    {
                        "price_buy": 2010960,
                        "terminal_name": "New Deal - Lorville",
                        "starmap_location": {
                            "name": "Lorville",
                            "parent_name": "Hurston",
                            "star_system_name": "Stanton",
                        },
                        "uex_link": "https://uexcorp.space/example",
                    }
                ]
            },
        },
        {
            "price": 110,
            "price_warbond": 100,
            "price_package": 125,
            "on_sale": 1,
            "currency": "USD",
        },
    )

    assert ship.name == "Drake Cutlass Black"
    assert ship.pledge is not None
    assert ship.pledge.is_on_sale is True
    assert ship.pledge.price == 110
    assert ship.pledge.warbond_price == 100
    assert ship.purchases[0].price == 2010960
    assert ship.purchases[0].location == "Lorville / Hurston / Stanton"


def test_autocomplete_ships_prefers_starts_with_matches() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    source._ship_names = [
        "Aegis Avenger Titan",
        "Anvil Carrack",
        "Drake Cutlass Black",
        "Origin 600i Executive Edition",
        "MISC Freelancer",
    ]

    matches = asyncio.run(source.autocomplete_ships("cut", limit=2))

    assert matches == ["Drake Cutlass Black", "Origin 600i Executive Edition"]


def test_ship_lookup_candidates_include_canonical_name() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    source._ship_names = [
        "Argo RAFT",
        "Argo RAFT Wikelo Work Special",
        "Anvil Carrack",
    ]

    candidates = asyncio.run(source._ship_lookup_candidates("argo raft"))

    assert candidates[:2] == ["argo raft", "Argo RAFT"]


def test_lookup_ship_retries_with_canonical_name() -> None:
    class FakeCache:
        async def get(self, key: str):
            return None

        async def set(self, key: str, value, ttl: int) -> None:
            return None

    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    source._cache = FakeCache()
    source._settings = SimpleNamespace(cache_ttl_seconds=300)
    source._ship_names = ["Argo RAFT"]
    requested_urls = []

    async def fake_fetch_json(url: str):
        requested_urls.append(url)
        if url.endswith("/Argo%20RAFT"):
            return {
                "data": {
                    "game_name": "Argo RAFT",
                    "manufacturer": {"name": "Argo Astronautics"},
                    "type": {"en_EN": "cargo"},
                    "size": {"en_EN": "small"},
                    "production_status": {"en_EN": "flight-ready"},
                    "cargo_capacity": 96,
                    "crew": {"min": 1, "max": 2},
                    "description": {"en_EN": "Cargo hauler."},
                }
            }
        return {"data": None}

    async def fake_fetch_pledge_price(data: dict):
        return None

    async def fake_lookup_rsi_ship(query: str):
        return SimpleNamespace(image_url="https://example.test/raft-high-resolution.jpg")

    source._fetch_json = fake_fetch_json
    source._fetch_pledge_price = fake_fetch_pledge_price
    source._lookup_rsi_ship = fake_lookup_rsi_ship

    result = asyncio.run(source.lookup_ship("argo raft"))

    assert result is not None
    assert result.name == "Argo RAFT"
    assert result.image_url == "https://example.test/raft-high-resolution.jpg"
    assert requested_urls[0].endswith("/argo%20raft")
    assert requested_urls[1].endswith("/Argo%20RAFT")


def test_fetch_pledge_price_caches_daily_vehicle_prices() -> None:
    class FakeCache:
        def __init__(self) -> None:
            self.values = {}
            self.ttls = {}

        async def get(self, key: str):
            return self.values.get(key)

        async def set(self, key: str, value, ttl: int) -> None:
            self.values[key] = value
            self.ttls[key] = ttl

    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    source._cache = FakeCache()
    calls = []

    async def fake_fetch_json(url: str):
        calls.append(url)
        return {
            "data": [
                {
                    "vehicle_name": "Drake Cutlass Black",
                    "price": 110,
                    "on_sale": 1,
                    "currency": "USD",
                }
            ]
        }

    source._fetch_json = fake_fetch_json

    result = asyncio.run(source._fetch_pledge_price({"game_name": "Drake Cutlass Black"}))

    assert result is not None
    assert result["price"] == 110
    assert source._cache.ttls["uex:vehicles-prices:v1"] == 86400
    assert len(calls) == 1

    result = asyncio.run(source._fetch_pledge_price({"game_name": "Drake Cutlass Black"}))

    assert result is not None
    assert len(calls) == 1


def test_fetch_rsi_pledge_status_uses_graphql_stock() -> None:
    class FakeCache:
        def __init__(self) -> None:
            self.values = {}
            self.ttls = {}

        async def get(self, key: str):
            return self.values.get(key)

        async def set(self, key: str, value, ttl: int) -> None:
            self.values[key] = value
            self.ttls[key] = ttl

    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    source._cache = FakeCache()
    calls = []

    async def fake_post_graphql(query: str, variables: dict):
        calls.append(variables)
        return {
            "data": {
                "store": {
                    "search": {
                        "resources": [
                            {
                                "title": "Cutlass Black",
                                "url": "/pledge/ships/drake-cutlass/Cutlass-Black",
                                "msrp": 11000,
                                "upgrades": [
                                    {"stock": {"available": True, "backOrder": False}},
                                ],
                            }
                        ]
                    }
                }
            }
        }

    source._post_rsi_graphql = fake_post_graphql

    result = asyncio.run(source._fetch_rsi_pledge_status({"name": "Cutlass Black"}))

    assert result is not None
    assert result["on_sale"] is True
    assert result["price"] == 110
    assert result["pledge_url"] == "https://robertsspaceindustries.com/pledge/ships/drake-cutlass/Cutlass-Black"
    assert source._cache.ttls["rsi:pledge-status:v2:cutlass black"] == 86400
    assert calls == [{"query": {"ships": {"name": "Cutlass Black"}}}]


def test_fetch_rsi_pledge_status_marks_no_stock_unavailable() -> None:
    class FakeCache:
        async def get(self, key: str):
            return None

        async def set(self, key: str, value, ttl: int) -> None:
            return None

    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    source._cache = FakeCache()

    async def fake_post_graphql(query: str, variables: dict):
        return {
            "data": {
                "store": {
                    "search": {
                        "resources": [
                            {
                                "title": "Galaxy",
                                "msrp": 38000,
                                "upgrades": None,
                            }
                        ]
                    }
                }
            }
        }

    source._post_rsi_graphql = fake_post_graphql

    result = asyncio.run(source._fetch_rsi_pledge_status({"name": "Galaxy"}))

    assert result is not None
    assert result["on_sale"] is False
    assert result["price"] == 380


def test_parse_ship_result_uses_rsi_url_when_wiki_pledge_link_is_missing() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)

    ship = source._parse_ship_result(
        {
            "game_name": "Aegis Javelin",
            "manufacturer": {"name": "Aegis Dynamics"},
            "msrp": 3000,
        },
        {
            "price": 3000,
            "on_sale": False,
            "pledge_url": "https://robertsspaceindustries.com/pledge/ships/aegis-javelin/Javelin",
        },
    )

    assert ship.pledge is not None
    assert ship.pledge.is_on_sale is False
    assert ship.pledge.pledge_url == "https://robertsspaceindustries.com/pledge/ships/aegis-javelin/Javelin"


def test_search_ships_filters_by_type_size_and_cargo() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    source._ship_summaries = [
        ShipResult(
            name="Drake Cutlass Black",
            manufacturer="Drake Interplanetary",
            career="Transporter",
            role="Medium Freight",
            vehicle_type="multi",
            size="medium",
            status="flight-ready",
            cargo_capacity=46,
            crew="1-3",
            length=None,
            beam=None,
            height=None,
            description=None,
            pledge=None,
            purchases=[],
            source_url="https://example.test/cutlass",
            source_name="Star Citizen Wiki",
        ),
        ShipResult(
            name="Anvil Arrow",
            manufacturer="Anvil Aerospace",
            career="Combat",
            role="Light Fighter",
            vehicle_type="fighter",
            size="small",
            status="flight-ready",
            cargo_capacity=0,
            crew="1",
            length=None,
            beam=None,
            height=None,
            description=None,
            pledge=None,
            purchases=[],
            source_url="https://example.test/arrow",
            source_name="Star Citizen Wiki",
        ),
    ]

    matches = asyncio.run(
        source.search_ships(
            query="freight",
            manufacturer="drake",
            vehicle_type="multi",
            size="medium",
            role=None,
            status="flight",
            min_cargo=40,
            max_cargo=50,
        )
    )

    assert [ship.name for ship in matches] == ["Drake Cutlass Black"]


def test_ship_facets_collects_dropdown_options() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    source._ship_summaries = [
        ShipResult(
            name="Drake Cutlass Black",
            manufacturer="Drake Interplanetary",
            career="Transporter",
            role="Medium Freight",
            vehicle_type="multi",
            size="medium",
            status="flight-ready",
            cargo_capacity=46,
            crew="1-3",
            length=None,
            beam=None,
            height=None,
            description=None,
            pledge=None,
            purchases=[],
            source_url="https://example.test/cutlass",
            source_name="Star Citizen Wiki",
        )
    ]

    facets = asyncio.run(source.ship_facets())

    assert facets["manufacturers"] == ["Drake Interplanetary"]
    assert facets["types"] == ["multi"]
    assert facets["sizes"] == ["medium"]
    assert facets["roles"] == ["Transporter / Medium Freight"]
    assert facets["statuses"] == ["flight-ready"]


def test_rsi_ship_search_candidates_strip_manufacturer_prefixes() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)

    assert source._rsi_ship_search_candidates("RSI Galaxy") == ["RSI Galaxy", "Galaxy"]
    assert source._rsi_ship_search_candidates("Anvil Arrow") == ["Anvil Arrow", "Arrow"]


def test_ship_image_prefers_high_resolution_original() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    assert source._ship_image_url({
        "images": [{
            "thumbnail_url": "https://example.test/thumb/600px-ship.webp",
            "original_url": "https://example.test/ship-4k.png",
        }]
    }) == "https://example.test/ship-4k.png"


def test_search_ships_falls_back_to_rsi_store() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    source._ship_summaries = []
    calls = []

    async def fake_post_graphql(query: str, variables: dict):
        calls.append(variables)
        if variables == {"query": {"ships": {"name": "Galaxy"}}}:
            return {
                "data": {
                    "store": {
                        "search": {
                            "resources": [
                                {
                                    "title": "Galaxy",
                                    "url": "/pledge/ships/galaxy/Galaxy",
                                    "msrp": 38000,
                                    "focus": "Modular",
                                    "productionStatus": "in-concept",
                                    "type": "multi",
                                    "manufacturer": {"name": "Roberts Space Industries"},
                                    "media": {
                                        "thumbnail": {
                                            "storeSmall": "https://example.test/galaxy.jpg",
                                        }
                                    },
                                    "upgrades": None,
                                }
                            ]
                        }
                    }
                }
            }
        return {"data": {"store": {"search": {"resources": []}}}}

    source._post_rsi_graphql = fake_post_graphql

    matches = asyncio.run(source.search_ships(query="RSI Galaxy"))

    assert [ship.name for ship in matches] == ["Galaxy"]
    assert matches[0].manufacturer == "Roberts Space Industries"
    assert matches[0].image_url == "https://example.test/galaxy.jpg"
    assert matches[0].pledge is not None
    assert matches[0].pledge.is_on_sale is False
    assert calls == [
        {"query": {"ships": {"name": "RSI Galaxy"}}},
        {"query": {"ships": {"name": "Galaxy"}}},
    ]
