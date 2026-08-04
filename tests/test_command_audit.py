import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from src.config import Settings
from src.bot import (
    build_inventory_search_embed,
    build_command_channel_directory_embed,
    GameAssistBot,
    INVENTORY_CHANNEL_ID,
    _allowed_command_channel_id,
    _format_interaction_options,
    _interaction_command_name,
    _message_embed_matches,
    _message_records_deployment,
    _deployment_targets_for_files,
    _hub_role_permissions,
    admin_group,
    inventory_group,
    industry_group,
)


def test_deployment_changelog_targets_match_changed_application() -> None:
    assert _deployment_targets_for_files(["src/bot.py", "docs/commands.md"]) == {"discord-changelog"}
    assert _deployment_targets_for_files(["src/web.py", "web/app.js"]) == {"website-changelog"}
    assert _deployment_targets_for_files(["src/bot.py", "web/app.js"]) == {
        "discord-changelog",
        "website-changelog",
    }
    # Unknown files remain a conservative both-target fallback, but production
    # now queries GitHub before reaching it when Render omits local Git history.
    assert _deployment_targets_for_files([]) == {"discord-changelog", "website-changelog"}


def test_deployment_history_entry_deduplicates_a_revision() -> None:
    message = SimpleNamespace(
        embeds=[
            discord.Embed(
                title="Website deployed",
                description="Revision: `123456789abc`",
            )
        ]
    )

    assert _message_records_deployment(message, "123456789abcdef")
    assert not _message_records_deployment(message, "fedcba987654321")
    assert not _message_records_deployment(
        SimpleNamespace(embeds=[discord.Embed(title="Discord channel updated", description="123456789abc")]),
        "123456789abcdef",
    )


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
            "blueprint": 333,
        },
        command_prefix="!",
        database_path="data/test.sqlite3",
        http_timeout_seconds=15,
        cache_ttl_seconds=300,
    )

    embed = build_command_channel_directory_embed(settings)

    assert "<#111>: /ship" in embed.description
    assert "<#222>: /commodity, /trade routing" in embed.description
    assert "<#333>: /blueprint, /mission, /myblueprints" in embed.description
    assert f"<#{INVENTORY_CHANNEL_ID}>: /inventory search" in embed.description


def test_message_embed_matches_existing_embed_payload() -> None:
    embed = discord.Embed(title="Discord Bot Commands - /mining", description="Mining help")
    message = SimpleNamespace(embeds=[embed])

    assert _message_embed_matches(message, embed)

    changed_embed = discord.Embed(title="Discord Bot Commands - /mining", description="Updated help")
    assert not _message_embed_matches(message, changed_embed)


def test_only_cached_bot_hub_messages_are_protected() -> None:
    async def scenario() -> None:
        bot = GameAssistBot.__new__(GameAssistBot)
        bot.visitor_channels = {"bot-commands": 123}
        bot.cache = SimpleNamespace(get=AsyncMock(side_effect=lambda key: [456, 789] if "commands-reference" in key else None))

        assert await bot._is_protected_hub_message(123, 789)
        assert not await bot._is_protected_hub_message(123, 999)
        assert not await bot._is_protected_hub_message(321, 789)

    asyncio.run(scenario())


def test_hub_admin_commands_are_registered() -> None:
    assert admin_group.get_command("hub-health") is not None
    assert admin_group.get_command("hub-repair") is not None


def test_hub_roles_have_scoped_permissions() -> None:
    visitor = _hub_role_permissions("Visitor")
    manager = _hub_role_permissions("Bot Manager")

    assert visitor.view_channel and visitor.connect and visitor.use_application_commands
    assert manager.view_channel and manager.send_messages
    assert not manager.manage_guild
    assert not visitor.administrator


def test_inventory_search_command_is_registered() -> None:
    assert inventory_group.get_command("search") is not None
    assert INVENTORY_CHANNEL_ID == 1533075934603772004


def test_mission_command_uses_blueprint_channel_by_default() -> None:
    bot = SimpleNamespace(
        settings=SimpleNamespace(command_channel_ids={"blueprint": 2468}),
        inventory_channel_id=INVENTORY_CHANNEL_ID,
    )

    assert _allowed_command_channel_id(bot, "mission") == 2468
    assert _allowed_command_channel_id(bot, "myblueprints") == 2468


def test_visitor_hub_channel_replaces_legacy_command_channel() -> None:
    bot = SimpleNamespace(
        settings=SimpleNamespace(command_channel_ids={"ship": 2468}),
        inventory_channel_id=INVENTORY_CHANNEL_ID,
        visitor_channels={"ship-search": 1357},
    )

    assert GameAssistBot.allowed_command_channel_ids(bot, "ship") == {1357}


def test_industry_planning_commands_are_registered() -> None:
    assert industry_group.get_command("split") is not None
    assert industry_group.get_command("refinery") is not None
    assert industry_group.get_command("brief") is not None


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


def test_discord_audit_is_saved_when_channel_is_not_configured() -> None:
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
        audit_log_channel_id=None,
        command_channel_ids={},
        command_prefix="!",
        database_path="data/test.sqlite3",
        http_timeout_seconds=15,
        cache_ttl_seconds=300,
    )
    cache = SimpleNamespace(add_audit_event=AsyncMock(), close=AsyncMock())
    sources = SimpleNamespace(close=AsyncMock())
    bot = GameAssistBot(settings, cache, sources)

    asyncio.run(bot.log_audit_event("Command Used", {"Command": "/mining"}))

    cache.add_audit_event.assert_awaited_once_with("Command Used", {"Command": "/mining"})
