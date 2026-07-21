# Chrome reviewer notes

The extension requires an existing RSI login because RSI hangar contents are private third-party account data. Publisher credentials cannot be provided for a third-party RSI account.

Testing steps:

1. Install the extension.
2. Sign into `https://robertsspaceindustries.com/` in the same Chrome profile with an account containing pledge-hangar ships.
3. Open `https://sccompanion.org/` and sign in with Discord.
4. Select Ships, then Hangar.
5. Click Import RSI Hangar.
6. Confirm that standalone, packaged, and upgraded-pledge ships are added.
7. Confirm that CCUs, paints, equipment, flair, currency, and other extras are excluded.

The extension performs a read-only GET of RSI pledge pages after the user's click. It cannot buy, gift, exchange, reclaim, melt, or modify pledges. It performs no background polling. Only normalized ship/vehicle names cross from the extension into SC Companion.

Support for reviewer questions: https://github.com/Battsman98/SC-discord-Bot-Website/issues
