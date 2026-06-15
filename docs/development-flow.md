# Development Flow

## Phase 1: Local Computer

1. Install Python 3.12+ and Git.
2. Run:

   ```powershell
   scripts\setup-local.ps1
   ```

3. Add your Discord bot token to `.env`.
4. Start the bot:

   ```powershell
   scripts\run-bot.ps1
   ```

5. Test slash commands in your private Discord server.

## Phase 2: GitHub

1. Create a new empty GitHub repository.
2. Connect this local repo:

   ```powershell
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
   git push -u origin main
   ```

3. Use branches for new features:

   ```powershell
   git checkout -b codex/source-name
   ```

4. Commit and push small working changes.

## Phase 3: VPS

1. Create a non-root app directory such as `/opt/game-assist-bot`.
2. Clone the GitHub repo.
3. Create the VPS `.env` file manually.
4. Install dependencies in a virtual environment.
5. Run the bot with `systemd`.
6. Watch logs with:

   ```bash
   sudo journalctl -u game-assist-bot -f
   ```

## Source Rules

- Prefer official APIs over scraping.
- Cache website results.
- Keep request rates low.
- Do not commit `.env`, tokens, API keys, cookies, or scraped private data.
