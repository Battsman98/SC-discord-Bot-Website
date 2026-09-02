import asyncio
import io

import pytest

from src.bot import build_trade_store_embed
from src.cache import SQLiteCache
from openpyxl import Workbook

from src.trade_stores import google_sheet_csv_url, parse_store_inventory_csv, parse_store_inventory_xlsx


def test_google_sheet_url_converts_to_csv_export() -> None:
    result = google_sheet_csv_url(
        "https://docs.google.com/spreadsheets/d/sheet_ABC-123/edit#gid=456"
    )

    assert result == (
        "https://docs.google.com/spreadsheets/d/sheet_ABC-123/export?format=csv&gid=456"
    )


def test_google_sheet_url_rejects_non_google_urls() -> None:
    with pytest.raises(ValueError, match="Google Sheets"):
        google_sheet_csv_url("https://example.com/store.csv")


def test_parse_store_inventory_supports_common_headers() -> None:
    parsed = parse_store_inventory_csv(
        b"Item Name,Price,Qty,Quality,Notes\nFS-9 LMG,500000,1,800,Crafted\nMedPen,50,12,,\n"
    )

    assert len(parsed.items) == 2
    assert parsed.items[0].name == "FS-9 LMG"
    assert parsed.items[0].price == "500000"
    assert parsed.items[0].quantity == "1"
    assert parsed.items[0].quality == "800"
    assert parsed.items[0].notes == "Crafted"
    assert len(parsed.content_hash) == 64


def test_parse_inventory_scanner_workbook_uses_selling_costs() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([
        "Location", "Category", "Item Type", "Quantity", "Name", "Size", "Quality",
        "Volume SCU", "Notes", "Average UEX Terminal Sell Price (aUEC)",
        "Average UEX Player Seller Price (aUEC)", "Price Source",
        "Estimated Sell Total (aUEC)",
    ])
    sheet.append(["Area18", "Weapons", "Rifle", 2, "FS-9 LMG", 4, 800, None, "Crafted", 1000, 1250, "UEX", 2500])
    sheet.append(["Lorville", "Armor", "Helmet", 1, "Test Helmet", 2, None, None, None, 500, None, "UEX", 500])
    buffer = io.BytesIO()
    workbook.save(buffer)

    parsed = parse_store_inventory_xlsx(buffer.getvalue())

    assert parsed.items[0].price == "1250"
    assert parsed.items[0].quantity == "2"
    assert parsed.items[0].location == "Area18"
    assert parsed.items[0].category == "Weapons"
    assert parsed.items[1].price == "500"


def test_store_embed_previews_inventory() -> None:
    parsed = parse_store_inventory_csv(b"Item Name,Price,Quantity\nFS-9 LMG,500000,1\n")
    store = {
        "store_name": "Battman's Armory",
        "description": "Weapons and armor.",
        "sheet_url": "https://docs.google.com/spreadsheets/d/test/edit",
        "location": "Seraphim Station",
        "availability": "Evenings",
    }

    embed = build_trade_store_embed(store, parsed.items, 1234567890)

    assert embed.title == "Battman's Armory"
    assert "1 item available" in embed.description
    assert any("FS-9 LMG" in field.value for field in embed.fields)
    assert any(field.name == "Default meetup" for field in embed.fields)


def test_trade_store_records_are_persistent(tmp_path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "stores.sqlite3"))
        await cache.save_trade_store(
            {
                "thread_id": 100,
                "message_id": 101,
                "owner_id": 200,
                "store_name": "Test Store",
                "description": "Test inventory",
                "sheet_url": "https://docs.google.com/spreadsheets/d/test/edit",
                "source_type": "google_sheet",
                "location": "Area18",
                "availability": "Weekends",
                "content_hash": "abc",
                "last_synced_at": 123,
                "last_error": None,
            }
        )

        stores = await cache.trade_stores(owner_id=200)
        assert len(stores) == 1
        assert stores[0]["store_name"] == "Test Store"
        assert stores[0]["content_hash"] == "abc"
        assert stores[0]["source_type"] == "google_sheet"
        await cache.close()

    asyncio.run(run())
