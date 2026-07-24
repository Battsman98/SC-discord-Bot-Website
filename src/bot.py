import logging
import asyncio
import re
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import (
    BlueprintIngredient,
    BlueprintMission,
    BlueprintResult,
    CommodityMarket,
    CommodityResult,
    ItemLocatorResult,
    ItemPurchaseLocation,
    MiningLocationResult,
    MiningSystemLocations,
    MissionResult,
    ShipResult,
    TradeRouteLeg,
    TradeRouteResult,
)
from src.sources.registry import SourceRegistry, build_default_registry
from src.timers import (
    ExecHangarStatus,
    calculate_countdown_end_unix,
    calculate_cycle_start_from_phase,
    calculate_exec_hangar_status,
    fetch_exec_cycle_start_unix,
)


EXEC_OVERRIDE_CACHE_KEY = "exec:cycle-start-override"
CZ_TIMERS_CACHE_KEY = "cz:dashboard:timers"
BLUEPRINT_PAGE_SIZE = 25
BLUEPRINT_MISSION_LINES_PER_PAGE = 25
MINING_LOCATION_LINES_PER_PAGE = 25
MINING_COMMUNITY_LOCATIONS_CACHE_KEY = "mining:community-locations:v1"
CZ_TIMER_DEFINITIONS = {
    "blue_keycard": ("Blue Keycards", 15 * 60),
    "compboard": ("Compboards / Tablets", 30 * 60),
    "red_keycard": ("Red Keycards", 30 * 60),
    "timer_door": ("Timer Doors", 20 * 60),
}
INVENTORY_CHANNEL_ID = 1528623944947597383


class GameAssistCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        bot = self.client
        if not isinstance(bot, GameAssistBot):
            return True

        if interaction.type == discord.InteractionType.autocomplete:
            return True

        command_name = _interaction_command_name(interaction)
        allowed_channel_id = _allowed_command_channel_id(bot, command_name)
        if allowed_channel_id and interaction.channel_id != allowed_channel_id:
            await interaction.response.send_message(
                f"`/{command_name}` can only be used in <#{allowed_channel_id}>.",
                ephemeral=True,
            )
            asyncio.create_task(
                bot.log_audit_event(
                    "Command Blocked",
                    {
                        "Command": f"/{command_name}",
                        "User": _audit_user(interaction.user),
                        "Used In": _audit_channel(interaction.channel_id),
                        "Allowed Channel": f"<#{allowed_channel_id}>",
                        "Options": _format_interaction_options(interaction) or "None",
                    },
                    color=discord.Color.red(),
                )
            )
            return False

        asyncio.create_task(
            bot.log_audit_event(
                "Command Used",
                {
                    "Command": f"/{command_name}",
                    "User": _audit_user(interaction.user),
                    "Channel": _audit_channel(interaction.channel_id),
                    "Options": _format_interaction_options(interaction) or "None",
                },
            )
        )
        return True

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        logging.error(
            "Application command failed: %s",
            _interaction_command_name(interaction),
            exc_info=(type(original), original, original.__traceback__),
        )
        try:
            if interaction.type == discord.InteractionType.autocomplete:
                if not interaction.response.is_done():
                    await interaction.response.autocomplete([])
                return
            message = "That command encountered an error. Please try again in a moment."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logging.warning("Could not send application-command error response")


def _allowed_command_channel_id(bot: "GameAssistBot", command_name: str) -> int | None:
    allowed_channel_id = bot.settings.command_channel_ids.get(command_name)
    if allowed_channel_id is None and command_name == "mission":
        allowed_channel_id = bot.settings.command_channel_ids.get("blueprint")
    if allowed_channel_id is None and command_name == "item search":
        allowed_channel_id = bot.settings.command_channel_ids.get("item locator")
    if command_name == "inventory search" and bot.inventory_channel_id:
        allowed_channel_id = bot.inventory_channel_id
    return allowed_channel_id


