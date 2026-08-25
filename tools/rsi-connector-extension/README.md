# Game Assist RSI Hangar Importer

This optional local browser extension lets the Game Assist website import ships and vehicles from your RSI pledge hangar without downloading HTML files manually. The website rejects upgrades, CCUs, paints, equipment, flair, and other non-vehicle extras.

This is an unofficial fan-made extension. It is not affiliated with, endorsed by, sponsored by, or authorized by Cloud Imperium Games or Roberts Space Industries, and it does not claim authorization from either company.

It only runs on:

- `https://sccompanion.org/*`
- `https://star-citizen-game-assist.onrender.com/*`
- `http://127.0.0.1:8000/*`
- `http://localhost:8000/*`

It fetches:

- `https://robertsspaceindustries.com/account/pledges`

using your existing browser RSI login session. It does not ask for, display, store, or send your RSI password or cookie value to the website.

## Install in Chrome or Edge

1. Open `chrome://extensions` or `edge://extensions`.
2. Turn on Developer mode.
3. Choose `Load unpacked`.
4. Select this folder:

   `C:\Users\1121b\OneDrive\Documents\Website\tools\rsi-connector-extension`

5. Sign into RSI in the same browser.
6. Open [SC Companion](https://sccompanion.org/).
7. Click `Ships`, then `Import RSI Hangar`.

## Install in Firefox

Use the packaged Firefox ZIP from `web/rsi-connector-extension-firefox-v0.4.9.zip`:

1. Open `about:debugging#/runtime/this-firefox`.
2. Choose `Load Temporary Add-on`.
3. Select the Firefox ZIP.
4. Sign into RSI in the same Firefox profile.
5. Open [SC Companion](https://sccompanion.org/), click `Ships`, then `Import RSI Hangar`.

Temporary add-ons are removed when Firefox closes. A permanent installation requires a Mozilla-signed package.

Version 0.4.9 reports pledge-page scan progress, imports only RSI items explicitly typed as ships or vehicles, and sends privacy-safe parser health metrics and a structural fingerprint to SC Companion.
