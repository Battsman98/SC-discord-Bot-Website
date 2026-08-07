import asyncio
from pathlib import Path
from types import SimpleNamespace

from src.bot import _format_approved_loot_sightings, _is_bot_manager
from src.cache import SQLiteCache


def test_loot_sighting_requires_review_before_search(tmp_path: Path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "loot.sqlite3"))
        report_id = await cache.add_loot_sighting_report(
            item_uuid="fs9-blacklist",
            item_name='FS-9 "Blacklist" LMG',
            location="Farro Data Center",
            location_type="Data center",
            game_version="4.9.0",
            notes="Found in a weapon crate.",
            screenshot_url="https://cdn.example.test/evidence.png",
            reporter_id=123,
            reporter_name="Citizen",
            guild_id=456,
            channel_id=789,
        )

        assert await cache.approved_loot_sightings('FS-9 "Blacklist" LMG') == []
        pending = await cache.pending_loot_sighting_reports()
        assert pending[0]["id"] == report_id
        assert pending[0]["screenshot_url"].endswith("evidence.png")

        assert await cache.review_loot_sighting(report_id, "approved", 999, "Manager") is True
        assert await cache.review_loot_sighting(report_id, "rejected", 999, "Manager") is False
        approved = await cache.approved_loot_sightings('FS-9 "Blacklist" LMG')
        assert approved[0]["location"] == "Farro Data Center"
        assert approved[0]["status"] == "approved"
        await cache.close()

    asyncio.run(run())


def test_approved_sighting_format_includes_location_patch_and_age() -> None:
    text = _format_approved_loot_sightings([
        {
            "location": "Farro Data Center",
            "location_type": "Data center",
            "game_version": "4.9.0",
            "reviewed_at": 1_786_000_000,
        }
    ])
    assert "Farro Data Center" in text
    assert "4.9.0" in text
    assert "<t:1786000000:R>" in text


def test_location_evidence_groups_reports_and_scores_independent_confirmation(tmp_path: Path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "evidence.sqlite3"))
        for reporter_id in (101, 202):
            report_id = await cache.add_loot_sighting_report(
                item_uuid="fs9-blacklist",
                item_name='FS-9 "Blacklist" LMG',
                location="Jumptown",
                celestial_body="Daymar",
                location_type="Drug lab",
                game_version="4.9.0",
                notes="Weapon crate",
                screenshot_url=f"https://example.test/{reporter_id}.png",
                source_url=None,
                reporter_id=reporter_id,
                reporter_name=f"Citizen {reporter_id}",
                guild_id=1,
                channel_id=2,
            )
            assert await cache.review_loot_sighting(report_id, "approved", 999, "Manager")

        evidence = await cache.loot_location_evidence('FS-9 "Blacklist" LMG')
        assert len(evidence) == 1
        assert evidence[0]["location"] == "Jumptown"
        assert evidence[0]["celestial_body"] == "Daymar"
        assert evidence[0]["report_count"] == 2
        assert evidence[0]["independent_reporters"] == 2
        assert evidence[0]["confidence"] == "Likely"
        await cache.close()

    asyncio.run(run())


def test_bot_manager_role_name_is_case_insensitive(monkeypatch) -> None:
    import src.bot as bot_module

    monkeypatch.setattr(bot_module.discord, "Member", SimpleNamespace, raising=True)
    user = SimpleNamespace(roles=[SimpleNamespace(name="bot manager")])
    assert _is_bot_manager(user) is True
