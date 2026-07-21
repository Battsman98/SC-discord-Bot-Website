import asyncio
from pathlib import Path

from src.cache import SQLiteCache, audit_action_type
from src.web import _safe_audit_query, _website_audit_metadata
from starlette.requests import Request


def test_audit_action_type_categorizes_discord_commands() -> None:
    assert audit_action_type("Command Used", {"Command": "/mining gold"}) == "mining"
    assert audit_action_type("Command Used", {"Command": "/inventory search"}) == "inventory"
    assert audit_action_type("Command Used", {"Command": "/ship Carrack"}) == "ships"
    assert audit_action_type("Command Used", {"Command": "/trade routing"}) == "trade"


def test_website_actions_are_categorized_and_background_requests_are_skipped() -> None:
    assert _website_audit_metadata("GET", "/api/mining/gold")[0] == "mining"
    assert _website_audit_metadata("POST", "/api/me/inventory")[0] == "inventory"
    assert _website_audit_metadata("PUT", "/api/me/ships")[0] == "ships"
    assert _website_audit_metadata("GET", "/api/autocomplete/mining-materials") is None
    assert _website_audit_metadata("GET", "/api/health") is None


def test_audit_query_redacts_authentication_secrets() -> None:
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/auth/discord/callback",
        "query_string": b"code=secret-code&state=secret-state&query=Carrack",
        "headers": [],
    })

    assert _safe_audit_query(request) == "query=Carrack"


def test_audit_events_filter_and_sort_by_action_type(tmp_path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "audit.sqlite3"))
        await cache.add_audit_event("Website Mining Search", {"User": "One"}, "mining")
        await cache.add_audit_event("Website Ship Search", {"User": "Two"}, "ships")
        await cache.add_audit_event("Website Mining Search", {"User": "Three"}, "mining")

        mining = await cache.recent_audit_events(25, "mining", "newest")
        assert [event["fields"]["User"] for event in mining] == ["Three", "One"]
        assert all(event["action_type"] == "mining" for event in mining)

        by_action = await cache.recent_audit_events(25, sort_order="action")
        assert [event["action_type"] for event in by_action] == ["mining", "mining", "ships"]
        await cache.close()

    asyncio.run(run())


def test_audit_ui_has_category_filter_and_sort_controls() -> None:
    web_dir = Path(__file__).resolve().parents[1] / "web"
    html = (web_dir / "index.html").read_text(encoding="utf-8")
    javascript = (web_dir / "app.js").read_text(encoding="utf-8")

    assert 'id="auditActionType"' in html
    assert '<option value="mining">Mining</option>' in html
    assert '<option value="inventory">Inventory</option>' in html
    assert '<option value="action">Action type A-Z</option>' in html
    assert 'params.set("action_type", actionType)' in javascript
