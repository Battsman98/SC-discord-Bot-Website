import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int | None
    command_prefix: str
    database_path: str
    http_timeout_seconds: int
    cache_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        discord_token = os.getenv("DISCORD_TOKEN", "").strip()
        if not discord_token or discord_token == "replace-with-your-discord-bot-token":
            raise RuntimeError("DISCORD_TOKEN is required. Add it to your .env file.")

        guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()

        return cls(
            discord_token=discord_token,
            discord_guild_id=int(guild_id) if guild_id else None,
            command_prefix=os.getenv("BOT_COMMAND_PREFIX", "!"),
            database_path=os.getenv("DATABASE_PATH", "data/bot.sqlite3"),
            http_timeout_seconds=int(os.getenv("HTTP_TIMEOUT_SECONDS", "15")),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "300")),
        )
