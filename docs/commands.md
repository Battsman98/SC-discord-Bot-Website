# Discord Bot Commands

This file is the running command reference for the Star Citizen Discord bot. Update it whenever commands, options, or behavior change.

If `COMMANDS_CHANNEL_ID` is set in `.env`, the bot posts or updates this command reference in that Discord channel when the bot starts.

## `/status`

Checks whether the bot is online.

Response visibility: private to the user.

Options: none.

## `/lookup`

Searches general Star Citizen game information.

Response visibility: private to the user.

Options:

| Option | Required | Purpose |
| --- | --- | --- |
| `query` | Yes | Ship, item, location, mission, company, or topic to search for. |

## `/ship`

Looks up a Star Citizen ship or vehicle.

Response visibility: private to the user.

Autocomplete:

- `name` supports ship/vehicle dropdown suggestions.
- Users can still type a ship or vehicle name manually.

Options:

| Option | Required | Purpose |
| --- | --- | --- |
| `name` | Yes | Ship or vehicle name to search for. |

Current output:

- Manufacturer
- Type
- Role
- Size
- Status
- Cargo capacity
- Crew
- Pledge store availability
- Pledge price, warbond price, and package price when available
- RSI pledge page link
- In-game purchase price and locations

## `/commodity`

Looks up Star Citizen commodity pricing and locations using UEX data.

Response visibility: private to the user.

Autocomplete:

- `name` supports commodity dropdown suggestions.
- Commodity search supports both full commodity names and commodity codes.
- System options support `Stanton`, `Pyro`, and `Nyx`.

Options:

| Option | Required | Purpose |
| --- | --- | --- |
| `name` | Yes | Commodity name or code, such as `Gold`, `Agricium`, `GOLD`, or `AGRI`. |
| `system` | No | Filters both purchase and sell locations to one star system. |
| `purchase_system` | No | Filters purchase locations only. Overrides `system` for purchase locations. |
| `sell_system` | No | Filters sell locations only. Overrides `system` for sell locations. |
| `quantity_scu` | No | SCU amount used to estimate buy cost and sell payout. |

Current output:

- Commodity code
- Top 3 purchase locations
- Top 3 sell locations
- Optional estimate for `quantity_scu`

Purchase location logic:

- Filters by `system` or `purchase_system` when provided.
- Uses average terminal sell price from UEX.
- Shows the top 3 lowest average prices, meaning the cheapest places for the player to buy.

Sell location logic:

- Filters by `system` or `sell_system` when provided.
- Uses average terminal buy price from UEX.
- Shows the top 3 highest average prices, meaning the best places for the player to sell.

Examples:

```text
/commodity Gold
/commodity AGRI
/commodity Gold system:Stanton
/commodity Gold purchase_system:Stanton sell_system:Pyro
/commodity Gold purchase_system:Stanton sell_system:Pyro quantity_scu:100
```
