import asyncio

from src.sources.sc_craft_tools import SCCraftToolsSource


def test_parse_blueprint_includes_materials_and_mission_rep() -> None:
    source = SCCraftToolsSource.__new__(SCCraftToolsSource)

    result = source._parse_blueprint(
        {
            "name": "Abrade Scraper Module",
            "category": "Vehiclegear / Salvage",
            "craft_time_seconds": 240,
            "tiers": 1,
            "version": "LIVE-4.8",
            "ingredients": [
                {
                    "slot": "CASE",
                    "name": "Iron",
                    "quantity_scu": 0.04,
                    "options": [{"unit": "scu"}],
                }
            ],
            "missions": [
                {
                    "mission_id": 180531,
                    "name": "Adagio Holdings in Need of Salvagers",
                    "drop_chance": "1.0000",
                }
            ],
        },
        {
            "180531": {
                "contractor": "Adagio Holdings",
                "mission_type": "Salvage",
                "locations": "Stanton",
                "min_standing": {"name": "Jr. Contractor", "reputation": 800},
            }
        },
    )

    assert result.name == "Abrade Scraper Module"
    assert result.category == "Vehiclegear / Salvage"
    assert result.ingredients[0].name == "Iron"
    assert result.ingredients[0].quantity == 0.04
    assert result.missions[0].contractor == "Adagio Holdings"
    assert result.missions[0].mission_type == "Salvage"
    assert result.missions[0].min_standing_name == "Jr. Contractor"
    assert result.missions[0].min_standing_reputation == 800
    assert result.missions[0].drop_chance == 1


def test_autocomplete_blueprint_filter_uses_config_hints() -> None:
    source = SCCraftToolsSource.__new__(SCCraftToolsSource)
    source._config = {
        "filterHints": {
            "category": [
                "Armour / Salvager / Medium",
                "Vehiclegear / Salvage",
            ],
            "resource": [
                {"name": "Iron"},
                {"name": "Copper"},
            ],
        }
    }

    categories = asyncio.run(source.autocomplete_blueprint_filter("category", "veh", 5))
    resources = asyncio.run(source.autocomplete_blueprint_filter("resource", "co", 5))

    assert categories == ["Vehiclegear / Salvage"]
    assert resources == ["Copper"]


def test_blueprint_cache_round_trip() -> None:
    source = SCCraftToolsSource.__new__(SCCraftToolsSource)
    result = source._parse_blueprint(
        {
            "name": "Aril Arms",
            "ingredients": [{"slot": "PLATING", "name": "Corundum", "quantity_scu": 0.04}],
            "missions": [{"mission_id": 1, "name": "XS Purchase Order", "drop_chance": "1.0000"}],
        },
        {"1": {"min_standing": {"name": "Neutral", "reputation": 0}}},
    )

    cached = source._blueprint_from_cache(source._blueprint_to_cache(result))

    assert cached == result
