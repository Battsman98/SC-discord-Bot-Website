# In-Game Assistance Discord Bot

Python Discord bot for collecting information from approved websites/APIs and serving it through Discord commands for in-game assistance.

## Features

- Slash command-ready Discord bot using `discord.py`
- Environment-based secrets through `.env`
- Star Citizen lookup support through Star Citizen Wiki data
- Website/API source abstraction for adding more game data providers
- SQLite cache to avoid repeated website requests
- VPS-friendly `systemd` service example

## Discord Commands

- `/status` checks whether the bot is online.
- `/lookup` searches Star Citizen game information.
- `/ship` looks up a Star Citizen ship or vehicle.
- `/commodity` looks up commodity pricing and locations.
- `/blueprint` searches crafting blueprints, materials, missions, and rep requirements.
- `/trade routing` calculates UEX-based circular trade route candidates.
- `/exec` shows the Executive Hangar clock.
- `/execset` corrects the Executive Hangar clock for approved users.
- `/execclear` clears an Executive Hangar manual override.
- `/cztimer` starts a contested-zone helper countdown.

See `docs/commands.md` for the full command reference.

Set `COMMANDS_CHANNEL_ID` in `.env` to have the bot auto-post/update the command reference in a Discord channel on startup.

Set `COMMAND_CHANNEL_IDS` in `.env` to restrict commands to specific Discord channels. Use command names without the leading slash:

```env
COMMAND_CHANNEL_IDS=ship:111111111111111111,commodity:222222222222222222,trade routing:333333333333333333,item locator:444444444444444444
```

Commands not listed in `COMMAND_CHANNEL_IDS` can be used in any channel.

Set `AUDIT_LOG_CHANNEL_ID` in `.env` to post a remote audit view of command usage, blocked command attempts, and manual changes such as Executive Hangar corrections, CZ timer updates, and community mining location additions.

Set `EXEC_STATUS_CHANNEL_ID` in `.env` to have the bot keep a public Executive Hangar status message updated every 60 seconds.

Set comma-separated `EXEC_ADMIN_ROLE_IDS` in `.env` to restrict change commands to specific Discord roles. This includes `/execset`, `/execclear`, and `/miningadd`.

Set comma-separated `BOT_ADMIN_ROLE_IDS` and/or `BOT_ADMIN_USER_IDS` in `.env` to restrict bot management and audit commands. This includes `/admin channels`, `/admin health`, and `/audit recent`. If no admin role IDs or user IDs are configured, users with Manage Server can use those commands.

Set `CZ_TIMERS_CHANNEL_ID` in `.env` to have the bot keep a public Contested Zone timer dashboard with clickable start/reset buttons.

## Local Setup

Install Python 3.12+ first. On Windows, make sure Python is added to PATH.

You can use the helper script:

```powershell
scripts\setup-local.ps1
```

Or set up manually:

1. Create a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

   For test tools:

   ```powershell
   pip install -r requirements-dev.txt
   ```

3. Create your `.env` file:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Edit `.env` and set `DISCORD_TOKEN`.

5. Run the bot:

   ```powershell
   python -m src.bot
   ```

## Tests

```powershell
pytest
```

## Adding Website Sources

Create a new source in `src/sources/` that implements `GameInfoSource`, then register it in `src/sources/registry.py`.

Prefer official APIs when available. If scraping is needed, check the website's terms of service and use caching/rate limits.

## VPS Deployment

Example `systemd` service:

```ini
[Unit]
Description=In-Game Assistance Discord Bot
After=network.target

[Service]
WorkingDirectory=/opt/game-assist-bot
ExecStart=/opt/game-assist-bot/.venv/bin/python -m src.bot
Restart=always
RestartSec=5
EnvironmentFile=/opt/game-assist-bot/.env

[Install]
WantedBy=multi-user.target
```

Common VPS commands:

```bash
sudo systemctl daemon-reload
sudo systemctl enable game-assist-bot
sudo systemctl start game-assist-bot
sudo journalctl -u game-assist-bot -f
```

## GitHub Notes

Never commit `.env` or bot tokens. Commit `.env.example` instead.

See `docs/development-flow.md` for the local-to-GitHub-to-VPS workflow.
