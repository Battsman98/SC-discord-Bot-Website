import logging

import discord
from discord import app_commands
from discord.ext import commands

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.registry import SourceRegistry, build_default_registry


class GameAssistBot(commands.Bot):
    def __init__(self, settings: Settings, cache: SQLiteCache, sources: SourceRegistry) -> None:
        intents = discord.Intents.default()
        intents.message_content = False

        super().__init__(
            command_prefix=settings.command_prefix,
            intents=intents,
            help_command=None,
        )
        self.settings = settings
        self.cache = cache
        self.sources = sources

    async def setup_hook(self) -> None:
        self.tree.add_command(status_command)
        self.tree.add_command(lookup_command)

        if self.settings.discord_guild_id:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logging.info("Synced slash commands to guild %s", self.settings.discord_guild_id)
        else:
            await self.tree.sync()
            logging.info("Synced global slash commands")

    async def close(self) -> None:
        await self.sources.close()
        await self.cache.close()
        await super().close()


@app_commands.command(name="status", description="Check whether the assistance bot is online.")
async def status_command(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Online and ready.", ephemeral=True)


@app_commands.command(name="lookup", description="Search configured game information sources.")
@app_commands.describe(query="The item, quest, enemy, location, or topic to search for.")
async def lookup_command(interaction: discord.Interaction, query: str) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    result = await bot.sources.lookup(query)

    if result is None:
        await interaction.followup.send(f"No result found for `{query}`.")
        return

    embed = discord.Embed(
        title=result.title,
        description=result.summary,
        url=result.url,
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"Source: {result.source_name}")
    await interaction.followup.send(embed=embed)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    cache = await SQLiteCache.create(settings.database_path)
    sources = await build_default_registry(settings, cache)

    async with GameAssistBot(settings, cache, sources) as bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
