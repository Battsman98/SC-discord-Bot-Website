from types import SimpleNamespace

from src.bot import (
    TRADING_FORUM_TAGS,
    TRADING_GUIDE_TAG,
    VISITOR_COMMAND_CHANNELS,
    _trade_listing_content,
    _trade_seller_terms,
    build_trading_item_embed,
)
from src.sources.base import TradeItemResult


def test_trading_forum_has_the_three_required_listing_types() -> None:
    assert TRADING_FORUM_TAGS == ("WTS", "WTB", "WTT")
    assert TRADING_GUIDE_TAG not in TRADING_FORUM_TAGS


def test_trade_listing_command_is_routed_to_trade_tools() -> None:
    assert VISITOR_COMMAND_CHANNELS["trade listing"] == "trade-tools"


def test_trade_item_embed_includes_catalog_details_and_image() -> None:
    item = TradeItemResult(
        uuid="item-1",
        name="Test Helmet",
        category="Helmet",
        manufacturer="Acme",
        size="Medium",
        description="A concise test description.",
        image_url="https://example.com/helmet.png",
        wiki_url="https://example.com/wiki",
        uex_url="https://example.com/uex",
    )

    embed = build_trading_item_embed(item, "WTS")

    assert embed.title == "Test Helmet"
    assert embed.description == "A concise test description."
    assert embed.image.url == "https://example.com/helmet.png"
    assert any(field.name == "Listing" and "WTS" in field.value for field in embed.fields)
    assert any(field.name == "Seller's terms" and "aUEC" in field.value for field in embed.fields)
    assert any(field.name == "Item links" and "View on UEX" in field.value for field in embed.fields)


def test_trade_listing_content_formats_user_price_quantity_and_notes() -> None:
    content = _trade_listing_content(
        SimpleNamespace(mention="<@123>"),
        "WTB",
        125000,
        2,
        "Meet at Seraphim Station.",
    )

    assert "**WTB listing by <@123>**" in content
    assert "**Price:** 125,000 aUEC" in content
    assert "**Quantity:** 2" in content
    assert "Meet at Seraphim Station." in content

    assert _trade_seller_terms(content) == (
        "**Price:** 125,000 aUEC\n"
        "**Quantity:** 2\n"
        "**Notes:** Meet at Seraphim Station."
    )


def test_trade_item_embed_displays_seller_terms() -> None:
    item = TradeItemResult(
        uuid="item-2",
        name="FS-9 LMG",
        category="Medium",
        manufacturer="Behring Applied Technology",
        size="4",
        description="A light machine gun.",
        image_url=None,
        wiki_url="https://example.com/wiki",
        uex_url="https://example.com/uex",
    )
    terms = "**Price:** 75,000 aUEC\n**Quantity:** 1\n**Notes:** Includes ammunition."

    embed = build_trading_item_embed(item, "WTS", terms)

    seller_field = next(field for field in embed.fields if field.name == "Seller's terms")
    assert seller_field.value == terms
