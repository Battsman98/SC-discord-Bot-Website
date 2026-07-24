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
- `/industry split`, `/industry refinery`, and `/industry brief` plan crew payouts, completion times, and operation posts.
- `/blueprint` searches crafting blueprints, materials, missions, and rep requirements.
- `/mission` searches missions by name, region, reputation giver, reputation level, and type.

Blueprint and mission searches read only from `data/blueprints_snapshot.json`.
The running website and Discord bot do not automatically fetch or refresh this
data; update the snapshot manually when you want to move to a newer game patch.

To update and publish that snapshot from the installed game files, double-click
`Update Star Citizen Database.cmd` in the project folder (or use the desktop
shortcut with the same name). The updater:

- reads `C:\StarCitizen\LIVE\Data.p4k`;
- rebuilds the mission and blueprint snapshot;
- runs the automated checks;
- commits and pushes only the snapshot; and
- waits for the hosted website to confirm the deployed game version.

The importer defaults to `C:\StarCitizen\LIVE\Data.p4k`, keeps its large
extraction cache outside the project under Local AppData, and never runs during
website or bot startup.

The hosted **Audit → Game Database** panel is status-only. It shows which
snapshot the website and Discord bot are currently using; the local website is
not part of the update process.

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

## Website Companion

Run the browser companion locally with:

```powershell
python -m uvicorn src.web:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`.

To link website permissions to Discord, create an OAuth2 redirect for the Discord application and set:

```env
DISCORD_CLIENT_ID=your-application-client-id
DISCORD_CLIENT_SECRET=your-application-client-secret
DISCORD_REDIRECT_URI=http://127.0.0.1:8000/auth/discord/callback
WEB_SESSION_SECRET=replace-with-a-long-random-secret
```

The website uses the same `DISCORD_GUILD_ID`, `EXEC_ADMIN_ROLE_IDS`, `BOT_ADMIN_ROLE_IDS`, and `BOT_ADMIN_USER_IDS` permission model as the bot. Users must be members of the configured Discord server. If no matching role IDs or user IDs are configured for a permission group, users with Discord's Manage Server permission can use those website actions.

### Import RSI Hangar

The Hangar `Import RSI Hangar` button can import pledged ships and vehicles from your RSI account through the optional local importer extension in:

```text
tools\rsi-connector-extension
```

Install it in Chrome or Edge with `Load unpacked`, sign into RSI in that same browser, then click `Import RSI Hangar`. The extension uses your browser's existing RSI session to fetch pledge pages for the local website. Only ships and vehicles from standalone pledges and game packages are imported; upgrades, paints, equipment, flair, and other extras are ignored. It does not ask for or store your RSI password or cookie value.

After the extension is installed and the user is signed into RSI, importing is one click from the deployed website. The connector accepts requests only from `https://sccompanion.org`, the Render service origin, and the documented local development origins.

Game Assist and its RSI Hangar Importer are unofficial fan-made projects. They are not affiliated with, endorsed by, sponsored by, or authorized by Cloud Imperium Games or Roberts Space Industries, and they do not claim authorization from either company.

If the connector is not installed, the website falls back to importing saved RSI pledge HTML files.

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

## Render Deployment

The included `render.yaml` deploys the website and Discord bot together as one
Starter web service. A 1 GB persistent disk stores the shared SQLite database at
`/var/data/bot.sqlite3`. Keeping both processes in one service is required while
the project uses SQLite because a Render disk cannot be shared between separate
services.

1. Push this repository to GitHub.
2. In Render, select **New > Blueprint** and connect the repository.
3. Supply every environment variable marked `sync: false`. Copy the values from
   the local `.env` file into Render's environment-variable form; never commit
   the `.env` file.
4. Set `DISCORD_REDIRECT_URI` to the Render service URL followed by
   `/auth/discord/callback`, for example:

   ```text
   https://star-citizen-game-assist.onrender.com/auth/discord/callback
   ```

5. Add that exact HTTPS callback URL under **OAuth2 > Redirects** in the Discord
   Developer Portal.
6. Deploy the Blueprint, then verify `/api/health` and sign in through Discord.

The first deployment starts with a new database. To preserve existing hangar,
blueprint, inventory, timer, and audit data, copy `data/bot.sqlite3` to the
mounted Render disk before using the production site. Do not run the local bot
and the Render bot with the same token at the same time after cutover.

## GitHub Notes

Never commit `.env` or bot tokens. Commit `.env.example` instead.

See `docs/development-flow.md` for the local-to-GitHub-to-VPS workflow.
