import asyncio
from unittest.mock import AsyncMock

from src.sources.uex import UEXSource


def fallback_source() -> UEXSource:
    source = UEXSource.__new__(UEXSource)
    source._mining_fallbacks = None
    source._find_mining_material = AsyncMock(
        return_value={"name": "Gold (Ore)", "code": "GOLD"}
    )
    source._fetch_mining_location_result = AsyncMock(return_value=None)
    return source


def test_mining_lookup_uses_bundled_fallback_when_live_locations_fail() -> None:
    result = asyncio.run(fallback_source().lookup_mining_material("gold"))

    assert result is not None
    assert result.material_name == "Gold"
    assert result.code == "GOLD"
    assert "Stanton" in result.systems
    assert "Pyro" in result.systems
    assert "ARC-L5" in result.lagrange_points
    assert "Terminus" in result.planets


def test_mining_fallback_applies_system_and_location_filters() -> None:
    result = asyncio.run(
        fallback_source().lookup_mining_material("gold", system="Pyro", planet="Terminus")
    )

    assert result is not None
    assert result.systems == ["Pyro"]
    assert result.planets == ["Terminus"]
    assert result.lagrange_points == []
    assert len(result.location_groups or []) == 1
    assert result.location_groups[0].system == "Pyro"
