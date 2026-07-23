import asyncio
from pathlib import Path

from src.cache import SQLiteCache
from src.sources.star_citizen_wiki import StarCitizenWikiSource


def catalog_row(item_uuid: str, name: str) -> dict:
    normalized = " ".join(name.lower().replace("-", " ").split())
    return {
        "item_uuid": item_uuid,
        "stable_id": abs(hash(item_uuid)) % 2_000_000_000,
        "item_name": name,
        "normalized_name": normalized,
        "category": "Utility",
        "item_type": "Medical",
        "company_name": "CureLife",
        "item_size": "1",
        "source_url": f"https://example.test/items/{item_uuid}",
        "source_name": "Test Catalog",
        "game_version": "4.9.0-LIVE",
        "source_updated_at": "2026-07-23T00:00:00Z",
    }


def test_catalog_replacement_and_local_fuzzy_search(tmp_path: Path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "catalog.sqlite3"))
        await cache.replace_item_catalog(
            [
                catalog_row("paramed", "ParaMed Medical Device"),
                catalog_row("medpen", "CureLife Medical Pen"),
            ],
            {
                "status": "ready",
                "item_count": 2,
                "game_version": "4.9.0-LIVE",
                "last_deep_validation_at": 1,
            },
        )
        source = StarCitizenWikiSource(None, cache, None)

        exact = await source.lookup_inventory_items("ParaMed Medical Device", 5)
        fuzzy = await source.lookup_inventory_items("Pare Med Medical Device", 5)

        assert exact[0].name == "ParaMed Medical Device"
        assert fuzzy[0].name == "ParaMed Medical Device"
        await cache.close()

    asyncio.run(run())


def test_invalid_catalog_replacement_preserves_last_good_copy(tmp_path: Path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "catalog.sqlite3"))
        await cache.replace_item_catalog(
            [catalog_row("paramed", "ParaMed Medical Device")],
            {"status": "ready", "item_count": 1},
        )
        try:
            await cache.replace_item_catalog(
                [{"item_uuid": "broken"}],
                {"status": "ready", "item_count": 1},
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Incomplete catalog replacement should fail.")

        rows = await cache.item_catalog_rows()
        assert [row["item_name"] for row in rows] == ["ParaMed Medical Device"]
        await cache.close()

    asyncio.run(run())


def test_daily_validation_skips_download_when_version_and_count_match(tmp_path: Path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "catalog.sqlite3"))
        now = 2_000_000_000
        await cache.replace_item_catalog(
            [catalog_row("paramed", "ParaMed Medical Device")],
            {
                "status": "ready",
                "item_count": 1,
                "game_version": "4.9.0-LIVE",
                "last_deep_validation_at": now,
            },
        )
        source = StarCitizenWikiSource(None, cache, None)

        async def summary() -> dict:
            return {"item_count": 1, "last_page": 1, "game_version": "4.9.0-LIVE"}

        async def unexpected_download(*_args):
            raise AssertionError("Matching daily validation should not download the full catalog.")

        source._fetch_item_catalog_summary = summary
        source._replace_with_downloaded_item_catalog = unexpected_download
        result = await source.validate_item_catalog()

        assert result["status"] == "ready"
        assert result["source_item_count"] == 1
        await cache.close()

    asyncio.run(run())


def test_weekly_validation_forces_a_complete_rebuild(tmp_path: Path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "catalog.sqlite3"))
        await cache.replace_item_catalog(
            [catalog_row("paramed", "ParaMed Medical Device")],
            {
                "status": "ready",
                "item_count": 1,
                "game_version": "4.9.0-LIVE",
                "last_deep_validation_at": 1,
            },
        )
        source = StarCitizenWikiSource(None, cache, None)
        calls: list[dict] = []

        async def summary() -> dict:
            return {"item_count": 1, "last_page": 1, "game_version": "4.9.0-LIVE"}

        async def rebuild(source_summary: dict, now: int) -> dict:
            calls.append(source_summary)
            return {"status": "ready", "item_count": 1, "last_deep_validation_at": now}

        source._fetch_item_catalog_summary = summary
        source._replace_with_downloaded_item_catalog = rebuild
        result = await source.validate_item_catalog()

        assert calls == [{"item_count": 1, "last_page": 1, "game_version": "4.9.0-LIVE"}]
        assert result["status"] == "ready"
        await cache.close()

    asyncio.run(run())


def test_catalog_page_retries_transient_source_failures() -> None:
    async def run() -> None:
        source = object.__new__(StarCitizenWikiSource)
        source.base_url = "https://example.test"
        responses = [None, None, {"data": [{"uuid": "ok"}]}]

        async def fetch(_url: str):
            return responses.pop(0)

        source._fetch_json = fetch
        payload = await source._fetch_item_catalog_page(3, 200)

        assert payload["data"] == [{"uuid": "ok"}]
        assert responses == []

    asyncio.run(run())


def test_bulk_catalog_download_is_paced_below_source_rate_limit() -> None:
    assert StarCitizenWikiSource.item_catalog_page_delay_seconds >= 3
