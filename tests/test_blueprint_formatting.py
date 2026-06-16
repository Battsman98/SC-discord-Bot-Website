from src.bot import _format_blueprint_missions
from src.sources.base import BlueprintMission


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
