from src.bot import _blueprint_mission_page_count, _blueprint_result_label, _format_blueprint_missions
from src.sources.base import BlueprintMission, BlueprintResult


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
        "- Contractor: Adagio Holdings | Rep: Jr. Contractor (800 rep) | Drop: 100%\n"
        "  - Type: Salvage | Mission: Adagio Holdings in Need of Salvagers"
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
        "- Contractor: Covalex Independent Contractors | Rep: Master (237,750 rep) | Drop: 100%\n"
        "  - Type: Hauling - Interstellar | Mission: Rank - Cargo Haul\n"
        "  - Type: Hauling - Interstellar | Mission: Rank - Direct Cargo Haul"
    )
    assert "Rank - Cargo Haul" in text
    assert "Rank - Direct Cargo Haul" in text


def test_format_blueprint_missions_keeps_lowest_rep_for_same_contract() -> None:
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
                name="Rank - Cargo Haul",
                contractor="Covalex Independent Contractors",
                mission_type="Hauling - Interstellar",
                locations="Stanton",
                min_standing_name="Junior",
                min_standing_reputation=800,
                drop_chance=1,
            ),
        ]
    )

    assert "Rep: Junior (800 rep)" in text
    assert "Rep: Master" not in text
    assert text.count("Rank - Cargo Haul") == 1


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
