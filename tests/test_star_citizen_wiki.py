import asyncio

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
