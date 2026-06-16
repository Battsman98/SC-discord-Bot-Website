import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int | None
    commands_channel_id: int | None
    exec_status_channel_id: int | None
    exec_admin_role_ids: tuple[int, ...]
    bot_admin_role_ids: tuple[int, ...]
    cz_timers_channel_id: int | None
    audit_log_channel_id: int | None
    command_channel_ids: dict[str, int]
    command_prefix: str
    database_path: str
    http_timeout_seconds: int
    cache_ttl_seconds: int

    @classmethod
    def from_env(cls, load_env_file: bool = True) -> "Settings":
        if load_env_file:
            load_dotenv()

        discord_token = os.getenv("DISCORD_TOKEN", "").strip()
        if not discord_token or discord_token == "replace-with-your-discord-bot-token":
            raise RuntimeError("DISCORD_TOKEN is required. Add it to your .env file.")

        guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
        commands_channel_id = os.getenv("COMMANDS_CHANNEL_ID", "").strip()
        exec_status_channel_id = os.getenv("EXEC_STATUS_CHANNEL_ID", "").strip()
        cz_timers_channel_id = os.getenv("CZ_TIMERS_CHANNEL_ID", "").strip()
        audit_log_channel_id = os.getenv("AUDIT_LOG_CHANNEL_ID", "").strip()
        exec_admin_role_ids = tuple(
            int(role_id.strip())
            for role_id in os.getenv("EXEC_ADMIN_ROLE_IDS", "").split(",")
            if role_id.strip()
        )
        bot_admin_role_ids = tuple(
            int(role_id.strip())
            for role_id in os.getenv("BOT_ADMIN_ROLE_IDS", "").split(",")
            if role_id.strip()
        )

        return cls(
            discord_token=discord_token,
            discord_guild_id=int(guild_id) if guild_id else None,
            commands_channel_id=int(commands_channel_id) if commands_channel_id else None,
            exec_status_channel_id=int(exec_status_channel_id) if exec_status_channel_id else None,
            exec_admin_role_ids=exec_admin_role_ids,
            bot_admin_role_ids=bot_admin_role_ids,
            cz_timers_channel_id=int(cz_timers_channel_id) if cz_timers_channel_id else None,
            audit_log_channel_id=int(audit_log_channel_id) if audit_log_channel_id else None,
            command_channel_ids=_parse_command_channel_ids(os.getenv("COMMAND_CHANNEL_IDS", "")),
            command_prefix=os.getenv("BOT_COMMAND_PREFIX", "!"),
            database_path=os.getenv("DATABASE_PATH", "data/bot.sqlite3"),
            http_timeout_seconds=int(os.getenv("HTTP_TIMEOUT_SECONDS", "15")),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "300")),
        )


def _parse_command_channel_ids(value: str) -> dict[str, int]:
    channel_ids: dict[str, int] = {}
    for item in value.replace("\n", ",").replace(";", ",").split(","):
        if not item.strip():
            continue
        separator = "=" if "=" in item else ":"
        if separator not in item:
            continue
        command_name, channel_id = item.split(separator, 1)
        command_name = _normalize_command_name(command_name)
        channel_id = channel_id.strip()
        if command_name and channel_id:
            channel_ids[command_name] = int(channel_id)
    return channel_ids


def _normalize_command_name(value: str) -> str:
    return " ".join(value.lower().strip().removeprefix("/").replace("_", " ").split())
