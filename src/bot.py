import logging
import asyncio
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import CommodityMarket, CommodityResult, ShipResult
from src.sources.registry import SourceRegistry, build_default_registry
from src.sources.sc_trade_tools import build_trade_route_url
from src.timers import (
    ExecHangarStatus,
    calculate_countdown_end_unix,
    calculate_cycle_start_from_phase,
    calculate_exec_hangar_status,
    fetch_exec_cycle_start_unix,
)


EXEC_OVERRIDE_CACHE_KEY = "exec:cycle-start-override"
CZ_TIMERS_CACHE_KEY = "cz:dashboard:timers"
CZ_TIMER_DEFINITIONS = {
    "blue_keycard": ("Blue Keycards", 15 * 60),
    "compboard": ("Compboards / Tablets", 30 * 60),
    "red_keycard": ("Red Keycards", 30 * 60),
    "timer_door": ("Timer Doors", 20 * 60),
}


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
        self._exec_status_task: asyncio.Task | None = None
        self._cz_timers_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        self.add_view(CZTimerDashboardView())
        self.tree.add_command(status_command)
        self.tree.add_command(lookup_command)
        self.tree.add_command(ship_command)
        self.tree.add_command(commodity_command)
        self.tree.add_command(exec_command)
        self.tree.add_command(execset_command)
        self.tree.add_command(execclear_command)
        self.tree.add_command(cztimer_command)

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
        await self.sync_exec_status_message()
        await self.sync_cz_timers_message()

        if self.settings.exec_status_channel_id and self._exec_status_task is None:
            self._exec_status_task = asyncio.create_task(self._exec_status_loop())
        if self.settings.cz_timers_channel_id and self._cz_timers_task is None:
            self._cz_timers_task = asyncio.create_task(self._cz_timers_loop())

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

        embeds = build_commands_reference_embeds()
        cache_key = f"discord:commands-reference-message:{self.settings.commands_channel_id}"
        cached_message_ids = await self.cache.get(cache_key)
        message_ids: list[int] = []
        if isinstance(cached_message_ids, int):
            message_ids = [cached_message_ids]
        elif isinstance(cached_message_ids, list):
            message_ids = [message_id for message_id in cached_message_ids if isinstance(message_id, int)]

        updated_message_ids: list[int] = []
        for index, embed in enumerate(embeds):
            if index < len(message_ids):
                try:
                    message = await channel.fetch_message(message_ids[index])
                    await message.edit(content=None, embed=embed)
                    updated_message_ids.append(message.id)
                    continue
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    logging.info("Could not update commands reference message part %s; creating a new one", index + 1)

            message = await channel.send(embed=embed)
            updated_message_ids.append(message.id)

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
                await message.edit(content=None, embed=embed)
                logging.info("Updated Executive Hangar status message %s", message_id)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logging.info("Could not update previous Executive Hangar status message; creating a new one")

        message = await channel.send(embed=embed)
        await self.cache.set(cache_key, message.id, 315360000)
        logging.info("Created Executive Hangar status message %s", message.id)

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
                await message.edit(content=None, embed=embed, view=view)
                logging.info("Updated CZ timers dashboard message %s", message_id)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logging.info("Could not update previous CZ timers dashboard; creating a new one")

        message = await channel.send(embed=embed, view=view)
        await self.cache.set(cache_key, message.id, 315360000)
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
    route_mode="Choose commodity prices or a circular route link.",
    name="Commodity name or code. Required for commodity prices.",
    system="Optional star system filter for both purchase and sell locations.",
    purchase_system="Optional system filter for purchase locations only.",
    sell_system="Optional system filter for sell locations only.",
    quantity_scu="Optional SCU amount for estimated buy cost and sell payout.",
    route_ship="Ship for circular route planning.",
    investment="aUEC investment for circular route planning.",
    max_stops="Maximum circular route stops, from 1 to 5.",
)
@app_commands.choices(
    route_mode=[
        app_commands.Choice(name="Commodity Prices", value="commodity_prices"),
        app_commands.Choice(name="Circular Route", value="circular_route"),
    ]
)
async def commodity_command(
    interaction: discord.Interaction,
    name: str | None = None,
    route_mode: app_commands.Choice[str] | None = None,
    system: str | None = None,
    purchase_system: str | None = None,
    sell_system: str | None = None,
    quantity_scu: float | None = None,
    route_ship: str = "Ironclad Assault",
    investment: int = 1_000_000,
    max_stops: int = 5,
) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    selected_mode = route_mode.value if route_mode else "commodity_prices"
    if selected_mode == "circular_route":
        if investment <= 0:
            await interaction.response.send_message("Investment must be greater than 0 aUEC.", ephemeral=True)
            return
        if max_stops < 1 or max_stops > 5:
            await interaction.response.send_message("Max stops must be between 1 and 5.", ephemeral=True)
            return

        route_url = build_trade_route_url(route_ship, investment, max_stops)
        embed = build_circular_route_embed(route_ship, investment, max_stops, route_url, bool(bot.settings.sc_trade_tools_token))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if not name:
        await interaction.response.send_message("Commodity name or code is required for commodity price lookups.", ephemeral=True)
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


@app_commands.command(name="exec", description="Show the current Executive Hangar clock.")
async def exec_command(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if not isinstance(bot, GameAssistBot):
        await interaction.response.send_message("Bot is not fully initialized.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    try:
        status_context = await bot.resolve_exec_status_context()
    except Exception:
        await interaction.followup.send("Could not fetch the Executive Hangar timer right now.")
        return

    await interaction.followup.send(embed=build_exec_status_embed(status_context))


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


def _can_manage_exec_timer(interaction: discord.Interaction, settings: Settings) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False

    if settings.exec_admin_role_ids:
        user_role_ids = {role.id for role in user.roles}
        return bool(user_role_ids.intersection(settings.exec_admin_role_ids))

    return user.guild_permissions.manage_guild


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


def build_circular_route_embed(
    ship: str,
    investment: int,
    max_stops: int,
    route_url: str,
    has_api_token: bool,
) -> discord.Embed:
    embed = discord.Embed(
        title="Circular Route",
        description=(
            f"Ship: {ship}\n"
            f"Investment: {_format_currency(investment, 'aUEC')}\n"
            f"Max Stops: {max_stops}\n"
            f"[Open SC Trade Tools route]({route_url})"
        ),
        url=route_url,
        color=discord.Color.teal(),
    )
    if has_api_token:
        embed.add_field(
            name="API",
            value="SC Trade Tools API token is configured. Direct in-Discord route results can be wired next.",
            inline=False,
        )
    else:
        embed.add_field(
            name="API",
            value="Direct route results require a SC Trade Tools API token. For now, this opens the prefilled route planner.",
            inline=False,
        )
    embed.set_footer(text="Source: SC Trade Tools")
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
