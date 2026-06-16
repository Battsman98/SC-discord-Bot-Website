from src.bot import _blueprint_result_label, _format_blueprint_missions
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
        "- Contractor: Adagio Holdings | Rep: Jr. Contractor (800 rep) | "
        "Type: Salvage | Mission: Adagio Holdings in Need of Salvagers | Drop: 100%"
    )


def test_format_blueprint_missions_deduplicates_similar_reward_paths() -> None:
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

    assert text.count("Covalex Independent Contractors") == 1
    assert "Rank - Cargo Haul" in text
    assert "Rank - Direct Cargo Haul" not in text


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
