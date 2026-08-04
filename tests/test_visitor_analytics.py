import asyncio
from datetime import datetime, timezone
from pathlib import Path

from src.cache import SQLiteCache


def test_visitor_analytics_count_unique_browsers_views_and_signed_in_users(tmp_path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "analytics.sqlite3"))
        now = int(datetime(2026, 7, 22, 12, tzinfo=timezone.utc).timestamp())
        await cache.record_website_visit("browser-a", 42, now)
        await cache.record_website_visit("browser-a", 42, now + 60)
        await cache.record_website_visit("browser-b", None, now + 120)
        await cache.touch_website_activity("browser-a", 42, now + 60)
        await cache.touch_website_activity("browser-b", None, now + 120)
        await cache.touch_website_activity("stale-browser", 99, now - 600)
        await cache.record_website_language("browser-a", "de", now)
        await cache.record_website_language("browser-a", "fr", now + 60)
        await cache.record_website_language("browser-b", "fr", now + 120)
        analytics = await cache.website_visitor_analytics(now + 180)
        assert analytics["active_now"] == {
            "unique_visitors": 2,
            "signed_in_users": 1,
            "window_minutes": 5,
        }
        assert analytics["today"] == {
            "unique_visitors": 2,
            "page_views": 3,
            "signed_in_users": 1,
        }
        assert analytics["daily"][0]["date"] == "2026-07-22"
        assert analytics["languages_last_30_days"] == [
            {"language": "de", "samples": 1},
            {"language": "fr", "samples": 1},
        ]
        await cache.close()

    asyncio.run(run())


def test_active_user_tracker_uses_visible_page_heartbeats() -> None:
    javascript = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert 'fetch("/api/activity"' in javascript
    assert 'document.visibilityState !== "visible"' in javascript
    assert "setInterval(sendActivityHeartbeat, 60_000)" in javascript
    assert 'document.addEventListener("visibilitychange", sendActivityHeartbeat)' in javascript


def test_language_measurement_is_limited_to_once_per_week_in_the_browser() -> None:
    javascript = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert 'fetch("/api/analytics/language"' in javascript
    assert "7 * 24 * 60 * 60 * 1000" in javascript
    assert "navigator.languages?.[0] || navigator.language" in javascript
