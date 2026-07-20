from types import SimpleNamespace

import discord

from src.bot import (
    build_command_channel_directory_embed,
    _format_interaction_options,
    _interaction_command_name,
    _message_embed_matches,
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


def test_message_embed_matches_existing_embed_payload() -> None:
    embed = discord.Embed(title="Discord Bot Commands - /mining", description="Mining help")
    message = SimpleNamespace(embeds=[embed])

    assert _message_embed_matches(message, embed)

    changed_embed = discord.Embed(title="Discord Bot Commands - /mining", description="Updated help")
    assert not _message_embed_matches(message, changed_embed)