class GameAssistBot(commands.Bot):
    def __init__(self, settings: Settings, cache: SQLiteCache, sources: SourceRegistry) -> None:
        intents = discord.Intents.default()
        intents.message_content = False

        super().__init__(
            command_prefix=settings.command_prefix,
            intents=intents,
            help_command=None,
            tree_cls=GameAssistCommandTree,
        )
        self.settings = settings
        self.cache = cache
        self.sources = sources
        self.started_at_unix = int(discord.utils.utcnow().timestamp())
        self._commands_reference_synced = False
        self.inventory_channel_id: int = INVENTORY_CHANNEL_ID
        self._exec_status_task: asyncio.Task | None = None
        self._cz_timers_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        self.add_view(CZTimerDashboardView())
        self.tree.add_command(status_command)
        self.tree.add_command(lookup_command)
        self.tree.add_command(ship_command)
        self.tree.add_command(commodity_command)
        self.tree.add_command(mining_command)
        self.tree.add_command(industry_group)
        self.tree.add_command(miningadd_command)
        self.tree.add_command(blueprint_command)
        self.tree.add_command(mission_command)
        self.tree.add_command(item_group)
        self.tree.add_command(inventory_group)
        self.tree.add_command(exec_command)
        self.tree.add_command(execset_command)
        self.tree.add_command(execclear_command)
        self.tree.add_command(cztimer_command)
        self.tree.add_command(trade_group)
        self.tree.add_command(admin_group)
        self.tree.add_command(audit_group)

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
        await self.ensure_inventory_search_channel()
        await self.sync_commands_reference_message()
        await self.sync_exec_status_message()
        await self.sync_cz_timers_message()

        if self.settings.exec_status_channel_id and self._exec_status_task is None:
            self._exec_status_task = asyncio.create_task(self._exec_status_loop())
        if self.settings.cz_timers_channel_id and self._cz_timers_task is None:
            self._cz_timers_task = asyncio.create_task(self._cz_timers_loop())

    async def ensure_inventory_search_channel(self) -> None:
        try:
            channel = self.get_channel(INVENTORY_CHANNEL_ID) or await self.fetch_channel(INVENTORY_CHANNEL_ID)
            if not isinstance(channel, discord.TextChannel):
                logging.error("INVENTORY_CHANNEL_ID %s is not a Discord text channel", INVENTORY_CHANNEL_ID)
                return
            if self.settings.discord_guild_id and channel.guild.id != self.settings.discord_guild_id:
                logging.error("INVENTORY_CHANNEL_ID %s is not in the configured guild", INVENTORY_CHANNEL_ID)
                return
            logging.info("Inventory search restricted to Discord channel %s", INVENTORY_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logging.exception("Could not access inventory search channel %s", INVENTORY_CHANNEL_ID)

    async def _exec_status_loop(self) -> None:
        while not self.is_closed():
            await asyncio.sleep(60)
            await self.sync_exec_status_message()

    async def _cz_timers_loop(self) -> None:
        while not self.is_closed():
            await asyncio.sleep(60)
            await self.sync_cz_timers_message()

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

        embeds = build_commands_reference_embeds(self.settings)
        cache_key = f"discord:commands-reference-message:{self.settings.commands_channel_id}"
        cached_message_ids = await self.cache.get(cache_key)
        message_ids: list[int] = []
        if isinstance(cached_message_ids, int):
            message_ids = [cached_message_ids]
        elif isinstance(cached_message_ids, list):
            message_ids = [message_id for message_id in cached_message_ids if isinstance(message_id, int)]

        existing_messages = await self.find_recent_embed_messages(
            channel,
            {embed.title for embed in embeds if embed.title},
            limit=250,
        )
        updated_message_ids: list[int] = []
        for index, embed in enumerate(embeds):
            message = None
            if index < len(message_ids):
                try:
                    message = await channel.fetch_message(message_ids[index])
                    if not any(message_embed.title == embed.title for message_embed in message.embeds):
                        message = None
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    logging.info(
                        "Could not update commands reference message part %s; searching for an existing one",
                        index + 1,
                    )

            if message is None and embed.title:
                matching_messages = existing_messages.get(embed.title, [])
                if matching_messages:
                    message = matching_messages[0]

            if message is not None:
                if not _message_embed_matches(message, embed) or message.content:
                    await message.edit(content=None, embed=embed)
                    await asyncio.sleep(1)
                updated_message_ids.append(message.id)
                if embed.title:
                    await self.delete_recent_duplicate_embed_messages(channel, embed.title, message.id, limit=250)
                continue

            message = await channel.send(embed=embed)
            await asyncio.sleep(1)
            updated_message_ids.append(message.id)
            if embed.title:
                await self.delete_recent_duplicate_embed_messages(channel, embed.title, message.id, limit=250)

        for stale_message_id in message_ids[len(embeds):]:
            try:
                message = await channel.fetch_message(stale_message_id)
                await message.delete()
                await asyncio.sleep(1)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logging.info("Could not delete stale commands reference message %s", stale_message_id)

        await self.cache.set(cache_key, updated_message_ids, 315360000)
        logging.info("Synced %s commands reference message(s)", len(updated_message_ids))

    async def sync_exec_status_message(self) -> None:
        if not self.settings.exec_status_channel_id:
            return

        try:
            channel = await self.fetch_channel(self.settings.exec_status_channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logging.warning("Could not access EXEC_STATUS_CHANNEL_ID %s", self.settings.exec_status_channel_id)
            return

        if not isinstance(channel, discord.abc.Messageable) or not hasattr(channel, "fetch_message"):
            logging.warning("EXEC_STATUS_CHANNEL_ID does not point to a messageable channel")
            return

        try:
            status_context = await self.resolve_exec_status_context()
        except Exception:
            logging.warning("Could not fetch Executive Hangar timer for status message")
            return

        embed = build_exec_status_embed(status_context)
        cache_key = f"discord:exec-status-message:{self.settings.exec_status_channel_id}"
        message_id = await self.cache.get(cache_key)

        if isinstance(message_id, int):
            try:
                message = await channel.fetch_message(message_id)
                if not _message_embed_matches(message, embed) or message.content:
                    await message.edit(content=None, embed=embed)
                await self.delete_recent_duplicate_embed_messages(channel, "Executive Hangar Clock", message.id)
                logging.info("Updated Executive Hangar status message %s", message_id)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logging.info("Could not update previous Executive Hangar status message; searching for an existing one")

        existing_message = await self.find_recent_embed_message(channel, "Executive Hangar Clock")
        if existing_message is not None:
            try:
                if not _message_embed_matches(existing_message, embed) or existing_message.content:
                    await existing_message.edit(content=None, embed=embed)
                await self.cache.set(cache_key, existing_message.id, 315360000)
                await self.delete_recent_duplicate_embed_messages(channel, "Executive Hangar Clock", existing_message.id)
                logging.info("Reused Executive Hangar status message %s", existing_message.id)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logging.info("Could not reuse existing Executive Hangar status message; creating a new one")

        message = await channel.send(embed=embed)
        await self.cache.set(cache_key, message.id, 315360000)
        await self.delete_recent_duplicate_embed_messages(channel, "Executive Hangar Clock", message.id)
        logging.info("Created Executive Hangar status message %s", message.id)

    async def find_recent_embed_message(
        self,
        channel: discord.abc.Messageable,
        title: str,
    ) -> discord.Message | None:
        if not hasattr(channel, "history"):
            return None

        try:
            async for message in channel.history(limit=50):
                if self.user is not None and message.author.id != self.user.id:
                    continue
                if any(embed.title == title for embed in message.embeds):
                    return message
        except (discord.Forbidden, discord.HTTPException):
            return None

        return None

    async def find_recent_embed_messages(
        self,
        channel: discord.abc.Messageable,
        titles: set[str],
        limit: int = 50,
    ) -> dict[str, list[discord.Message]]:
        messages_by_title = {title: [] for title in titles}
        if not titles or not hasattr(channel, "history"):
            return messages_by_title

        try:
            async for message in channel.history(limit=limit):
                if self.user is not None and message.author.id != self.user.id:
                    continue
                for embed in message.embeds:
                    if embed.title in messages_by_title:
                        messages_by_title[embed.title].append(message)
                        break
        except (discord.Forbidden, discord.HTTPException):
            logging.info("Could not scan for existing embed messages")

        return messages_by_title

    async def delete_recent_duplicate_embed_messages(
        self,
        channel: discord.abc.Messageable,
        title: str,
        keep_message_id: int,
        limit: int = 50,
    ) -> None:
        if not hasattr(channel, "history"):
            return

        try:
            async for message in channel.history(limit=limit):
                if message.id == keep_message_id:
                    continue
                if self.user is not None and message.author.id != self.user.id:
                    continue
                if any(embed.title == title for embed in message.embeds):
                    try:
                        await message.delete()
                        logging.info("Deleted duplicate %s message %s", title, message.id)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        logging.info("Could not delete duplicate %s message %s", title, message.id)
        except (discord.Forbidden, discord.HTTPException):
            logging.info("Could not scan for duplicate %s messages", title)

    async def sync_cz_timers_message(self) -> None:
        if not self.settings.cz_timers_channel_id:
            return

        try:
            channel = await self.fetch_channel(self.settings.cz_timers_channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logging.warning("Could not access CZ_TIMERS_CHANNEL_ID %s", self.settings.cz_timers_channel_id)
            return

        if not isinstance(channel, discord.abc.Messageable) or not hasattr(channel, "fetch_message"):
            logging.warning("CZ_TIMERS_CHANNEL_ID does not point to a messageable channel")
            return

        timers = await get_cz_dashboard_timers(self.cache)
        embed = build_cz_dashboard_embed(timers)
        view = CZTimerDashboardView()
        cache_key = f"discord:cz-timers-message:{self.settings.cz_timers_channel_id}"
        message_id = await self.cache.get(cache_key)

        if isinstance(message_id, int):
            try:
                message = await channel.fetch_message(message_id)
                if not _message_embed_matches(message, embed) or message.content:
                    await message.edit(content=None, embed=embed, view=view)
                else:
                    await message.edit(view=view)
                logging.info("Updated CZ timers dashboard message %s", message_id)
                await self.delete_recent_duplicate_embed_messages(channel, "Contested Zone Timers", message.id)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logging.info("Could not update previous CZ timers dashboard; scanning for an existing one")

        existing_message = await self.find_recent_embed_message(channel, "Contested Zone Timers")
        if existing_message is not None:
            if not _message_embed_matches(existing_message, embed) or existing_message.content:
                await existing_message.edit(content=None, embed=embed, view=view)
            else:
                await existing_message.edit(view=view)
            await self.cache.set(cache_key, existing_message.id, 315360000)
            await self.delete_recent_duplicate_embed_messages(channel, "Contested Zone Timers", existing_message.id)
            logging.info("Adopted existing CZ timers dashboard message %s", existing_message.id)
            return

        message = await channel.send(embed=embed, view=view)
        await self.cache.set(cache_key, message.id, 315360000)
        await self.delete_recent_duplicate_embed_messages(channel, "Contested Zone Timers", message.id)
        logging.info("Created CZ timers dashboard message %s", message.id)

    async def resolve_exec_cycle_start(self) -> tuple[int, str]:
        override = await self.cache.get(EXEC_OVERRIDE_CACHE_KEY)
        if isinstance(override, dict) and isinstance(override.get("cycle_start_unix"), int):
            return override["cycle_start_unix"], "Manual override"

        cycle_start = await fetch_exec_cycle_start_unix(self.settings.http_timeout_seconds)
        return cycle_start, "contestedzonetimers.com community timer"

    async def resolve_exec_status_context(self) -> dict:
        source_cycle_start = await fetch_exec_cycle_start_unix(self.settings.http_timeout_seconds)
        source_status = calculate_exec_hangar_status(source_cycle_start)
        override = await self.cache.get(EXEC_OVERRIDE_CACHE_KEY)

        if isinstance(override, dict) and isinstance(override.get("cycle_start_unix"), int):
            corrected_status = calculate_exec_hangar_status(override["cycle_start_unix"])
            return {
                "source_status": source_status,
                "corrected_status": corrected_status,
                "override": override,
            }

        return {
            "source_status": source_status,
            "corrected_status": None,
            "override": None,
        }

    async def close(self) -> None:
        if self._exec_status_task:
            self._exec_status_task.cancel()
        if self._cz_timers_task:
            self._cz_timers_task.cancel()
        await self.sources.close()
        await self.cache.close()
        await super().close()

    async def log_audit_event(
        self,
        title: str,
        fields: dict[str, object],
        color: discord.Color = discord.Color.blurple(),
    ) -> None:
        await self.cache.add_audit_event(title, fields)

        if not self.settings.audit_log_channel_id:
            return

        try:
            channel = await self.fetch_channel(self.settings.audit_log_channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logging.warning("Could not access AUDIT_LOG_CHANNEL_ID %s", self.settings.audit_log_channel_id)
            return

        if not isinstance(channel, discord.abc.Messageable):
            logging.warning("AUDIT_LOG_CHANNEL_ID does not point to a messageable channel")
            return

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())
        for name, value in fields.items():
            embed.add_field(name=name, value=_truncate_audit_value(value), inline=False)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logging.warning("Could not send audit log event: %s", title)



def _interaction_command_name(interaction: discord.Interaction) -> str:
    data = interaction.data if isinstance(interaction.data, dict) else {}
    names = [str(data.get("name") or "unknown")]
    options = data.get("options")

    while isinstance(options, list) and options:
        option = options[0]
        if not isinstance(option, dict) or option.get("type") not in (1, 2):
            break
        names.append(str(option.get("name") or "unknown"))
        options = option.get("options")

    return _normalize_command_name(" ".join(names))


def _normalize_command_name(value: str) -> str:
    return " ".join(value.lower().strip().removeprefix("/").replace("_", " ").split())


def _format_interaction_options(interaction: discord.Interaction) -> str:
    data = interaction.data if isinstance(interaction.data, dict) else {}
    options = _flatten_interaction_options(data.get("options"))
    if not options:
        return ""

    text = "\n".join(f"{name}: {value}" for name, value in options)
    return text if len(text) <= 900 else f"{text[:897].rstrip()}..."


def _flatten_interaction_options(options: object, prefix: str = "") -> list[tuple[str, object]]:
    if not isinstance(options, list):
        return []

    flattened: list[tuple[str, object]] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        name = str(option.get("name") or "unknown")
        full_name = f"{prefix}.{name}" if prefix else name
        nested_options = option.get("options")
        if isinstance(nested_options, list):
            flattened.extend(_flatten_interaction_options(nested_options, full_name))
            continue
        if "value" in option:
            flattened.append((full_name, option["value"]))
    return flattened


def _audit_user(user: discord.abc.User) -> str:
    return f"{user} (`{user.id}`)"


def _audit_channel(channel_id: int | None) -> str:
    return f"<#{channel_id}>" if channel_id else "Unknown"


def _truncate_audit_value(value: object) -> str:
    text = str(value)
    return text if len(text) <= 1024 else f"{text[:1021].rstrip()}..."


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
    name="Commodity name or code.",
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


@app_commands.command(name="mining", description="Find where to mine Star Citizen materials.")
@app_commands.describe(
    material="Mineable material name or code.",
    system="Optional star system filter.",
    planet="Optional planet, moon, lagrange point, or location filter.",
)
async def mining_command(
    interaction: discord.Interaction,
    material: str,
    system: str | None = None,
    planet: str | None = None,
) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    result: MiningLocationResult | None = None
    terms = _mining_multi_search_terms(material)
    if len(terms) == 1 and not _has_mining_multi_separator(material):
        result = await bot.sources.lookup_mining_material(material, system, planet)
        if result is None:
            terms = _mining_space_search_terms(material)

    if len(terms) > 1:
        embed = await build_multi_mining_signature_embed(bot.sources, material, terms)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    if result is None:
        result = await bot.sources.lookup_mining_material(material, system, planet)
    if result is None:
        await interaction.followup.send(f"No mining material found for `{material}`.", ephemeral=True)
        return
    result = await apply_community_mining_locations(bot.cache, result)

    kwargs = {
        "embed": build_mining_embed(result, system, planet),
        "ephemeral": True,
    }
    if _mining_location_page_count(result) > 1:
        kwargs["view"] = MiningLocationView(result, system, planet)
    await interaction.followup.send(**kwargs)


@mining_command.autocomplete("material")
async def mining_material_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        return []

    prefix, partial = _mining_autocomplete_prefix(current)
    names = await bot.sources.autocomplete_mining_materials(partial)
    return [
        app_commands.Choice(name=f"{prefix}{name}"[:100], value=f"{prefix}{name}"[:100])
        for name in names[:25]
    ]


@mining_command.autocomplete("system")
async def mining_system_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await commodity_system_autocomplete(interaction, current)


@mining_command.autocomplete("planet")
async def mining_planet_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        return []

    namespace = interaction.namespace
    system = namespace.system if isinstance(getattr(namespace, "system", None), str) else None
    names = await bot.sources.autocomplete_mining_locations(current, system)
    return [
        app_commands.Choice(name=name[:100], value=name[:100])
        for name in names[:25]
    ]


industry_group = app_commands.Group(name="industry", description="Mining and salvage operation planning tools.")


@industry_group.command(name="split", description="Divide an operation payout evenly after shared expenses.")
@app_commands.describe(
    gross="Total operation payout in aUEC.",
    crew="Comma-separated crew names.",
    expenses="Shared operation expenses in aUEC.",
)
async def industry_split_command(
    interaction: discord.Interaction,
    gross: int,
    crew: str,
    expenses: int = 0,
) -> None:
    names = [name.strip() for name in crew.split(",") if name.strip()]
    if gross < 0 or expenses < 0 or expenses > gross:
        await interaction.response.send_message(
            "Gross and expenses cannot be negative, and expenses cannot exceed gross.", ephemeral=True
        )
        return
    if not names:
        await interaction.response.send_message("Add at least one crew member.", ephemeral=True)
        return
    net = gross - expenses
    base_share, remainder = divmod(net, len(names))
    payouts = [f"**{name}** — {base_share + (1 if index < remainder else 0):,} aUEC" for index, name in enumerate(names)]
    embed = discord.Embed(title="Industry Crew Payout", color=discord.Color.orange())
    embed.description = "\n".join(payouts)
    embed.add_field(name="Gross", value=f"{gross:,} aUEC")
    embed.add_field(name="Expenses", value=f"{expenses:,} aUEC")
    embed.add_field(name="Net", value=f"{net:,} aUEC")
    embed.set_footer(text="Any indivisible remainder is assigned one aUEC at a time in listed order.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@industry_group.command(name="refinery", description="Calculate a refinery job's completion time.")
@app_commands.describe(job="Job label or refinery.", hours="Whole hours remaining.", minutes="Additional minutes remaining.")
async def industry_refinery_command(
    interaction: discord.Interaction,
    job: str,
    hours: app_commands.Range[int, 0, 999] = 0,
    minutes: app_commands.Range[int, 0, 59] = 0,
) -> None:
    if hours == 0 and minutes == 0:
        await interaction.response.send_message("The refinery duration must be longer than zero.", ephemeral=True)
        return
    completion_unix = int(discord.utils.utcnow().timestamp()) + ((hours * 60 + minutes) * 60)
    embed = discord.Embed(title="Refinery Completion", color=discord.Color.orange())
    embed.add_field(name="Job", value=job, inline=False)
    embed.add_field(name="Completes", value=f"<t:{completion_unix}:F> (<t:{completion_unix}:R>)", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@industry_group.command(name="brief", description="Create a Discord-ready mining or salvage operation brief.")
@app_commands.describe(
    operation="Operation name.",
    location="Rally point or operating location.",
    objective="Mining or salvage objective.",
    crew="Assigned crew or open roles.",
    notes="Equipment, route, communications, or safety notes.",
)
async def industry_brief_command(
    interaction: discord.Interaction,
    operation: str,
    location: str,
    objective: str,
    crew: str | None = None,
    notes: str | None = None,
) -> None:
    embed = discord.Embed(title=operation, description=objective, color=discord.Color.orange())
    embed.add_field(name="Rally Point", value=location, inline=False)
    if crew:
        embed.add_field(name="Crew / Open Roles", value=crew, inline=False)
    if notes:
        embed.add_field(name="Notes", value=notes, inline=False)
    embed.set_footer(text="Prepared with SC Companion Industry Operations")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app_commands.command(name="miningadd", description="Add a community-reported mining location for a material.")
@app_commands.describe(
    material="Mineable material name or code.",
    system="Star system where the material was found.",
    location_type="Type of location to add.",
    location="Planet, moon, lagrange point, or point of interest name.",
)
@app_commands.choices(
    location_type=[
        app_commands.Choice(name="Lagrange Point", value="lagrange_points"),
        app_commands.Choice(name="Planet", value="planets"),
        app_commands.Choice(name="Moon", value="moons"),
        app_commands.Choice(name="Point of Interest", value="points_of_interest"),
    ]
)
async def miningadd_command(
    interaction: discord.Interaction,
    material: str,
    system: str,
    location_type: app_commands.Choice[str],
    location: str,
) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    if not _can_manage_change_commands(interaction, bot.settings):
        await interaction.response.send_message("You do not have permission to add mining locations.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    result = await bot.sources.lookup_mining_material(material)
    if result is None:
        await interaction.followup.send(f"No mining material found for `{material}`.", ephemeral=True)
        return

    entry = {
        "material": result.material_name,
        "system": system.strip(),
        "location_type": location_type.value,
        "location": location.strip(),
        "reported_by": str(interaction.user),
    }
    await add_community_mining_location(bot.cache, entry)
    await bot.log_audit_event(
        "Mining Location Added",
        {
            "User": _audit_user(interaction.user),
            "Channel": _audit_channel(interaction.channel_id),
            "Material": result.material_name,
            "System": system.strip(),
            "Location Type": location_type.name,
            "Location": location.strip(),
        },
        color=discord.Color.green(),
    )
    await interaction.followup.send(
        f"Added `{location.strip()}` to `{result.material_name}` mining locations in `{system.strip()}`.",
        ephemeral=True,
    )


@miningadd_command.autocomplete("material")
async def miningadd_material_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await mining_material_autocomplete(interaction, current)


@miningadd_command.autocomplete("system")
async def miningadd_system_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await commodity_system_autocomplete(interaction, current)


class MiningLocationView(discord.ui.View):
    def __init__(
        self,
        result: MiningLocationResult,
        system: str | None = None,
        planet: str | None = None,
        page: int = 1,
    ) -> None:
        super().__init__(timeout=300)
        self.result = result
        self.system = system
        self.planet = planet
        self.page = page
        if not system and _mining_location_page_count(result) > 1:
            self.add_item(MiningSystemSelect(result, planet))
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        page_count = _mining_location_page_count(self.result)
        self.previous_page.disabled = self.page <= 1
        self.next_page.disabled = self.page >= page_count

    @discord.ui.button(label="Previous Page", style=discord.ButtonStyle.secondary, row=0)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        self.page = max(1, self.page - 1)
        self._sync_buttons()
        await interaction.response.edit_message(
            embed=build_mining_embed(self.result, self.system, self.planet, page=self.page),
            view=self,
        )

    @discord.ui.button(label="Next Page", style=discord.ButtonStyle.secondary, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        self.page = min(_mining_location_page_count(self.result), self.page + 1)
        self._sync_buttons()
        await interaction.response.edit_message(
            embed=build_mining_embed(self.result, self.system, self.planet, page=self.page),
            view=self,
        )


class MiningSystemSelect(discord.ui.Select):
    def __init__(self, result: MiningLocationResult, planet: str | None = None) -> None:
        options = [
            discord.SelectOption(label=group.system, value=group.system)
            for group in result.location_groups or []
            if _mining_system_group_has_locations(group)
        ][:25]
        super().__init__(
            placeholder="Filter by system",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )
        self.result = result
        self.planet = planet

    async def callback(self, interaction: discord.Interaction) -> None:
        system = self.values[0]
        result = _mining_result_for_system(self.result, system)
        view = MiningLocationView(result, system, self.planet) if _mining_location_page_count(result) > 1 else None
        await interaction.response.edit_message(
            embed=build_mining_embed(result, system, self.planet),
            view=view,
        )


@app_commands.command(name="blueprint", description="Search Star Citizen crafting blueprints.")
@app_commands.describe(
    name="Blueprint or item name to search.",
    category="Optional blueprint category.",
    material="Optional required material or resource.",
    mission_type="Optional mission type that can award the blueprint.",
    contractor="Optional mission contractor.",
)
async def blueprint_command(
    interaction: discord.Interaction,
    name: str | None = None,
    category: str | None = None,
    material: str | None = None,
    mission_type: str | None = None,
    contractor: str | None = None,
) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    if not any([name, category, material, mission_type, contractor]):
        await interaction.response.send_message("Add a blueprint name or at least one filter.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        lookup_name = name
        lookup_material = material
        if name and not any([category, material, mission_type, contractor]):
            exact_blueprint_name = await _exact_blueprint_name_match(bot, name)
            exact_material = await _exact_blueprint_filter_match(bot, "resource", name)
            if exact_material and not exact_blueprint_name:
                lookup_name = None
                lookup_material = exact_material

        result_limit = 3 if lookup_name else 25
        results = await bot.sources.lookup_blueprints(
            query=lookup_name,
            category=category,
            material=lookup_material,
            mission_type=mission_type,
            contractor=contractor,
            limit=result_limit,
        )

        if not results:
            await interaction.followup.send("No blueprints found for those filters.", ephemeral=True)
            return

        if not lookup_name:
            has_next = bool(
                await bot.sources.lookup_blueprints(
                    query=None,
                    category=category,
                    material=lookup_material,
                    mission_type=mission_type,
                    contractor=contractor,
                    limit=BLUEPRINT_PAGE_SIZE,
                    page=2,
                )
            )
            await interaction.followup.send(
                embed=build_blueprint_selection_embed(
                    results,
                    category=category,
                    material=lookup_material,
                    mission_type=mission_type,
                    contractor=contractor,
                    page=1,
                    has_next=has_next,
                ),
                view=BlueprintSelectView(
                    results,
                    category=category,
                    material=lookup_material,
                    mission_type=mission_type,
                    contractor=contractor,
                    page=1,
                    has_next=has_next,
                ),
                ephemeral=True,
            )
            return

        if len(results) == 1:
            result = results[0]
            has_next = _blueprint_mission_page_count(result.missions) > 1
            kwargs = {
                "embed": build_blueprint_embed(
                    result,
                    lookup_name,
                    category,
                    lookup_material,
                    mission_type,
                    contractor,
                    mission_page=1,
                ),
                "ephemeral": True,
            }
            if has_next:
                kwargs["view"] = BlueprintDetailView(
                    result,
                    lookup_name,
                    category,
                    lookup_material,
                    mission_type,
                    contractor,
                    page=1,
                )
            await interaction.followup.send(**kwargs)
            return

        await interaction.followup.send(
            embeds=[
                build_blueprint_embed(result, lookup_name, category, lookup_material, mission_type, contractor, mission_page=1)
                for result in results
            ],
            ephemeral=True,
        )
    except Exception:
        logging.exception("Blueprint command failed")
        await interaction.followup.send(
            "Blueprint lookup hit an internal error. I logged the details so it can be fixed.",
            ephemeral=True,
        )


@blueprint_command.autocomplete("name")
async def blueprint_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        return []

    names = await bot.sources.autocomplete_blueprints(current)
    return [app_commands.Choice(name=name[:100], value=name[:100]) for name in names[:25]]


@app_commands.command(name="mission", description="Search Star Citizen missions and blueprint rewards.")
@app_commands.describe(
    name="Mission name.",
    region="Region or star system.",
    rep_giver="Contractor or reputation giver.",
    rep_level="Required reputation level.",
    mission_type="Mission category or type.",
)
async def mission_command(
    interaction: discord.Interaction,
    name: str | None = None,
    region: str | None = None,
    rep_giver: str | None = None,
    rep_level: str | None = None,
    mission_type: str | None = None,
) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return
    if not any([name, region, rep_giver, rep_level, mission_type]):
        await interaction.response.send_message("Add a mission name or at least one filter.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        results = await bot.sources.lookup_missions(
            query=name, region=region, contractor=rep_giver,
            reputation_level=rep_level, mission_type=mission_type, limit=10,
        )
        if not results:
            await interaction.followup.send("No missions found for those filters.", ephemeral=True)
            return
        await interaction.followup.send(
            embeds=[build_mission_embed(result) for result in results],
            ephemeral=True,
        )
    except Exception:
        logging.exception("Mission command failed")
        await interaction.followup.send(
            "Mission lookup hit an internal error. I logged the details so it can be fixed.",
            ephemeral=True,
        )


@mission_command.autocomplete("name")
@mission_command.autocomplete("region")
@mission_command.autocomplete("rep_giver")
@mission_command.autocomplete("rep_level")
@mission_command.autocomplete("mission_type")
async def mission_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        return []
    field_map = {
        "name": "name",
        "region": "region",
        "rep_giver": "contractor",
        "rep_level": "reputation_level",
        "mission_type": "mission_type",
    }
    focused = interaction.namespace
    parameter = next(
        (option.get("name") for option in interaction.data.get("options", []) if option.get("focused")),
        "name",
    )
    del focused
    values = await bot.sources.autocomplete_missions(field_map.get(parameter, "name"), current)
    return [app_commands.Choice(name=value[:100], value=value[:100]) for value in values[:25]]


@blueprint_command.autocomplete("category")
@blueprint_command.autocomplete("material")
@blueprint_command.autocomplete("mission_type")
@blueprint_command.autocomplete("contractor")
async def blueprint_filter_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        return []

    field_map = {
        "category": "category",
        "material": "resource",
        "mission_type": "mission_type",
        "contractor": "contractor",
    }
    names = await bot.sources.autocomplete_blueprint_filter(
        field_map.get(_focused_option_name(interaction), "category"),
        current,
    )
    return [app_commands.Choice(name=name[:100], value=name[:100]) for name in names[:25]]


async def _exact_blueprint_name_match(bot: GameAssistBot, query: str) -> str | None:
    names = await bot.sources.autocomplete_blueprints(query)
    return _exact_choice_match(query, names)


async def _exact_blueprint_filter_match(bot: GameAssistBot, filter_name: str, query: str) -> str | None:
    names = await bot.sources.autocomplete_blueprint_filter(filter_name, query)
    return _exact_choice_match(query, names)


def _exact_choice_match(query: str, choices: list[str]) -> str | None:
    normalized_query = _normalize_choice(query)
    for choice in choices:
        if _normalize_choice(choice) == normalized_query:
            return choice
    return None


def _normalize_choice(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").split())


class BlueprintSelect(discord.ui.Select):
    def __init__(self, results: list[BlueprintResult]) -> None:
        self.results = results[:25]
        options = [
            discord.SelectOption(
                label=result.name[:100],
                description=_blueprint_result_label(result)[:100],
                value=str(index),
            )
            for index, result in enumerate(self.results)
        ]
        super().__init__(
            placeholder="Select a blueprint for full details",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        result = self.results[int(self.values[0])]
        has_next = _blueprint_mission_page_count(result.missions) > 1
        kwargs = {"embed": build_blueprint_embed(result, mission_page=1)}
        if has_next:
            kwargs["view"] = BlueprintDetailView(result, page=1)
        else:
            kwargs["view"] = None
        await interaction.response.edit_message(**kwargs)


class BlueprintDetailView(discord.ui.View):
    def __init__(
        self,
        result: BlueprintResult,
        name: str | None = None,
        category: str | None = None,
        material: str | None = None,
        mission_type: str | None = None,
        contractor: str | None = None,
        page: int = 1,
    ) -> None:
        super().__init__(timeout=300)
        self.result = result
        self.name = name
        self.category = category
        self.material = material
        self.mission_type = mission_type
        self.contractor = contractor
        self.page = page
        self.page_count = _blueprint_mission_page_count(result.missions)
        self.previous_page.disabled = self.page_count <= 1
        self.next_page.disabled = self.page_count <= 1

    @discord.ui.button(label="Previous Page", style=discord.ButtonStyle.secondary, row=0)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._show_page(interaction, self.page - 1)

    @discord.ui.button(label="Next Page", style=discord.ButtonStyle.secondary, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._show_page(interaction, self.page + 1)

    async def _show_page(self, interaction: discord.Interaction, page: int) -> None:
        if page < 1:
            page = self.page_count
        elif page > self.page_count:
            page = 1
        await interaction.response.edit_message(
            embed=build_blueprint_embed(
                self.result,
                self.name,
                self.category,
                self.material,
                self.mission_type,
                self.contractor,
                mission_page=page,
            ),
            view=BlueprintDetailView(
                self.result,
                self.name,
                self.category,
                self.material,
                self.mission_type,
                self.contractor,
                page=page,
            ),
        )


class BlueprintSelectView(discord.ui.View):
    def __init__(
        self,
        results: list[BlueprintResult],
        category: str | None = None,
        material: str | None = None,
        mission_type: str | None = None,
        contractor: str | None = None,
        page: int = 1,
        has_next: bool = False,
    ) -> None:
        super().__init__(timeout=300)
        self.category = category
        self.material = material
        self.mission_type = mission_type
        self.contractor = contractor
        self.page = page
        self.has_next = has_next
        self.add_item(BlueprintSelect(results))
        self.previous_page.disabled = page <= 1
        self.next_page.disabled = not has_next

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, row=1)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._show_page(interaction, self.page - 1)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._show_page(interaction, self.page + 1)

    async def _show_page(self, interaction: discord.Interaction, page: int) -> None:
        bot = interaction.client
        if not isinstance(bot, GameAssistBot):
            await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
            return

        await interaction.response.defer()
        results = await bot.sources.lookup_blueprints(
            query=None,
            category=self.category,
            material=self.material,
            mission_type=self.mission_type,
            contractor=self.contractor,
            limit=BLUEPRINT_PAGE_SIZE,
            page=page,
        )
        has_next = bool(
            await bot.sources.lookup_blueprints(
                query=None,
                category=self.category,
                material=self.material,
                mission_type=self.mission_type,
                contractor=self.contractor,
                limit=BLUEPRINT_PAGE_SIZE,
                page=page + 1,
            )
        )
        await interaction.edit_original_response(
            embed=build_blueprint_selection_embed(
                results,
                category=self.category,
                material=self.material,
                mission_type=self.mission_type,
                contractor=self.contractor,
                page=page,
                has_next=has_next,
            ),
            view=BlueprintSelectView(
                results,
                category=self.category,
                material=self.material,
                mission_type=self.mission_type,
                contractor=self.contractor,
                page=page,
                has_next=has_next,
            ),
        )


item_group = app_commands.Group(name="item", description="Item lookup tools.")


@item_group.command(name="locator", description="Find in-game buyable Star Citizen items.")
@app_commands.describe(
    name="Item name to search.",
    category="Optional item category, such as Quantum Drives, Guns, Helmets, or Undersuits.",
    section="Optional item section, such as Systems, Vehicle Weapons, Armor, or Utility.",
    size="Optional item size.",
)
async def item_locator_command(
    interaction: discord.Interaction,
    name: str | None = None,
    category: str | None = None,
    section: str | None = None,
    size: str | None = None,
) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    if not any([name, category, section, size]):
        await interaction.response.send_message("Add an item name or at least one filter.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    results = await bot.sources.lookup_items(
        query=name,
        category=category,
        section=section,
        size=size,
        limit=BLUEPRINT_PAGE_SIZE,
        page=1,
    )
    if not results:
        await interaction.followup.send("No in-game buyable items found for those filters.", ephemeral=True)
        return

    if name and len(results) == 1:
        detail = await bot.sources.lookup_item_by_id(results[0].id)
        await interaction.followup.send(
            embed=build_item_locator_embed(detail or results[0], name, category, section, size),
            ephemeral=True,
        )
        return

    has_next = bool(
        await bot.sources.lookup_items(
            query=name,
            category=category,
            section=section,
            size=size,
            limit=BLUEPRINT_PAGE_SIZE,
            page=2,
        )
    )
    await interaction.followup.send(
        embed=build_item_locator_selection_embed(results, name, category, section, size, page=1, has_next=has_next),
        view=ItemLocatorSelectView(results, name, category, section, size, page=1, has_next=has_next),
        ephemeral=True,
    )


@item_group.command(name="search", description="Search for in-game buyable Star Citizen items.")
@app_commands.describe(
    name="Item name to search.",
    category="Optional item category, such as Quantum Drives, Guns, Helmets, or Undersuits.",
    section="Optional item section, such as Systems, Vehicle Weapons, Armor, or Utility.",
    size="Optional item size.",
)
async def item_search_command(
    interaction: discord.Interaction,
    name: str | None = None,
    category: str | None = None,
    section: str | None = None,
    size: str | None = None,
) -> None:
    await item_locator_command.callback(interaction, name, category, section, size)


@item_search_command.autocomplete("name")
@item_locator_command.autocomplete("name")
async def item_locator_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        return []
    names = await bot.sources.autocomplete_items(current)
    return [app_commands.Choice(name=name[:100], value=name[:100]) for name in names[:25]]


@item_search_command.autocomplete("category")
@item_search_command.autocomplete("section")
@item_search_command.autocomplete("size")
@item_locator_command.autocomplete("category")
@item_locator_command.autocomplete("section")
@item_locator_command.autocomplete("size")
async def item_locator_filter_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        return []
    names = await bot.sources.autocomplete_item_filter(_focused_option_name(interaction), current)
    return [app_commands.Choice(name=name[:100], value=name[:100]) for name in names[:25]]


class ItemLocatorSelect(discord.ui.Select):
    def __init__(self, results: list[ItemLocatorResult]) -> None:
        self.results = results[:25]
        options = [
            discord.SelectOption(
                label=result.name[:100],
                description=_item_locator_result_label(result)[:100],
                value=str(result.id),
            )
            for result in self.results
        ]
        super().__init__(
            placeholder="Select an item for buy locations",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        if not isinstance(bot, GameAssistBot):
            await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
            return

        await interaction.response.defer()
        result = await bot.sources.lookup_item_by_id(int(self.values[0]))
        if result is None:
            await interaction.edit_original_response(content="That item is no longer available in UEX.", embed=None, view=None)
            return
        await interaction.edit_original_response(embed=build_item_locator_embed(result), view=None)


class ItemLocatorSelectView(discord.ui.View):
    def __init__(
        self,
        results: list[ItemLocatorResult],
        name: str | None = None,
        category: str | None = None,
        section: str | None = None,
        size: str | None = None,
        page: int = 1,
        has_next: bool = False,
    ) -> None:
        super().__init__(timeout=300)
        self.name = name
        self.category = category
        self.section = section
        self.size = size
        self.page = page
        self.has_next = has_next
        self.add_item(ItemLocatorSelect(results))
        self.previous_page.disabled = page <= 1
        self.next_page.disabled = not has_next

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, row=1)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._show_page(interaction, self.page - 1)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._show_page(interaction, self.page + 1)

    async def _show_page(self, interaction: discord.Interaction, page: int) -> None:
        bot = interaction.client
        if not isinstance(bot, GameAssistBot):
            await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
            return

        await interaction.response.defer()
        results = await bot.sources.lookup_items(
            query=self.name,
            category=self.category,
            section=self.section,
            size=self.size,
            limit=BLUEPRINT_PAGE_SIZE,
            page=page,
        )
        has_next = bool(
            await bot.sources.lookup_items(
                query=self.name,
                category=self.category,
                section=self.section,
                size=self.size,
                limit=BLUEPRINT_PAGE_SIZE,
                page=page + 1,
            )
        )
        await interaction.edit_original_response(
            embed=build_item_locator_selection_embed(
                results,
                self.name,
                self.category,
                self.section,
                self.size,
                page=page,
                has_next=has_next,
            ),
            view=ItemLocatorSelectView(
                results,
                self.name,
                self.category,
                self.section,
                self.size,
                page=page,
                has_next=has_next,
            ),
        )


inventory_group = app_commands.Group(name="inventory", description="Search your website inventory.")


@inventory_group.command(name="search", description="Search the inventory saved through the website.")
@app_commands.describe(
    item="Item name or notes to search.",
    station="Station or inventory location.",
    category="Inventory category.",
    item_type="Item type.",
    size="Item size.",
    sort_by="How to order the results.",
)
@app_commands.choices(
    sort_by=[
        app_commands.Choice(name="Item name", value="name"),
        app_commands.Choice(name="Station", value="location"),
        app_commands.Choice(name="Category", value="category"),
        app_commands.Choice(name="Quantity", value="quantity"),
        app_commands.Choice(name="Recently updated", value="updated"),
    ]
)
async def inventory_search_command(
    interaction: discord.Interaction,
    item: str | None = None,
    station: str | None = None,
    category: str | None = None,
    item_type: str | None = None,
    size: str | None = None,
    sort_by: app_commands.Choice[str] | None = None,
) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    results = await bot.cache.user_inventory_items(
        interaction.user.id,
        location=station,
        category=category,
        query=item,
        sort_by=sort_by.value if sort_by else "name",
        item_type=item_type,
        item_size=size,
    )
    if not results:
        await interaction.followup.send(
            "No items in your website inventory matched those filters. Sign into the website with this Discord account to add inventory.",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        embed=build_inventory_search_embed(results, item, station, category, item_type, size),
        ephemeral=True,
    )


@inventory_search_command.autocomplete("item")
@inventory_search_command.autocomplete("station")
@inventory_search_command.autocomplete("category")
@inventory_search_command.autocomplete("item_type")
@inventory_search_command.autocomplete("size")
async def inventory_search_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        return []

    focused = _focused_option_name(interaction)
    if focused == "item":
        inventory = await bot.cache.user_inventory_items(interaction.user.id)
        values = sorted({str(row["name"]) for row in inventory if row.get("name")}, key=str.casefold)
    else:
        facets = await bot.cache.user_inventory_facets(interaction.user.id)
        values = facets.get(
            {
                "station": "locations",
                "category": "categories",
                "item_type": "item_types",
                "size": "item_sizes",
            }.get(focused, ""),
            [],
        )

    normalized = current.strip().casefold()
    matches = [value for value in values if not normalized or normalized in value.casefold()]
    return [app_commands.Choice(name=value[:100], value=value[:100]) for value in matches[:25]]


trade_group = app_commands.Group(name="trade", description="Trade planning tools.")


@trade_group.command(name="routing", description="Find Star Citizen trade route candidates from UEX.")
@app_commands.describe(
    starting_point="Required starting trade terminal for the circular route.",
    ship="Ship for route planning.",
    investment="aUEC investment for route planning.",
    max_stops="Maximum route stops, from 2 to 5.",
    stay_system="Optional star system to keep the full loop inside.",
)
async def trade_routing_command(
    interaction: discord.Interaction,
    starting_point: str,
    ship: str = "Ironclad Assault",
    investment: int = 1_000_000,
    max_stops: int = 5,
    stay_system: str | None = None,
) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    if investment <= 0:
        await interaction.response.send_message("Investment must be greater than 0 aUEC.", ephemeral=True)
        return
    if max_stops < 2 or max_stops > 5:
        await interaction.response.send_message("Circular routes need max stops between 2 and 5.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    ship_result = await bot.sources.lookup_ship(ship)
    if ship_result is None:
        await interaction.followup.send(f"No ship or vehicle found for `{ship}`.", ephemeral=True)
        return
    if ship_result.cargo_capacity is None or ship_result.cargo_capacity <= 0:
        await interaction.followup.send(f"`{ship_result.name}` does not have a usable cargo capacity for trade routing.", ephemeral=True)
        return

    result = await bot.sources.lookup_trade_routes(
        ship_result.name,
        ship_result.cargo_capacity,
        starting_point,
        investment,
        max_stops,
        stay_system,
        True,
    )
    if result is None or not result.legs:
        await interaction.followup.send(
            "No profitable UEX circular route found from that starting point right now.",
            ephemeral=True,
        )
        return

    embed = build_trade_route_embed(result, starting_point, max_stops, stay_system)
    await interaction.followup.send(embed=embed, ephemeral=True)


@trade_routing_command.autocomplete("starting_point")
async def trade_starting_point_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        return []

    locations = await bot.sources.autocomplete_trade_locations(current)
    return [
        app_commands.Choice(name=location[:100], value=location[:100])
        for location in locations[:25]
    ]


@trade_routing_command.autocomplete("ship")
async def trade_ship_autocomplete(
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


@trade_routing_command.autocomplete("stay_system")
async def trade_system_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await commodity_system_autocomplete(interaction, current)


admin_group = app_commands.Group(name="admin", description="Bot management commands.")


@admin_group.command(name="channels", description="Show command channel routing.")
async def admin_channels_command(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return
    if not _can_manage_admin_commands(interaction, bot.settings):
        await interaction.response.send_message("You do not have permission to view bot management details.", ephemeral=True)
        return

    embed = build_admin_channels_embed(bot.settings)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@admin_group.command(name="health", description="Show bot health and configuration status.")
async def admin_health_command(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return
    if not _can_manage_admin_commands(interaction, bot.settings):
        await interaction.response.send_message("You do not have permission to view bot management details.", ephemeral=True)
        return

    embed = build_admin_health_embed(bot)
    await interaction.response.send_message(embed=embed, ephemeral=True)


audit_group = app_commands.Group(name="audit", description="Audit log commands.")


@audit_group.command(name="recent", description="Show recent bot audit events.")
@app_commands.describe(limit="Number of recent audit events to show, from 1 to 20.")
async def audit_recent_command(interaction: discord.Interaction, limit: int = 10) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return
    if not _can_manage_admin_commands(interaction, bot.settings):
        await interaction.response.send_message("You do not have permission to view audit logs.", ephemeral=True)
        return
    if limit < 1 or limit > 20:
        await interaction.response.send_message("Limit must be between 1 and 20.", ephemeral=True)
        return

    events = await bot.cache.recent_audit_events(limit)
    await interaction.response.send_message(embed=build_audit_recent_embed(events), ephemeral=True)


@app_commands.command(name="exec", description="Show the current Executive Hangar clock.")
async def exec_command(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    await bot.sync_exec_status_message()

    if bot.settings.exec_status_channel_id:
        await interaction.followup.send(
            f"Executive Hangar panel refreshed in <#{bot.settings.exec_status_channel_id}>.",
            ephemeral=True,
        )
        return

    await interaction.followup.send("Executive Hangar status channel is not configured.", ephemeral=True)


@app_commands.command(name="execset", description="Correct the Executive Hangar timer.")
@app_commands.describe(
    phase="Current Executive Hangar phase.",
    remaining_minutes="Minutes remaining in the selected phase.",
)
@app_commands.choices(
    phase=[
        app_commands.Choice(name="Closed", value="closed"),
        app_commands.Choice(name="Open", value="open"),
        app_commands.Choice(name="Resetting", value="resetting"),
    ]
)
async def execset_command(
    interaction: discord.Interaction,
    phase: app_commands.Choice[str],
    remaining_minutes: int,
) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    if not _can_manage_exec_timer(interaction, bot.settings):
        await interaction.response.send_message("You do not have permission to update the Executive Hangar timer.", ephemeral=True)
        return

    try:
        cycle_start = calculate_cycle_start_from_phase(phase.value, remaining_minutes)
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return

    await bot.cache.set(
        EXEC_OVERRIDE_CACHE_KEY,
        {
            "cycle_start_unix": cycle_start,
            "updated_by": interaction.user.id,
            "updated_by_name": str(interaction.user),
            "updated_at_unix": discord.utils.utcnow().timestamp(),
            "phase": phase.value,
            "remaining_minutes": remaining_minutes,
        },
        315360000,
    )
    await bot.sync_exec_status_message()
    await bot.log_audit_event(
        "Executive Timer Corrected",
        {
            "User": _audit_user(interaction.user),
            "Channel": _audit_channel(interaction.channel_id),
            "Phase": phase.name,
            "Remaining Minutes": remaining_minutes,
        },
        color=discord.Color.gold(),
    )
    await interaction.response.send_message("Executive Hangar timer override saved and status message updated.", ephemeral=True)


@app_commands.command(name="execclear", description="Clear the manual Executive Hangar timer override.")
async def execclear_command(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    if not _can_manage_exec_timer(interaction, bot.settings):
        await interaction.response.send_message("You do not have permission to clear the Executive Hangar timer.", ephemeral=True)
        return

    await bot.cache.delete(EXEC_OVERRIDE_CACHE_KEY)
    await bot.sync_exec_status_message()
    await bot.log_audit_event(
        "Executive Timer Override Cleared",
        {
            "User": _audit_user(interaction.user),
            "Channel": _audit_channel(interaction.channel_id),
        },
        color=discord.Color.gold(),
    )
    await interaction.response.send_message("Executive Hangar timer override cleared. Using community timer source again.", ephemeral=True)


def build_exec_status_embed(status_context: dict) -> discord.Embed:
    source_status = status_context["source_status"]
    corrected_status = status_context.get("corrected_status")
    override = status_context.get("override")
    display_status = corrected_status or source_status

    embed = discord.Embed(
        title="Executive Hangar Clock",
        description=f"Status: {display_status.status}\nPhase: {display_status.status_detail}",
        url=display_status.source_url,
        color=discord.Color.green() if display_status.status == "Open" else discord.Color.red(),
    )
    embed.add_field(name="Active Timer", value=_format_exec_status(display_status), inline=False)

    if corrected_status is not None and isinstance(override, dict):
        embed.add_field(name="Website Source Timer", value=_format_exec_status(source_status), inline=False)
        updated_by = override.get("updated_by")
        updated_by_name = override.get("updated_by_name")
        if isinstance(updated_by, int):
            user = f"<@{updated_by}>"
        else:
            user = str(updated_by_name or "Unknown user")
        updated_at = override.get("updated_at_unix")
        updated_line = f"\nUpdated: <t:{int(updated_at)}:R>" if isinstance(updated_at, (int, float)) else ""
        embed.add_field(
            name="Manual Correction",
            value=f"Corrected by: {user}{updated_line}",
            inline=False,
        )

    embed.set_footer(
        text="Source timer: contestedzonetimers.com community timer. Corrected timer shown when manually adjusted."
    )
    return embed


def _format_exec_status(status: ExecHangarStatus) -> str:
    return (
        f"Status: {status.status}\n"
        f"Phase: {status.status_detail}\n"
        f"Lights: {status.lights}\n"
        f"Next Change: <t:{status.next_change_unix}:R>\n"
        f"At: <t:{status.next_change_unix}:T>"
    )


def build_admin_channels_embed(settings: Settings) -> discord.Embed:
    embed = build_command_channel_directory_embed(settings)
    embed.title = "Bot Management - Command Channels"

    special_channels = [
        _line("Command Reference", f"<#{settings.commands_channel_id}>" if settings.commands_channel_id else None),
        _line("Audit Log", f"<#{settings.audit_log_channel_id}>" if settings.audit_log_channel_id else None),
        _line("Executive Status", f"<#{settings.exec_status_channel_id}>" if settings.exec_status_channel_id else None),
        _line("CZ Dashboard", f"<#{settings.cz_timers_channel_id}>" if settings.cz_timers_channel_id else None),
    ]
    embed.add_field(
        name="Bot Channels",
        value="\n".join(line for line in special_channels if line) or "No bot channels configured.",
        inline=False,
    )
    return embed


def build_admin_health_embed(bot: GameAssistBot) -> discord.Embed:
    settings = bot.settings
    now = int(discord.utils.utcnow().timestamp())
    description = [
        _line("Status", "Online"),
        _line("Uptime", _format_duration(max(0, now - bot.started_at_unix))),
        _line("Guild ID", str(settings.discord_guild_id) if settings.discord_guild_id else "Global commands"),
        _line("Command Channels", str(len(settings.command_channel_ids))),
        _line("Audit Log", f"<#{settings.audit_log_channel_id}>" if settings.audit_log_channel_id else "Not configured"),
        _line("Change Command Roles", _format_role_ids(settings.exec_admin_role_ids)),
        _line("Admin/Audit Roles", _format_role_ids(settings.bot_admin_role_ids)),
        _line("Admin/Audit Users", _format_user_ids(settings.bot_admin_user_ids)),
        _line("Database", settings.database_path),
        _line("Cache TTL", _format_duration(settings.cache_ttl_seconds)),
    ]
    return discord.Embed(
        title="Bot Management - Health",
        description="\n".join(line for line in description if line),
        color=discord.Color.green(),
    )


def build_audit_recent_embed(events: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="Audit - Recent Events",
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow(),
    )
    if not events:
        embed.description = "No audit events recorded yet."
        return embed

    for event in events:
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        summary_parts = []
        for key in ("Command", "User", "Channel", "Action", "Timer", "Material", "Phase"):
            value = fields.get(key)
            if value:
                summary_parts.append(f"{key}: {value}")
        summary = "\n".join(summary_parts) or "No details recorded."
        created_at = event.get("created_at")
        when = f" <t:{created_at}:R>" if isinstance(created_at, int) else ""
        embed.add_field(
            name=f"{event.get('title', 'Audit Event')}{when}",
            value=_truncate_audit_value(summary),
            inline=False,
        )
    return embed


def _can_manage_exec_timer(interaction: discord.Interaction, settings: Settings) -> bool:
    return _can_manage_change_commands(interaction, settings)


def _can_manage_change_commands(interaction: discord.Interaction, settings: Settings) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False

    if settings.exec_admin_role_ids:
        user_role_ids = {role.id for role in user.roles}
        return bool(user_role_ids.intersection(settings.exec_admin_role_ids))

    return user.guild_permissions.manage_guild


def _can_manage_admin_commands(interaction: discord.Interaction, settings: Settings) -> bool:
    user = interaction.user
    if getattr(user, "id", None) in settings.bot_admin_user_ids:
        return True
    if not isinstance(user, discord.Member):
        return False

    if settings.bot_admin_role_ids:
        user_role_ids = {role.id for role in user.roles}
        return bool(user_role_ids.intersection(settings.bot_admin_role_ids))

    return user.guild_permissions.manage_guild


def _format_role_ids(role_ids: tuple[int, ...]) -> str:
    return ", ".join(f"<@&{role_id}>" for role_id in role_ids) if role_ids else "Manage Server fallback"


def _format_user_ids(user_ids: tuple[int, ...]) -> str:
    return ", ".join(f"<@{user_id}>" for user_id in user_ids) if user_ids else "None configured"


@app_commands.command(name="cztimer", description="Start a local contested-zone countdown.")
@app_commands.describe(
    timer="The contested-zone timer to track.",
    started_minutes_ago="Optional minutes already elapsed.",
)
@app_commands.choices(
    timer=[
        app_commands.Choice(name="Blue keycard terminal - 15 min", value="blue_keycard"),
        app_commands.Choice(name="Compboard/tablet - 30 min", value="compboard"),
        app_commands.Choice(name="Red supervisor keycard - 30 min", value="red_keycard"),
        app_commands.Choice(name="Ruin timer door cycle - 20 min", value="ruin_timer_door"),
    ]
)
async def cztimer_command(
    interaction: discord.Interaction,
    timer: app_commands.Choice[str],
    started_minutes_ago: int = 0,
) -> None:
    if started_minutes_ago < 0:
        await interaction.response.send_message("Elapsed minutes cannot be negative.", ephemeral=True)
        return

    durations = {
        "blue_keycard": ("Blue Keycard Terminal", 15 * 60),
        "compboard": ("Compboard / Tablet", 30 * 60),
        "red_keycard": ("Red Supervisor Keycard", 30 * 60),
        "ruin_timer_door": ("Ruin Timer Door Cycle", 20 * 60),
    }
    label, duration = durations[timer.value]
    ends_at = calculate_countdown_end_unix(duration, started_minutes_ago)

    embed = discord.Embed(
        title=label,
        description=f"Ready <t:{ends_at}:R>\nReady at <t:{ends_at}:T>",
        color=discord.Color.orange(),
    )
    embed.set_footer(text="Local helper timer based on known contested-zone durations")
    await interaction.response.send_message(embed=embed, ephemeral=True)


class CZTimerDashboardView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Start Blue Keycards", style=discord.ButtonStyle.primary, custom_id="cz:start:blue_keycard", row=0)
    async def start_blue_keycard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await handle_cz_timer_button(interaction, "start", "blue_keycard")

    @discord.ui.button(label="Reset Blue Keycards", style=discord.ButtonStyle.secondary, custom_id="cz:reset:blue_keycard", row=0)
    async def reset_blue_keycard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await handle_cz_timer_button(interaction, "reset", "blue_keycard")

    @discord.ui.button(label="Start Compboards", style=discord.ButtonStyle.primary, custom_id="cz:start:compboard", row=1)
    async def start_compboard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await handle_cz_timer_button(interaction, "start", "compboard")

    @discord.ui.button(label="Reset Compboards", style=discord.ButtonStyle.secondary, custom_id="cz:reset:compboard", row=1)
    async def reset_compboard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await handle_cz_timer_button(interaction, "reset", "compboard")

    @discord.ui.button(label="Start Red Keycards", style=discord.ButtonStyle.primary, custom_id="cz:start:red_keycard", row=2)
    async def start_red_keycard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await handle_cz_timer_button(interaction, "start", "red_keycard")

    @discord.ui.button(label="Reset Red Keycards", style=discord.ButtonStyle.secondary, custom_id="cz:reset:red_keycard", row=2)
    async def reset_red_keycard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await handle_cz_timer_button(interaction, "reset", "red_keycard")

    @discord.ui.button(label="Start Timer Doors", style=discord.ButtonStyle.primary, custom_id="cz:start:timer_door", row=3)
    async def start_timer_door(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await handle_cz_timer_button(interaction, "start", "timer_door")

    @discord.ui.button(label="Reset Timer Doors", style=discord.ButtonStyle.secondary, custom_id="cz:reset:timer_door", row=3)
    async def reset_timer_door(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await handle_cz_timer_button(interaction, "reset", "timer_door")

    @discord.ui.button(label="Reset All", style=discord.ButtonStyle.danger, custom_id="cz:reset:all", row=4)
    async def reset_all(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await handle_cz_timer_button(interaction, "reset_all", None)


async def handle_cz_timer_button(
    interaction: discord.Interaction,
    action: str,
    timer_key: str | None,
) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    timers = await get_cz_dashboard_timers(bot.cache)
    now = int(discord.utils.utcnow().timestamp())

    if action == "start" and timer_key in CZ_TIMER_DEFINITIONS:
        label, duration = CZ_TIMER_DEFINITIONS[timer_key]
        timers[timer_key] = {
            "end_unix": now + duration,
            "updated_by": interaction.user.id,
            "updated_by_name": str(interaction.user),
            "updated_at_unix": now,
        }
        message = f"{label} timer started."
    elif action == "reset" and timer_key in CZ_TIMER_DEFINITIONS:
        label, _duration = CZ_TIMER_DEFINITIONS[timer_key]
        timers.pop(timer_key, None)
        message = f"{label} timer reset."
    elif action == "reset_all":
        timers = {}
        message = "All CZ timers reset."
    else:
        await interaction.response.send_message("Unknown CZ timer action.", ephemeral=True)
        return

    await set_cz_dashboard_timers(bot.cache, timers)
    embed = build_cz_dashboard_embed(timers)
    await interaction.response.edit_message(embed=embed, view=CZTimerDashboardView())
    await bot.log_audit_event(
        "CZ Timer Updated",
        {
            "User": _audit_user(interaction.user),
            "Channel": _audit_channel(interaction.channel_id),
            "Action": action,
            "Timer": CZ_TIMER_DEFINITIONS[timer_key][0] if timer_key in CZ_TIMER_DEFINITIONS else "All",
        },
        color=discord.Color.orange(),
    )
    await interaction.followup.send(message, ephemeral=True)


async def get_cz_dashboard_timers(cache: SQLiteCache) -> dict:
    timers = await cache.get(CZ_TIMERS_CACHE_KEY)
    return timers if isinstance(timers, dict) else {}


async def set_cz_dashboard_timers(cache: SQLiteCache, timers: dict) -> None:
    await cache.set(CZ_TIMERS_CACHE_KEY, timers, 315360000)


def build_cz_dashboard_embed(timers: dict) -> discord.Embed:
    embed = discord.Embed(
        title="Contested Zone Timers",
        description="Use the buttons below to start or reset shared CZ timers.",
        color=discord.Color.orange(),
    )

    for key, (label, duration) in CZ_TIMER_DEFINITIONS.items():
        timer = timers.get(key)
        value = _format_cz_timer_value(timer, duration)
        embed.add_field(name=label, value=value, inline=False)

    embed.set_footer(text="Shared dashboard. Timers update when buttons are used and refresh every 60s while the bot is running.")
    return embed


def _format_cz_timer_value(timer: object, duration: int) -> str:
    if not isinstance(timer, dict):
        return f"Ready\nDefault duration: {_format_duration(duration)}"

    end_unix = timer.get("end_unix")
    if not isinstance(end_unix, int):
        return f"Ready\nDefault duration: {_format_duration(duration)}"

    now = int(discord.utils.utcnow().timestamp())
    user_id = timer.get("updated_by")
    user = f"<@{user_id}>" if isinstance(user_id, int) else str(timer.get("updated_by_name") or "Unknown user")

    if end_unix <= now:
        return f"Ready\nLast started by: {user}"

    return f"Ready <t:{end_unix}:R>\nAt <t:{end_unix}:T>\nStarted by: {user}"


def _format_duration(seconds: int) -> str:
    minutes = seconds // 60
    return f"{minutes} min"


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


def build_mining_embed(
    result: MiningLocationResult,
    system: str | None = None,
    planet: str | None = None,
    page: int = 1,
) -> discord.Embed:
    page_count = _mining_location_page_count(result)
    description = [
        _line("Code", result.code),
        _format_mining_signature_block(result.rock_signatures),
        _line("System Filter", system),
        _line("Location Filter", planet),
        _line("Location Basis", result.location_basis),
        _line("Refined Sell", _format_currency(result.refined_sell_price, "aUEC") if result.refined_sell_price else None),
        _line("Raw Sell", _format_currency(result.raw_sell_price, "aUEC") if result.raw_sell_price else None),
        _line("Tip", "Use the system selector or optional `system` field to narrow results." if page_count > 1 and not system else None),
    ]
    flags = _format_mining_flags(result)
    if flags:
        description.append(_line("Flags", flags))

    embed = discord.Embed(
        title=f"{result.material_name} Mining",
        description="\n".join(line for line in description if line),
        url=result.source_url,
        color=discord.Color.dark_gold(),
    )
    field_name = "Mining Locations"
    if page_count > 1:
        field_name = f"{field_name} (Page {page}/{page_count})"
    embed.add_field(name=field_name, value=_format_mining_location_page(result, page), inline=False)
    embed.set_footer(text=f"Source: {result.source_name} mining locations")
    return embed


async def build_multi_mining_signature_embed(
    sources: SourceRegistry,
    query: str,
    terms: list[str],
) -> discord.Embed:
    results: list[tuple[str, MiningLocationResult, list[int]]] = []
    missing: list[str] = []
    for term in terms:
        result = await sources.lookup_mining_material(term)
        if result is None:
            missing.append(term)
            continue
        signatures = _mining_term_signatures(result, term)
        results.append((term, result, signatures))

    material_names = _unique_preserve_order([result.material_name for _, result, _ in results])
    shared_signatures = _shared_mining_signatures([signatures for _, _, signatures in results])
    description = [
        _line("Search", query),
        _line("Materials", ", ".join(material_names) if material_names else None),
    ]
    if missing:
        description.append(_line("Not Found", ", ".join(missing)))

    embed = discord.Embed(
        title="Mining Signature Match",
        description="\n".join(line for line in description if line) or "No matching materials found.",
        color=discord.Color.dark_gold(),
    )
    embed.add_field(
        name="Rock Signatures",
        value=_format_rock_signatures(shared_signatures)
        if shared_signatures
        else "No shared rock signatures found for those materials.",
        inline=False,
    )
    embed.set_footer(text="Multi-material mining searches show shared rock signatures only.")
    return embed


def build_blueprint_embed(
    result: BlueprintResult,
    name: str | None = None,
    category: str | None = None,
    material: str | None = None,
    mission_type: str | None = None,
    contractor: str | None = None,
    mission_page: int = 1,
) -> discord.Embed:
    description = [
        _line("Category", result.category),
        _line("Craft Time", _format_seconds_duration(result.craft_time_seconds)),
        _line("Tiers", str(result.tiers) if result.tiers is not None else None),
        _line("Search", name),
        _line("Category Filter", category),
        _line("Material Filter", material),
        _line("Mission Type Filter", mission_type),
        _line("Contractor Filter", contractor),
    ]
    embed = discord.Embed(
        title=result.name,
        description="\n".join(line for line in description if line),
        url=result.source_url,
        color=discord.Color.dark_gold(),
    )
    embed.add_field(name="Materials", value=_format_blueprint_ingredients(result.ingredients), inline=False)
    page_count = _blueprint_mission_page_count(result.missions)
    field_name = "Blueprint Missions"
    if page_count > 1:
        field_name = f"{field_name} (Page {mission_page}/{page_count})"
    embed.add_field(
        name=field_name,
        value=_format_blueprint_missions(result.missions, page=mission_page),
        inline=False,
    )
    embed.set_footer(text=f"Source: {result.source_name} | {result.version or 'Current version'}")
    return embed


def build_mission_embed(result: MissionResult) -> discord.Embed:
    embed = discord.Embed(
        title=result.name,
        url=result.source_url,
        color=discord.Color(0x2F8FE5),
    )
    if result.contractor:
        embed.add_field(name="Reputation Giver", value=result.contractor, inline=True)
    if result.region:
        embed.add_field(name="Region", value=result.region, inline=True)
    if result.mission_type:
        embed.add_field(name="Mission Type", value=result.mission_type, inline=True)
    standing = " · ".join(filter(None, [
        result.min_standing_name,
        f"{result.min_standing_reputation:g} rep"
        if result.min_standing_reputation is not None else None,
    ]))
    if standing:
        embed.add_field(name="Required Reputation", value=standing, inline=False)
    rewards = []
    for reward in result.blueprint_rewards:
        chance = f" ({reward.drop_chance * 100:g}%)" if reward.drop_chance is not None else ""
        rewards.append(f"• {reward.name}{chance}")
    embed.add_field(
        name="Blueprint Rewards",
        value="\n".join(rewards)[:1024] if rewards else "No blueprint reward in the current dataset.",
        inline=False,
    )
    embed.set_footer(text=" · ".join(filter(None, [
        "Crusader Industries Contract Network",
        result.source_name,
        result.version,
    ])))
    return embed


def build_blueprint_selection_embed(
    results: list[BlueprintResult],
    category: str | None = None,
    material: str | None = None,
    mission_type: str | None = None,
    contractor: str | None = None,
    page: int = 1,
    has_next: bool = False,
) -> discord.Embed:
    description = [
        _line("Category Filter", category),
        _line("Material Filter", material),
        _line("Mission Type Filter", mission_type),
        _line("Contractor Filter", contractor),
    ]
    embed = discord.Embed(
        title="Blueprint Results",
        description="\n".join(line for line in description if line) or "Available blueprints matching your filters.",
        color=discord.Color.dark_gold(),
    )
    lines = []
    for index, result in enumerate(results[:25], start=1):
        lines.append(f"{index}. {result.name} - {_blueprint_result_label(result)}")

    embed.add_field(
        name="Available Blueprints",
        value=_limit_lines(lines, 1000),
        inline=False,
    )
    page_hint = f"Page {page}"
    if has_next:
        page_hint = f"{page_hint} | More results available"
    embed.set_footer(text=f"{page_hint} | Select a blueprint below to view materials and mission details.")
    return embed


def _blueprint_result_label(result: BlueprintResult) -> str:
    details = [value for value in [result.category, result.component_size] if value]
    return " | ".join(details) if details else "Blueprint"


def build_item_locator_selection_embed(
    results: list[ItemLocatorResult],
    name: str | None = None,
    category: str | None = None,
    section: str | None = None,
    size: str | None = None,
    page: int = 1,
    has_next: bool = False,
) -> discord.Embed:
    description = [
        _line("Search", name),
        _line("Category Filter", category),
        _line("Section Filter", section),
        _line("Size Filter", size),
    ]
    embed = discord.Embed(
        title="Item Locator Results",
        description="\n".join(line for line in description if line) or "In-game buyable items matching your filters.",
        color=discord.Color.green(),
    )
    lines = [
        f"{index}. {result.name} - {_item_locator_result_label(result)}"
        for index, result in enumerate(results[:25], start=1)
    ]
    embed.add_field(name="Available Items", value=_limit_lines(lines, 1000), inline=False)
    page_hint = f"Page {page}"
    if has_next:
        page_hint = f"{page_hint} | More results available"
    embed.set_footer(text=f"{page_hint} | Select an item below to view buy locations.")
    return embed


def build_item_locator_embed(
    result: ItemLocatorResult,
    name: str | None = None,
    category: str | None = None,
    section: str | None = None,
    size: str | None = None,
) -> discord.Embed:
    description = [
        _line("Section", result.section),
        _line("Category", result.category),
        _line("Size", _item_size_label(result.size)),
        _line("Manufacturer", result.company_name),
        _line("Search", name),
        _line("Category Filter", category),
        _line("Section Filter", section),
        _line("Size Filter", size),
    ]
    embed = discord.Embed(
        title=result.name,
        description="\n".join(line for line in description if line),
        url=result.wiki_url or result.source_url,
        color=discord.Color.green(),
    )
    embed.add_field(name="Purchase Locations", value=_format_item_purchase_locations(result.purchases), inline=False)
    embed.set_footer(text=f"Source: {result.source_name}")
    return embed


def build_inventory_search_embed(
    results: list[dict],
    item: str | None = None,
    station: str | None = None,
    category: str | None = None,
    item_type: str | None = None,
    size: str | None = None,
) -> discord.Embed:
    filters = [
        _line("Item", item),
        _line("Station", station),
        _line("Category", category),
        _line("Type", item_type),
        _line("Size", size),
    ]
    filter_text = "\n".join(line for line in filters if line)
    lines: list[str] = []
    shown = 0
    for row in results:
        name = discord.utils.escape_markdown(str(row.get("name") or "Unknown item"))
        location = discord.utils.escape_markdown(str(row.get("location") or "Unknown location"))
        details = [row.get("category"), row.get("item_type")]
        if row.get("item_size"):
            details.append(f"Size {row['item_size']}")
        detail_text = " / ".join(discord.utils.escape_markdown(str(value)) for value in details if value)
        line = f"**{name}** × {_format_number(row.get('quantity'))}"
        if not station:
            line = f"{line} — {location}"
        if detail_text:
            line = f"{line}\n{detail_text}"
        candidate = "\n".join([*lines, line])
        if len(candidate) > 3600:
            break
        lines.append(line)
        shown += 1

    description_parts = [filter_text, "\n".join(lines)]
    embed = discord.Embed(
        title="Your Website Inventory",
        description="\n\n".join(part for part in description_parts if part),
        color=discord.Color.blurple(),
    )
    footer = f"Showing {shown} of {len(results)} matching item{'s' if len(results) != 1 else ''}. Results are private to you."
    embed.set_footer(text=footer)
    return embed


def _item_locator_result_label(result: ItemLocatorResult) -> str:
    details = [
        value
        for value in [result.section, result.category, _item_size_label(result.size)]
        if value
    ]
    return " | ".join(details) if details else "Item"


def _item_size_label(size: str | None) -> str | None:
    if not size:
        return None
    return f"Size {size}" if str(size).isdigit() else str(size)


def _format_item_purchase_locations(purchases: list[ItemPurchaseLocation]) -> str:
    if not purchases:
        return "No current in-game purchase locations found."

    lines = []
    for purchase in purchases[:25]:
        place = " / ".join(part for part in [purchase.system, purchase.planet, purchase.location] if part)
        if not place:
            place = "Unknown location"
        lines.append(
            f"{_format_currency(purchase.price, 'aUEC')} at {purchase.terminal_name} - {place}"
        )
    if len(purchases) > 25:
        lines.append(f"{len(purchases) - 25} more location(s) available in UEX.")
    return _limit_lines(lines, 1000)


def _format_blueprint_ingredients(ingredients: list[BlueprintIngredient]) -> str:
    if not ingredients:
        return "No material data found."

    lines = []
    for ingredient in ingredients:
        quantity = _format_number(ingredient.quantity) if ingredient.quantity is not None else "Unknown"
        unit = ingredient.unit or "SCU"
        slot = f" ({ingredient.slot.title()})" if ingredient.slot else ""
        lines.append(f"{ingredient.name}: {quantity} {unit}{slot}")
    return _limit_lines(lines, 1000)


def _blueprint_mission_lines(missions: list[BlueprintMission]) -> list[str]:
    groups = []
    group_indexes = {}
    for mission in missions:
        rep = mission.min_standing_name or "Unknown"
        if mission.min_standing_reputation is not None:
            rep = f"{rep} ({_format_number(mission.min_standing_reputation)} rep)"
        drop = _format_drop_chance(mission.drop_chance) or "Unknown"
        key = (
            mission.contractor or "Unknown",
            drop,
        )
        if key not in group_indexes:
            group_indexes[key] = len(groups)
            groups.append(
                {
                    "contractor": mission.contractor or "Unknown",
                    "rep": rep,
                    "rep_value": _mission_rep_value(mission),
                    "drop": drop,
                    "missions": [],
                    "seen_missions": set(),
                }
            )
        group = groups[group_indexes[key]]
        if _mission_rep_value(mission) < group["rep_value"]:
            group["rep"] = rep
            group["rep_value"] = _mission_rep_value(mission)

        mission_name = mission.name or "Unknown mission"
        if mission_name in group["seen_missions"]:
            continue
        group["seen_missions"].add(mission_name)
        group["missions"].append(mission_name)

    lines = []
    for group in groups:
        lines.append(
            " | ".join(
                [
                    f"- Contractor: {group['contractor']}",
                    f"Minimum Rep: {group['rep']}",
                    f"Drop Rate: {group['drop']}",
                ]
            )
        )
        for mission_name in group["missions"]:
            lines.append(f"  - {mission_name}")
    return lines


def _format_blueprint_missions(missions: list[BlueprintMission], page: int = 1) -> str:
    if not missions:
        return "No mission drop data found."

    lines = _blueprint_mission_lines(missions)
    start = max(0, page - 1) * BLUEPRINT_MISSION_LINES_PER_PAGE
    page_lines = lines[start : start + BLUEPRINT_MISSION_LINES_PER_PAGE]
    if not page_lines:
        return "No mission drop data found for this page."
    return _limit_lines(page_lines, 1000)


def _blueprint_mission_page_count(missions: list[BlueprintMission]) -> int:
    line_count = len(_blueprint_mission_lines(missions))
    return max(1, (line_count + BLUEPRINT_MISSION_LINES_PER_PAGE - 1) // BLUEPRINT_MISSION_LINES_PER_PAGE)


def _mission_rep_value(mission: BlueprintMission) -> float:
    if mission.min_standing_reputation is None:
        return float("inf")
    return float(mission.min_standing_reputation)


def _format_drop_chance(value: int | float | None) -> str | None:
    if value is None:
        return None
    percent = float(value) * 100 if float(value) <= 1 else float(value)
    return f"{_format_number(percent)}%"


def build_trade_route_embed(
    result: TradeRouteResult,
    starting_point: str,
    max_stops: int,
    stay_system: str | None = None,
) -> discord.Embed:
    loop_line = (
        "Loop: each sell stop is the next buy stop, and the final sell stop returns to the start."
        if not result.requires_empty_return_to_start
        else "Loop: trade legs are chained, then return empty to the starting point because UEX does not list it as a buyer."
    )
    description = [
        _line("Ship", result.ship),
        _line("Starting Point", starting_point),
        _line("Cargo", f"{_format_number(result.cargo_capacity_scu)} SCU"),
        _line("Starting Cash", _format_currency(result.investment, "aUEC")),
        _line("Max Stops", str(max_stops)),
        _line("Estimated Loop Profit", _format_currency(_trade_route_total_profit(result), "aUEC")),
        _line("Estimated Ending Cash", _format_currency(_trade_route_ending_cash(result), "aUEC")),
        _line("Stay In System", stay_system),
        loop_line,
    ]
    embed = discord.Embed(
        title="Circular Route",
        description="\n".join(line for line in description if line),
        color=discord.Color.teal(),
    )

    for index, leg in enumerate(result.legs, start=1):
        embed.add_field(
            name=f"Leg {index}: {leg.commodity_name} - {_format_currency(leg.profit, 'aUEC')} profit",
            value=_format_trade_route_leg(leg),
            inline=False,
        )

    if result.requires_empty_return_to_start and result.legs:
        final_location = _format_route_location(
            result.legs[-1].sell_system,
            result.legs[-1].sell_planet,
            result.legs[-1].sell_location,
            result.legs[-1].sell_terminal,
        )
        embed.add_field(
            name="Return",
            value=f"Fly empty from {final_location} back to {starting_point}.",
            inline=False,
        )

    embed.set_footer(text=f"Source: {result.source_name} average prices, stock, and demand")
    return embed


def _trade_route_total_profit(result: TradeRouteResult) -> float:
    return sum(float(leg.profit) for leg in result.legs)


def _trade_route_ending_cash(result: TradeRouteResult) -> float:
    return float(result.investment) + _trade_route_total_profit(result)


def _format_trade_route_leg(leg: TradeRouteLeg) -> str:
    buy_location = _format_route_location(leg.buy_system, leg.buy_planet, leg.buy_location, leg.buy_terminal)
    sell_location = _format_route_location(leg.sell_system, leg.sell_planet, leg.sell_location, leg.sell_terminal)
    return (
        f"Buy: {_format_currency(leg.buy_price, 'aUEC')}/SCU at {buy_location}\n"
        f"Sell: {_format_currency(leg.sell_price, 'aUEC')}/SCU at {sell_location}\n"
        f"Quantity: {_format_number(leg.quantity_scu)} SCU | "
        f"Cost: {_format_currency(leg.investment_used, 'aUEC')}"
    )


def _format_route_location(
    system: str | None,
    planet: str | None,
    location: str | None,
    terminal: str,
) -> str:
    parts = [part for part in [system, planet, location or terminal] if part]
    return " / ".join(parts) or terminal


def build_commands_reference_embeds(settings: Settings | None = None) -> list[discord.Embed]:
    reference_path = Path("docs/commands.md")
    markdown = reference_path.read_text(encoding="utf-8").strip()
    if markdown.startswith("# Discord Bot Commands"):
        markdown = markdown.removeprefix("# Discord Bot Commands").strip()

    embeds = []
    if settings and settings.command_channel_ids:
        embeds.append(build_command_channel_directory_embed(settings))

    sections = _command_reference_sections(markdown)
    for command_name, body in sections:
        chunks = _chunk_text(body, 3500)
        for index, chunk in enumerate(chunks):
            title = f"Discord Bot Commands - {command_name}"
            if len(chunks) > 1:
                title = f"{title} ({index + 1}/{len(chunks)})"
            embed = discord.Embed(
                title=title,
                description=chunk,
                color=discord.Color.blurple(),
            )
            embed.set_footer(text="Auto-updated from docs/commands.md when the bot starts")
            embeds.append(embed)

    return embeds


def _message_embed_matches(message: discord.Message, embed: discord.Embed) -> bool:
    if len(message.embeds) != 1:
        return False
    return message.embeds[0].to_dict() == embed.to_dict()


def build_command_channel_directory_embed(settings: Settings) -> discord.Embed:
    channel_commands: dict[int, list[str]] = {}
    for command_name, channel_id in settings.command_channel_ids.items():
        channel_commands.setdefault(channel_id, []).append(f"/{command_name}")
    blueprint_channel = settings.command_channel_ids.get("blueprint")
    if blueprint_channel and "mission" not in settings.command_channel_ids:
        blueprint_commands = channel_commands.setdefault(blueprint_channel, [])
        if "/mission" not in blueprint_commands:
            blueprint_commands.append("/mission")
    inventory_commands = channel_commands.setdefault(INVENTORY_CHANNEL_ID, [])
    if "/inventory search" not in inventory_commands:
        inventory_commands.append("/inventory search")

    lines = []
    for channel_id, command_names in sorted(channel_commands.items(), key=lambda item: min(item[1])):
        commands = ", ".join(sorted(command_names))
        lines.append(f"<#{channel_id}>: {commands}")

    embed = discord.Embed(
        title="Discord Bot Commands - Channel Directory",
        description="\n".join(lines) if lines else "No command channel restrictions configured.",
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="Channel names are rendered by Discord from the configured channel IDs")
    return embed


def _command_reference_sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    for line in markdown.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line.removeprefix("## ").strip()
            current_lines = []
            continue

        if current_title is not None:
            current_lines.append(line)

    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip()))

    return sections


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


def _format_location_group(locations: list[str]) -> str:
    if not locations:
        return "No matching locations found."

    lines = []
    for location in locations:
        candidate = "\n".join([*lines, location])
        if len(candidate) > 1000:
            lines.append("More locations available in UEX.")
            break
        lines.append(location)
    return "\n".join(lines)


def _has_mining_multi_separator(value: str) -> bool:
    return bool(re.search(r"\s*(,|;|\+|&|\band\b)\s*", value, flags=re.IGNORECASE))


def _mining_multi_search_terms(value: str) -> list[str]:
    if not _has_mining_multi_separator(value):
        return [value.strip()] if value.strip() else []
    return [
        term.strip()
        for term in re.split(r"\s*(?:,|;|\+|&|\band\b)\s*", value, flags=re.IGNORECASE)
        if term.strip()
    ]


def _mining_space_search_terms(value: str) -> list[str]:
    return [term.strip() for term in value.split() if term.strip()]


def _mining_autocomplete_prefix(value: str) -> tuple[str, str]:
    match = re.search(r"^(?P<prefix>.*(?:,|;|\+|&|\band\b)\s*)(?P<partial>[^,;+&]*)$", value, flags=re.IGNORECASE)
    if match is None:
        return "", value
    return match.group("prefix"), match.group("partial")


def _mining_term_signatures(result: MiningLocationResult, term: str) -> list[int]:
    signatures = result.rock_signatures or []
    signature = _mining_signature_number(term)
    if signature is None:
        return signatures
    return [
        base_signature
        for base_signature in signatures
        if _mining_signature_matches_cluster(signature, base_signature)
    ]


def _mining_signature_number(value: object) -> int | None:
    text = str(value or "").replace(",", "").strip()
    return int(text) if text.isdigit() else None


def _mining_signature_matches_cluster(signature: int, base_signature: int) -> bool:
    return signature == base_signature or (signature % base_signature == 0 and 1 <= signature // base_signature <= 6)


def _shared_mining_signatures(signature_groups: list[list[int]]) -> list[int]:
    if not signature_groups or any(not signatures for signatures in signature_groups):
        return []
    shared = set(signature_groups[0])
    for signatures in signature_groups[1:]:
        shared.intersection_update(signatures)
    return sorted(shared)


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = _normalize_text(value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


async def add_community_mining_location(cache: SQLiteCache, entry: dict) -> None:
    entries = await _community_mining_entries(cache)
    key = _normalize_text(entry.get("material"))
    material_entries = entries.setdefault(key, [])
    new_entry = {
        "material": str(entry.get("material") or "").strip(),
        "system": str(entry.get("system") or "").strip(),
        "location_type": str(entry.get("location_type") or "").strip(),
        "location": str(entry.get("location") or "").strip(),
        "reported_by": str(entry.get("reported_by") or "").strip(),
    }
    duplicate = any(
        _normalize_text(existing.get("system")) == _normalize_text(new_entry["system"])
        and _normalize_text(existing.get("location_type")) == _normalize_text(new_entry["location_type"])
        and _normalize_text(existing.get("location")) == _normalize_text(new_entry["location"])
        for existing in material_entries
        if isinstance(existing, dict)
    )
    if not duplicate:
        material_entries.append(new_entry)
    await cache.set(MINING_COMMUNITY_LOCATIONS_CACHE_KEY, entries, 315360000)


async def apply_community_mining_locations(
    cache: SQLiteCache,
    result: MiningLocationResult,
) -> MiningLocationResult:
    entries = await _community_mining_entries(cache)
    material_entries = entries.get(_normalize_text(result.material_name), [])
    if not material_entries:
        return result

    groups_by_system: dict[str, MiningSystemLocations] = {
        _normalize_text(group.system): group
        for group in result.location_groups or []
    }
    groups = list(result.location_groups or [])
    systems = list(result.systems)
    lagrange_points = list(result.lagrange_points)
    planets = list(result.planets)
    moons = list(result.moons)
    points_of_interest = list(result.points_of_interest)

    for entry in material_entries:
        if not isinstance(entry, dict):
            continue
        system = str(entry.get("system") or "").strip()
        location_type = str(entry.get("location_type") or "").strip()
        location = str(entry.get("location") or "").strip()
        if not system or location_type not in _mining_location_type_labels() or not location:
            continue

        system_key = _normalize_text(system)
        if system_key not in groups_by_system:
            group = MiningSystemLocations(system=system, lagrange_points=[], planets=[], moons=[], points_of_interest=[])
            groups_by_system[system_key] = group
            groups.append(group)
        group = groups_by_system[system_key]
        _append_unique(getattr(group, location_type), f"{location} (Community)")
        _append_unique(systems, system)
        _append_unique(
            {
                "lagrange_points": lagrange_points,
                "planets": planets,
                "moons": moons,
                "points_of_interest": points_of_interest,
            }[location_type],
            f"{location} (Community)",
        )

    return MiningLocationResult(
        material_name=result.material_name,
        code=result.code,
        kind=result.kind,
        refined_sell_price=result.refined_sell_price,
        raw_sell_price=result.raw_sell_price,
        is_harvestable=result.is_harvestable,
        is_volatile_qt=result.is_volatile_qt,
        is_volatile_time=result.is_volatile_time,
        is_explosive=result.is_explosive,
        systems=systems,
        lagrange_points=lagrange_points,
        planets=planets,
        moons=moons,
        points_of_interest=points_of_interest,
        source_url=result.source_url,
        source_name=result.source_name,
        location_basis=result.location_basis,
        rock_signatures=result.rock_signatures or [],
        location_groups=groups,
    )


async def _community_mining_entries(cache: SQLiteCache) -> dict:
    entries = await cache.get(MINING_COMMUNITY_LOCATIONS_CACHE_KEY)
    return entries if isinstance(entries, dict) else {}


def _mining_location_type_labels() -> dict[str, str]:
    return {
        "lagrange_points": "Lagrange Points",
        "planets": "Planets",
        "moons": "Moons",
        "points_of_interest": "Points of Interest",
    }


def _append_unique(values: list[str], value: str) -> None:
    if all(_normalize_text(existing) != _normalize_text(value) for existing in values):
        values.append(value)


def _mining_location_lines(result: MiningLocationResult) -> list[str]:
    groups = result.location_groups or []
    if not groups and result.systems:
        groups = [
            type(
                "MiningLocationGroup",
                (),
                {
                    "system": "All Systems",
                    "lagrange_points": result.lagrange_points,
                    "planets": result.planets,
                    "moons": result.moons,
                    "points_of_interest": result.points_of_interest,
                },
            )()
        ]

    lines: list[str] = []
    for group in groups:
        detail_lines = [
            _mining_location_detail_line("Lagrange Points", group.lagrange_points),
            _mining_location_detail_line("Planets", group.planets),
            _mining_location_detail_line("Moons", group.moons),
            _mining_location_detail_line("Points of Interest", group.points_of_interest),
        ]
        detail_lines = [line for line in detail_lines if line]
        if not detail_lines:
            continue
        if lines:
            lines.append("")
        lines.append(f"**{group.system}**")
        lines.extend(detail_lines)

    return lines or ["No matching locations found."]


def _mining_system_group_has_locations(group: MiningSystemLocations) -> bool:
    return any([group.lagrange_points, group.planets, group.moons, group.points_of_interest])


def _mining_result_for_system(result: MiningLocationResult, system: str) -> MiningLocationResult:
    normalized_system = _normalize_text(system)
    group = next(
        (
            group
            for group in result.location_groups or []
            if _normalize_text(group.system) == normalized_system
        ),
        None,
    )
    if group is None:
        return result

    return MiningLocationResult(
        material_name=result.material_name,
        code=result.code,
        kind=result.kind,
        refined_sell_price=result.refined_sell_price,
        raw_sell_price=result.raw_sell_price,
        is_harvestable=result.is_harvestable,
        is_volatile_qt=result.is_volatile_qt,
        is_volatile_time=result.is_volatile_time,
        is_explosive=result.is_explosive,
        systems=[group.system],
        lagrange_points=group.lagrange_points,
        planets=group.planets,
        moons=group.moons,
        points_of_interest=group.points_of_interest,
        source_url=result.source_url,
        source_name=result.source_name,
        location_basis=result.location_basis,
        rock_signatures=result.rock_signatures,
        location_groups=[group],
    )


def _mining_location_detail_line(label: str, locations: list[str]) -> str | None:
    if not locations:
        return None
    return f"{label}: {', '.join(locations)}"


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").lower().replace("-", " ").split())


def _mining_location_pages(result: MiningLocationResult) -> list[list[str]]:
    lines = _mining_location_lines(result)
    pages = [
        lines[index : index + MINING_LOCATION_LINES_PER_PAGE]
        for index in range(0, len(lines), MINING_LOCATION_LINES_PER_PAGE)
    ]
    return pages or [["No matching locations found."]]


def _mining_location_page_count(result: MiningLocationResult) -> int:
    return len(_mining_location_pages(result))


def _format_mining_location_page(result: MiningLocationResult, page: int = 1) -> str:
    pages = _mining_location_pages(result)
    page = max(1, min(page, len(pages)))
    return _limit_lines(pages[page - 1], 1000)


def _format_mining_flags(result: MiningLocationResult) -> str | None:
    flags = []
    if result.is_harvestable:
        flags.append("Harvestable")
    if result.is_volatile_qt:
        flags.append("QT sensitive")
    if result.is_volatile_time:
        flags.append("Time sensitive")
    if result.is_explosive:
        flags.append("Explosive")
    return ", ".join(flags) if flags else None


def _format_rock_signatures(signatures: list[int] | None) -> str:
    if not signatures:
        return "No rock signature data found."

    lines = []
    for signature in signatures[:8]:
        clusters = [f"{count}x {_format_number(signature * count)}" for count in range(1, 7)]
        lines.append(f"{_format_number(signature)}: {' | '.join(clusters)}")
    if len(signatures) > 8:
        lines.append("More signatures available in Star-Head.")
    return _limit_lines(lines, 1000)


def _format_mining_signature_block(signatures: list[int] | None) -> str:
    return f"Rock Signatures:\n{_format_rock_signatures(signatures)}"


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


def _format_seconds_duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    remaining_minutes = minutes % 60
    return f"{hours} hr {remaining_minutes} min" if remaining_minutes else f"{hours} hr"


def _limit_lines(lines: list[str], max_length: int) -> str:
    kept = []
    for line in lines:
        candidate = "\n".join([*kept, line])
        if len(candidate) > max_length:
            kept.append("More available.")
            break
        kept.append(line)
    return "\n".join(kept)


def _focused_option_name(interaction: discord.Interaction) -> str:
    def find_focused(options: list[dict]) -> str | None:
        for option in options:
            if option.get("focused"):
                return str(option.get("name") or "")
            nested = option.get("options")
            if isinstance(nested, list):
                focused = find_focused(nested)
                if focused:
                    return focused
        return None

    data = interaction.data if isinstance(interaction.data, dict) else {}
    options = data.get("options")
    if not isinstance(options, list):
        return ""
    return find_focused(options) or ""


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
