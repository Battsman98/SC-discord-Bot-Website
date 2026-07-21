# Edge certification notes

This Manifest V3 extension requires an existing RSI login because RSI hangar contents are private third-party account data. Publisher credentials cannot be supplied for a third-party RSI account.

1. Install the extension in Edge.
2. Sign into `https://robertsspaceindustries.com/` in the same profile with an account containing pledged ships.
3. Open `https://sccompanion.org/` and authenticate with Discord.
4. Select Ships > Hangar > Import RSI Hangar.
5. Confirm that ship and vehicle names are imported and non-vehicle extras are excluded.

The extension performs read-only RSI page requests only after the user action. It performs no background polling and cannot purchase, gift, reclaim, melt, exchange, or modify pledges.

Support: https://github.com/Battsman98/SC-discord-Bot-Website/issues
