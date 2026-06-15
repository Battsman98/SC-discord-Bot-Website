import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import CommodityMarket, CommodityResult, ShipResult
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
        self._commands_reference_synced = False

    async def setup_hook(self) -> None:
        self.tree.add_command(status_command)
        self.tree.add_command(lookup_command)
        self.tree.add_command(ship_command)
        self.tree.add_command(commodity_command)

        if self.settings.discord_guild_id:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logging.info("Synced slash commands to guild %s", self.settings.discord_guild_id)
        else:
            await self.tree.sync()
            logging.info("Synced global slash commands")

    async def on_ready(self) -> None:
        if self._commands_reference_synced:
            return

        self._commands_reference_synced = True
        await self.sync_commands_reference_message()

    async def sync_commands_reference_message(self) -> None:
        if not self.settings.commands_channel_id:
            return

        try:
            channel = await self.fetch_channel(self.settings.commands_channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logging.warning("Could not access COMMANDS_CHANNEL_ID %s", self.settings.commands_channel_id)
            return

        if not isinstance(channel, discord.abc.Messageable) or not hasattr(channel, "fetch_message"):
            logging.warning("COMMANDS_CHANNEL_ID does not point to a messageable channel")
            return

        embeds = build_commands_reference_embeds()
        cache_key = f"discord:commands-reference-message:{self.settings.commands_channel_id}"
        message_id = await self.cache.get(cache_key)

        if isinstance(message_id, int):
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(content=None, embeds=embeds)
                logging.info("Updated commands reference message %s", message_id)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logging.info("Could not update previous commands reference message; creating a new one")

        message = await channel.send(embeds=embeds)
        await self.cache.set(cache_key, message.id, 315360000)
        logging.info("Created commands reference message %s", message.id)

    async def close(self) -> None:
        await self.sources.close()
        await self.cache.close()
        await super().close()


@app_commands.command(name="status", description="Check whether the assistance bot is online.")
async def status_command(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Online and ready.", ephemeral=True)


@app_commands.command(name="lookup", description="Search Star Citizen game information.")
@app_commands.describe(query="The ship, item, location, mission, company, or topic to search for.")
async def lookup_command(interaction: discord.Interaction, query: str) -> None:
    await send_lookup(interaction, query)


@app_commands.command(name="ship", description="Look up a Star Citizen ship or vehicle.")
@app_commands.describe(name="The ship or vehicle name to search for.")
async def ship_command(interaction: discord.Interaction, name: str) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    result = await bot.sources.lookup_ship(name)

    if result is None:
        await interaction.followup.send(f"No ship or vehicle found for `{name}`.", ephemeral=True)
        return

    await interaction.followup.send(embed=build_ship_embed(result), ephemeral=True)


@ship_command.autocomplete("name")
async def ship_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        return []

    names = await bot.sources.autocomplete_ships(current)
    return [
        app_commands.Choice(name=name[:100], value=name[:100])
        for name in names[:25]
    ]


@app_commands.command(name="commodity", description="Look up Star Citizen commodity prices and locations.")
@app_commands.describe(
    name="The commodity name to search for.",
    system="Optional star system filter for both purchase and sell locations.",
    purchase_system="Optional system filter for purchase locations only.",
    sell_system="Optional system filter for sell locations only.",
    quantity_scu="Optional SCU amount for estimated buy cost and sell payout.",
)
async def commodity_command(
    interaction: discord.Interaction,
    name: str,
    system: str | None = None,
    purchase_system: str | None = None,
    sell_system: str | None = None,
    quantity_scu: float | None = None,
) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    if quantity_scu is not None and quantity_scu <= 0:
        await interaction.response.send_message("Quantity must be greater than 0 SCU.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    result = await bot.sources.lookup_commodity(name, system, purchase_system, sell_system)

    if result is None:
        await interaction.followup.send(f"No commodity found for `{name}`.", ephemeral=True)
        return

    await interaction.followup.send(
        embed=build_commodity_embed(result, quantity_scu, system, purchase_system, sell_system),
        ephemeral=True,
    )


@commodity_command.autocomplete("name")
async def commodity_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        return []

    names = await bot.sources.autocomplete_commodities(current)
    return [
        app_commands.Choice(name=name[:100], value=name[:100])
        for name in names[:25]
    ]


@commodity_command.autocomplete("system")
@commodity_command.autocomplete("purchase_system")
@commodity_command.autocomplete("sell_system")
async def commodity_system_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    del interaction
    systems = ["Stanton", "Pyro", "Nyx"]
    normalized = current.lower().strip()
    matches = [system for system in systems if system.lower().startswith(normalized)]
    if not matches and normalized:
        matches = [system for system in systems if normalized in system.lower()]
    return [app_commands.Choice(name=system, value=system) for system in matches[:25]]


async def send_lookup(interaction: discord.Interaction, query: str) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    result = await bot.sources.lookup(query)

    if result is None:
        await interaction.followup.send(f"No result found for `{query}`.", ephemeral=True)
        return

    embed = discord.Embed(
        title=result.title,
        description=result.summary,
        url=result.url,
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"Source: {result.source_name}")
    await interaction.followup.send(embed=embed, ephemeral=True)


def build_ship_embed(result: ShipResult) -> discord.Embed:
    embed = discord.Embed(
        title=result.name,
        description=result.description or "No basic description available.",
        url=result.source_url,
        color=discord.Color.dark_teal(),
    )

    overview = [
        _line("Manufacturer", result.manufacturer),
        _line("Type", result.vehicle_type),
        _line("Role", result.role),
        _line("Size", result.size),
        _line("Status", result.status),
    ]
    embed.add_field(name="Overview", value="\n".join(line for line in overview if line) or "Unknown", inline=False)

    specs = [
        _line("Cargo", f"{_format_number(result.cargo_capacity)} SCU" if result.cargo_capacity is not None else None),
        _line("Crew", str(result.crew) if result.crew is not None else None),
    ]
    embed.add_field(name="Specs", value="\n".join(line for line in specs if line) or "Unknown", inline=False)

    embed.add_field(name="Pledge Store", value=_format_pledge(result), inline=False)
    embed.add_field(name="In-Game Purchase", value=_format_purchases(result), inline=False)
    embed.set_footer(text=f"Source: {result.source_name} + UEX pledge/pricing data")
    return embed


def build_commodity_embed(
    result: CommodityResult,
    quantity_scu: float | None = None,
    system: str | None = None,
    purchase_system: str | None = None,
    sell_system: str | None = None,
) -> discord.Embed:
    purchase_filter = purchase_system or system
    sell_filter = sell_system or system
    description = [
        _line("Code", result.code),
        _line("Purchase System", purchase_filter),
        _line("Sell System", sell_filter),
    ]

    embed = discord.Embed(
        title=result.name,
        description="\n".join(line for line in description if line),
        url=result.wiki_url,
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="Purchase Locations",
        value=_format_markets(result.buy_from),
        inline=False,
    )
    embed.add_field(
        name="Sell Locations",
        value=_format_markets(result.sell_to),
        inline=False,
    )
    if quantity_scu is not None:
        embed.add_field(
            name=f"Estimate for {_format_number(quantity_scu)} SCU",
            value=_format_commodity_estimate(result, quantity_scu),
            inline=False,
        )
    embed.set_footer(text=f"Source: {result.source_name}")
    return embed


def build_commands_reference_embeds() -> list[discord.Embed]:
    reference_path = Path("docs/commands.md")
    markdown = reference_path.read_text(encoding="utf-8").strip()
    if markdown.startswith("# Discord Bot Commands"):
        markdown = markdown.removeprefix("# Discord Bot Commands").strip()
    chunks = _chunk_text(markdown, 3500)
    embeds = []

    for index, chunk in enumerate(chunks):
        embed = discord.Embed(
            title="Discord Bot Commands" if index == 0 else f"Discord Bot Commands Continued {index + 1}",
            description=chunk,
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Auto-updated from docs/commands.md when the bot starts")
        embeds.append(embed)

    return embeds


def _chunk_text(text: str, max_length: int) -> list[str]:
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_length:
            current = candidate
            continue

        if current:
            chunks.append(current)
        current = paragraph

    if current:
        chunks.append(current)

    return chunks


def _format_markets(markets: list[CommodityMarket]) -> str:
    if not markets:
        return "No current locations found."

    lines = []
    for index, market in enumerate(markets, start=1):
        system = market.system or "Unknown"
        planet = market.planet or "Unknown"
        location = market.location or market.terminal_name
        demand = f"{_format_number(market.demand)} SCU" if market.demand is not None else "Unknown"
        line = (
            f"{index}. {_format_currency(market.price, 'aUEC')}/SCU avg | "
            f"System: {system} | Planet: {planet} | Location: {location} | Demand: {demand}"
        )
        candidate = "\n".join([*lines, line])
        if len(candidate) > 1000:
            lines.append("More locations available in UEX.")
            break
        lines.append(line)
    return "\n".join(lines)


def _format_commodity_estimate(result: CommodityResult, quantity_scu: float) -> str:
    lines = []
    if result.buy_from:
        purchase = result.buy_from[0]
        lines.append(
            f"Estimated buy cost: {_format_currency(purchase.price * quantity_scu, 'aUEC')} "
            f"at {purchase.location or purchase.terminal_name}"
        )
    else:
        lines.append("Estimated buy cost: No purchase location found.")

    if result.sell_to:
        sale = result.sell_to[0]
        lines.append(
            f"Estimated sell payout: {_format_currency(sale.price * quantity_scu, 'aUEC')} "
            f"at {sale.location or sale.terminal_name}"
        )
    else:
        lines.append("Estimated sell payout: No sell location found.")

    return "\n".join(lines)


def _format_pledge(result: ShipResult) -> str:
    pledge = result.pledge
    if pledge is None:
        return "No pledge store data found."

    lines = []
    if pledge.is_on_sale is True:
        lines.append("Availability: Available")
    elif pledge.is_on_sale is False:
        lines.append("Availability: Not currently listed as on sale")
    else:
        lines.append("Availability: Unknown")

    if pledge.price is not None:
        lines.append(f"Pledge price: {_format_currency(pledge.price, pledge.currency)}")
    if pledge.warbond_price is not None:
        lines.append(f"Warbond: {_format_currency(pledge.warbond_price, pledge.currency)}")
    if pledge.package_price is not None:
        lines.append(f"Package: {_format_currency(pledge.package_price, pledge.currency)}")
    if pledge.pledge_url:
        lines.append(f"[Open pledge page]({pledge.pledge_url})")
    else:
        lines.append("[Open RSI pledge store](https://robertsspaceindustries.com/en/pledge)")

    return "\n".join(lines)


def _format_purchases(result: ShipResult) -> str:
    if not result.purchases:
        return "No in-game purchase locations found."

    lines = []
    for purchase in result.purchases:
        terminal = purchase.terminal_name
        if purchase.uex_link:
            terminal = f"[{terminal}]({purchase.uex_link})"
        location = f" - {purchase.location}" if purchase.location else ""
        lines.append(f"{_format_currency(purchase.price, 'aUEC')} at {terminal}{location}")
    return "\n".join(lines)


def _line(label: str, value: str | None) -> str | None:
    return f"{label}: {value}" if value else None


def _format_currency(value: int | float, currency: str) -> str:
    amount = _format_number(value)
    if currency == "aUEC":
        return f"{amount} aUEC"
    if currency == "USD":
        return f"${amount} USD"
    return f"{amount} {currency}"


def _format_number(value: int | float | None) -> str:
    if value is None:
        return "Unknown"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}"
    return f"{int(value):,}"


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
