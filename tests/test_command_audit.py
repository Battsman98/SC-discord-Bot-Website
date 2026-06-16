from types import SimpleNamespace

from src.bot import build_command_channel_directory_embed, _format_interaction_options, _interaction_command_name
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
        discord_guild_id=123,
        commands_channel_id=456,
        exec_status_channel_id=None,
        exec_admin_role_ids=(),
        bot_admin_role_ids=(),
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
