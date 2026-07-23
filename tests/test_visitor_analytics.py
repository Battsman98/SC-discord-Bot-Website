import asyncio
from datetime import datetime, timezone

from src.cache import SQLiteCache


def test_visitor_analytics_count_unique_browsers_views_and_signed_in_users(tmp_path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "analytics.sqlite3"))
        now = int(datetime(2026, 7, 22, 12, tzinfo=timezone.utc).timestamp())
        await cache.record_website_visit("browser-a", 42, now)
        await cache.record_website_visit("browser-a", 42, now + 60)
        await cache.record_website_visit("browser-b", None, now + 120)
        analytics = await cache.website_visitor_analytics(now + 180)
        assert analytics["today"] == {
            "unique_visitors": 2,
            "page_views": 3,
            "signed_in_users": 1,
        }
        assert analytics["daily"][0]["date"] == "2026-07-22"
        await cache.close()

    asyncio.run(run())
