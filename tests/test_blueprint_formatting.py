import asyncio

from src.bot import (
    _blueprint_mission_page_count,
    _blueprint_result_label,
    add_community_mining_location,
    apply_community_mining_locations,
    _format_blueprint_missions,
    _format_mining_location_page,
    _mining_location_page_count,
    _format_rock_signatures,
    build_mining_embed,
)
from src.cache import SQLiteCache
from src.sources.base import BlueprintMission, BlueprintResult, MiningLocationResult, MiningSystemLocations


def test_format_rock_signatures_shows_clusters_to_six() -> None:
    text = _format_rock_signatures([3185])

    assert text == "3,185: 1x 3,185 | 2x 6,370 | 3x 9,555 | 4x 12,740 | 5x 15,925 | 6x 19,110"


def test_build_mining_embed_groups_locations_and_omits_kind() -> None:
    result = MiningLocationResult(
        material_name="Borase",
        code="BORA",
        kind="Metal",
        refined_sell_price=None,
        raw_sell_price=None,
        is_harvestable=False,
        is_volatile_qt=False,
        is_volatile_time=False,
        is_explosive=False,
        systems=["Pyro", "Stanton"],
        lagrange_points=[],
        planets=[],
        moons=[],
        points_of_interest=[],
        source_url="https://uexcorp.space/mining/locations/commodity/borase-ore/",
        source_name="UEX",
        rock_signatures=[3570],
        location_groups=[
            MiningSystemLocations(
                system="Stanton",
                lagrange_points=["HUR-L1"],
                planets=[],
                moons=[],
                points_of_interest=[],
            ),
            MiningSystemLocations(
                system="Pyro",
                lagrange_points=[],
                planets=["Bloom"],
                moons=["Fuego"],
                points_of_interest=["Pyro Clusters"],
            ),
        ],
    )

    embed = build_mining_embed(result)
    locations = _format_mining_location_page(result)

    assert "Code: BORA" in embed.description
    assert "Rock Signatures:\n3,570:" in embed.description
    assert "Kind" not in embed.description
    assert "**Stanton**" in locations
    assert "Lagrange Points: HUR-L1" in locations
    assert "**Pyro**" in locations
    assert "Planets: Bloom" in locations
    assert len(embed.fields) == 1
    assert embed.fields[0].name == "Mining Locations"
    assert _mining_location_page_count(result) == 1


def test_community_mining_locations_merge_into_grouped_output(tmp_path) -> None:
    async def run() -> str:
        cache = await SQLiteCache.create(str(tmp_path / "cache.sqlite"))
        result = MiningLocationResult(
            material_name="Borase",
            code="BORA",
            kind=None,
            refined_sell_price=None,
            raw_sell_price=None,
            is_harvestable=False,
            is_volatile_qt=False,
            is_volatile_time=False,
            is_explosive=False,
            systems=["Stanton"],
            lagrange_points=[],
            planets=[],
            moons=[],
            points_of_interest=[],
            source_url="https://uexcorp.space/mining/locations/commodity/borase-ore/",
            source_name="UEX",
            rock_signatures=[3570],
            location_groups=[
                MiningSystemLocations(
                    system="Stanton",
                    lagrange_points=[],
                    planets=[],
                    moons=[],
                    points_of_interest=[],
                )
            ],
        )
        await add_community_mining_location(
            cache,
            {
                "material": "Borase",
                "system": "Stanton",
                "location_type": "moons",
                "location": "Aberdeen",
                "reported_by": "Tester",
            },
        )
        merged = await apply_community_mining_locations(cache, result)
        await cache.close()
        return _format_mining_location_page(merged)

    text = asyncio.run(run())

    assert "**Stanton**" in text
    assert "Moons: Aberdeen (Community)" in text


def test_format_blueprint_missions_uses_simple_ordered_fields() -> None:
    text = _format_blueprint_missions(
        [
            BlueprintMission(
                name="Adagio Holdings in Need of Salvagers",
                contractor="Adagio Holdings",
                mission_type="Salvage",
                locations="Stanton",
                min_standing_name="Jr. Contractor",
                min_standing_reputation=800,
                drop_chance=1,
            )
        ]
    )

    assert text == (
        "- Contractor: Adagio Holdings | Minimum Rep: Jr. Contractor (800 rep) | Drop Rate: 100%\n"
        "  - Adagio Holdings in Need of Salvagers"
    )


def test_format_blueprint_missions_groups_shared_reward_paths() -> None:
    text = _format_blueprint_missions(
        [
            BlueprintMission(
                name="Rank - Cargo Haul",
                contractor="Covalex Independent Contractors",
                mission_type="Hauling - Interstellar",
                locations="Stanton",
                min_standing_name="Master",
                min_standing_reputation=237750,
                drop_chance=1,
            ),
            BlueprintMission(
                name="Rank - Direct Cargo Haul",
                contractor="Covalex Independent Contractors",
                mission_type="Hauling - Interstellar",
                locations="Stanton",
                min_standing_name="Master",
                min_standing_reputation=237750,
                drop_chance=1,
            ),
        ]
    )

    assert text == (
        "- Contractor: Covalex Independent Contractors | Minimum Rep: Master (237,750 rep) | Drop Rate: 100%\n"
        "  - Rank - Cargo Haul\n"
        "  - Rank - Direct Cargo Haul"
    )
    assert "Rank - Cargo Haul" in text
    assert "Rank - Direct Cargo Haul" in text


def test_format_blueprint_missions_keeps_lowest_rep_for_same_contractor_drop() -> None:
    text = _format_blueprint_missions(
        [
            BlueprintMission(
                name="Senior Cargo Haul",
                contractor="Covalex Independent Contractors",
                mission_type="Hauling - Interstellar",
                locations="Stanton",
                min_standing_name="Master",
                min_standing_reputation=237750,
                drop_chance=1,
            ),
            BlueprintMission(
                name="Junior Cargo Haul",
                contractor="Covalex Independent Contractors",
                mission_type="Hauling - Interstellar",
                locations="Stanton",
                min_standing_name="Junior",
                min_standing_reputation=800,
                drop_chance=1,
            ),
        ]
    )

    assert "Minimum Rep: Junior (800 rep)" in text
    assert "Minimum Rep: Master" not in text
    assert "Senior Cargo Haul" in text
    assert "Junior Cargo Haul" in text


def test_format_blueprint_missions_pages_after_25_lines() -> None:
    missions = [
        BlueprintMission(
            name=f"Mission {index}",
            contractor=f"Contractor {index}",
            mission_type="Hauling",
            locations="Stanton",
            min_standing_name="Neutral",
            min_standing_reputation=0,
            drop_chance=1,
        )
        for index in range(13)
    ]

    assert _blueprint_mission_page_count(missions) == 2
    assert "Mission 0" in _format_blueprint_missions(missions, page=1)
    assert "Mission 12" not in _format_blueprint_missions(missions, page=1)
    assert "Mission 12" in _format_blueprint_missions(missions, page=2)


def test_blueprint_result_label_includes_component_size() -> None:
    result = BlueprintResult(
        name="Atlas",
        category="Quantum Drive",
        craft_time_seconds=None,
        tiers=None,
        version=None,
        ingredients=[],
        missions=[],
        source_name="SC Craft Tools",
        source_url="https://sc-craft.tools",
        component_size="Size 1",
    )

    assert _blueprint_result_label(result) == "Quantum Drive | Size 1"
