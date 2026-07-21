import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from src.bot import (
    build_inventory_search_embed,
    build_command_channel_directory_embed,
    GameAssistBot,
    INVENTORY_CHANNEL_ID,
    _format_interaction_options,
    _interaction_command_name,
    _message_embed_matches,
    inventory_group,
)
from src.config import Settings


def test_interaction_command_name_handles_grouped_commands() -> None:
    interaction = SimpleNamespace(
        data={
            "name": "trade",
            "options": [
                {
                    "name": "routing",
                    "type": 1,
                    "options": [{"name": "starting_point", "value": "ARC-L3"}],
                }
            ],
        }
    )

    assert _interaction_command_name(interaction) == "trade routing"


def test_format_interaction_options_flattens_subcommand_options() -> None:
    interaction = SimpleNamespace(
        data={
            "name": "item",
            "options": [
                {
                    "name": "locator",
                    "type": 1,
                    "options": [
                        {"name": "category", "value": "Quantum Drives"},
                        {"name": "size", "value": 1},
                    ],
                }
            ],
        }
    )

    assert _interaction_command_name(interaction) == "item locator"
    assert _format_interaction_options(interaction) == "locator.category: Quantum Drives\nlocator.size: 1"


def test_command_channel_directory_groups_commands_by_channel() -> None:
    settings = Settings(
        discord_token="token",
        discord_client_id="",
        discord_client_secret="",
        discord_redirect_uri="http://127.0.0.1:8000/auth/discord/callback",
        discord_guild_id=123,
        commands_channel_id=456,
        exec_status_channel_id=None,
        exec_admin_role_ids=(),
        bot_admin_role_ids=(),
        bot_admin_user_ids=(),
        cz_timers_channel_id=None,
        audit_log_channel_id=None,
        command_channel_ids={
            "ship": 111,
            "commodity": 222,
            "trade routing": 222,
        },
        command_prefix="!",
        database_path="data/test.sqlite3",
        http_timeout_seconds=15,
        cache_ttl_seconds=300,
    )

    embed = build_command_channel_directory_embed(settings)

    assert "<#111>: /ship" in embed.description
    assert "<#222>: /commodity, /trade routing" in embed.description
    assert f"<#{INVENTORY_CHANNEL_ID}>: /inventory search" in embed.description


def test_message_embed_matches_existing_embed_payload() -> None:
    embed = discord.Embed(title="Discord Bot Commands - /mining", description="Mining help")
    message = SimpleNamespace(embeds=[embed])

    assert _message_embed_matches(message, embed)

    changed_embed = discord.Embed(title="Discord Bot Commands - /mining", description="Updated help")
    assert not _message_embed_matches(message, changed_embed)


def test_inventory_search_command_is_registered() -> None:
    assert inventory_group.get_command("search") is not None
    assert INVENTORY_CHANNEL_ID == 1528623944947597383


def test_inventory_search_embed_shows_station_and_item_metadata() -> None:
    embed = build_inventory_search_embed(
        [
            {
                "name": "250-E Laser Pointer",
                "location": "Everus Harbor",
                "quantity": 3,
                "category": "Personal Weapons",
                "item_type": "Attachments",
                "item_size": "1",
            }
        ],
        station="Everus Harbor",
        item_type="Attachments",
    )

    assert "Station: Everus Harbor" in embed.description
    assert "250-E Laser Pointer" in embed.description
    assert "250-E Laser Pointer** × 3 — Everus Harbor" not in embed.description
    assert "Personal Weapons / Attachments / Size 1" in embed.description
    assert "Showing 1 of 1 matching item" in embed.footer.text


def test_inventory_search_embed_keeps_locations_without_station_filter() -> None:
    embed = build_inventory_search_embed(
        [{"name": "FS-9 LMG", "location": "Port Tressler", "quantity": 1}]
    )

    assert "FS-9 LMG** × 1 — Port Tressler" in embed.description


def test_autocomplete_skips_synchronous_command_auditing() -> None:
    settings = Settings(
        discord_token="token",
        discord_client_id="",
        discord_client_secret="",
        discord_redirect_uri="http://127.0.0.1:8000/auth/discord/callback",
        discord_guild_id=123,
        commands_channel_id=None,
        exec_status_channel_id=None,
        exec_admin_role_ids=(),
        bot_admin_role_ids=(),
        bot_admin_user_ids=(),
        cz_timers_channel_id=None,
        audit_log_channel_id=456,
        command_channel_ids={},
        command_prefix="!",
        database_path="data/test.sqlite3",
        http_timeout_seconds=15,
        cache_ttl_seconds=300,
    )
    cache = SimpleNamespace(close=AsyncMock())
    sources = SimpleNamespace(close=AsyncMock())
    bot = GameAssistBot(settings, cache, sources)
    bot.log_audit_event = AsyncMock()
    interaction = SimpleNamespace(type=discord.InteractionType.autocomplete)

    assert asyncio.run(bot.tree.interaction_check(interaction))
    bot.log_audit_event.assert_not_awaited()
