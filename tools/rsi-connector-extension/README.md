# Game Assist RSI Connector

This optional local browser extension lets the Game Assist website update your Hangar from your RSI pledge pages without downloading HTML files manually.

It only runs on:

- `http://127.0.0.1:8000/*`
- `http://localhost:8000/*`

It fetches:

- `https://robertsspaceindustries.com/en/account/pledges?page=1&product-type=`

using your existing browser RSI login session. It does not ask for, display, store, or send your RSI password or cookie value to the website.

## Install in Chrome or Edge

1. Open `chrome://extensions` or `edge://extensions`.
2. Turn on Developer mode.
3. Choose `Load unpacked`.
4. Select this folder:

   `C:\Users\1121b\OneDrive\Documents\Website\tools\rsi-connector-extension`

5. Sign into RSI in the same browser.
6. Open Game Assist at `http://127.0.0.1:8000/`.
7. Click `Ships`, then `Update` beside Hangar.
