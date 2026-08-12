import asyncio
import json

from src.sources.wikelo import WikeloSource


def test_wikelo_lookup_searches_rewards_and_formats_requirements(tmp_path) -> None:
    snapshot = tmp_path / "wikelo.json"
    snapshot.write_text(json.dumps({"missions": [{
        "mission_id": "abc", "name": "Now make Polaris", "released": True,
        "version": "4.9", "source_url": "https://example.test/mission",
        "reputation_required_name": "Very Good Customer", "reputation_required": 340,
        "reputation_reward": 250,
        "rewards": [{"name": "RSI Polaris", "quantity": 1, "unit": "item"}],
        "requirements": [{"name": "Wikelo Favor", "quantity": 30, "unit": "item"},
                         {"name": "Savrilium", "quantity": 48, "unit": "SCU"}],
    }]}), encoding="utf-8")
    results = asyncio.run(WikeloSource(snapshot).lookup_wikelo("Polaris"))
    assert [result.name for result in results] == ["Now make Polaris"]
    assert results[0].requirements[1].quantity == 48
    assert results[0].requirements[1].unit == "SCU"
    assert results[0].reputation_required_name == "Very Good Customer"
    assert results[0].reputation_required == 340
    assert results[0].reputation_reward == 250


def test_current_wikelo_snapshot_has_searchable_offers() -> None:
    results = asyncio.run(WikeloSource().lookup_wikelo("Wikelo Favor"))
    assert results
    assert all(result.requirements for result in results)


def test_exact_autocomplete_choice_separates_polaris_from_polaris_bit() -> None:
    source = WikeloSource()
    suggestions = asyncio.run(source.autocomplete_wikelo("Polaris"))
    assert "Polaris" in suggestions
    assert "Polaris Bit" in suggestions

    ship_results = asyncio.run(source.lookup_wikelo("Polaris"))
    bit_results = asyncio.run(source.lookup_wikelo("Polaris Bit"))
    assert [result.name for result in ship_results] == ["Now make Polaris. Short Time Deal."]
    assert [result.name for result in bit_results] == ["Want Polaris? Need something special."]
