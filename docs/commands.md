# Discord Bot Commands

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

## `/blueprint`

Searches Star Citizen crafting blueprints using SC Craft Tools data.

Response visibility: private to the user.

Behavior:

- `name` shows full blueprint details immediately.
- Filter-only searches show a selectable list of matching blueprints first.
- Selecting a blueprint from the list opens its materials and mission details.
- Result lists over 25 blueprints include page buttons.

Autocomplete:

- `name` supports blueprint/item name suggestions.
- `category`, `material`, `mission_type`, `contractor`, and `location` support dropdown suggestions from current crafting data.

Options:

| Option | Required | Purpose |
| --- | --- | --- |
| `name` | No | Blueprint or crafted item name to search for. |
| `category` | No | Blueprint category, such as Quantum Drive, Power Plant, Heavy Armor, Flight Suits, Helmets, or Weapons. |
| `material` | No | Required material/resource used by the blueprint. |
| `mission_type` | No | Mission type that can award the blueprint. |
| `contractor` | No | Mission contractor that can award the blueprint. |
| `location` | No | Mission location or system. |

At least one option is required.

Current output:

- Blueprint category
- Craft time and tiers
- Required materials and quantities
- Missions that can award the blueprint
- Blueprint missions in this order: contractor, required rep, mission type, mission name, drop rate

Examples:

```text
/blueprint name:Aril Arms
/blueprint material:Iron category:Vehiclegear / Salvage
/blueprint mission_type:Salvage contractor:Adagio Holdings
/blueprint location:Stanton material:Tungsten
```

## `/trade routing`

Finds Star Citizen circular trade route candidates using UEX data.

Response visibility: private to the user.

Options:

| Option | Required | Purpose |
| --- | --- | --- |
| `starting_point` | Yes | Starting trade terminal for the circular route. Autocomplete is available, and users can still type a terminal manually. |
| `ship` | No | Ship name for route planning. Defaults to `Ironclad Assault`. |
| `investment` | No | aUEC investment for route planning. Defaults to `1,000,000`. |
| `max_stops` | No | Maximum route stops, from 2 to 5. Defaults to `5`. |
| `stay_system` | No | Keeps the full circular route inside one star system. |

Examples:

```text
/trade routing starting_point:ARC-L3
/trade routing starting_point:ARC-L3 ship:Ironclad Assault investment:1000000 max_stops:5
/trade routing starting_point:Area 18 ship:Caterpillar investment:2000000 stay_system:Stanton
```

Route behavior:

- Uses UEX average terminal prices, stock, and demand.
- Uses the selected ship's cargo capacity from the ship lookup data.
- Limits purchasable SCU by cargo capacity, investment, purchase stock, and sell demand.
- Builds a closed loop where each sell location is the next buy location.
- The final sell location returns to the starting buy location.
- Optimizes for maximum estimated profit across the whole loop, not just one leg.
- Shows the highest estimated profit circular route found from the selected starting point.
- `stay_system` can make a closed loop impossible when UEX does not have a profitable loop inside that system.
- Does not require a SC Trade Tools API token.

## `/exec`

Shows the current Executive Hangar clock.

Response visibility: public.

If `EXEC_STATUS_CHANNEL_ID` is set in `.env`, the bot also posts or updates a public Executive Hangar status message in that channel every 60 seconds.

Options: none.

Current output:

- Current Executive Hangar status
- Current phase
- Light state
- Relative countdown to the next phase change
- Exact local time of the next phase change
- If manually corrected, the embed shows both the website source timer and the corrected active timer
- If manually corrected, the embed shows which user made the correction

Data source:

- Sync timestamp is fetched from `https://contestedzonetimers.com/lib/cfg.dat`.
- The bot calculates status locally from the community timer model used by `contestedzonetimers.com`.
- This is a community timer, not official CIG server telemetry.

## `/execset`

Manually corrects the Executive Hangar clock when the timer is wrong.

Response visibility: private to the user.

Permissions:

- If `EXEC_ADMIN_ROLE_IDS` is set in `.env`, users must have one of those roles.
- If no role IDs are configured yet, users must have Discord's Manage Server permission.

Options:

| Option | Required | Purpose |
| --- | --- | --- |
| `phase` | Yes | Current phase: Closed, Open, or Resetting. |
| `remaining_minutes` | Yes | Minutes remaining in the selected phase. |

When used, the bot stores a manual override and updates the public Executive Hangar status message.
While active, `/exec` and the public status message show both the community source timer and the corrected timer.

Examples:

```text
/execset phase:Open remaining_minutes:42
/execset phase:Closed remaining_minutes:110
```

## `/execclear`

Clears the manual Executive Hangar timer override and returns to the community timer source.

Response visibility: private to the user.

Permissions:

- Same permission rules as `/execset`.

Options: none.

## `/cztimer`

Starts a local contested-zone countdown helper.

Response visibility: private to the user.

If `CZ_TIMERS_CHANNEL_ID` is set in `.env`, the bot also posts or updates a public Contested Zone timer dashboard with clickable buttons.

Options:

| Option | Required | Purpose |
| --- | --- | --- |
| `timer` | Yes | Timer type to track. |
| `started_minutes_ago` | No | Minutes already elapsed when starting the helper. |

Timer choices:

- Blue keycard terminal - 15 min
- Compboard/tablet - 30 min
- Red supervisor keycard - 30 min
- Ruin timer door cycle - 20 min

Public dashboard buttons:

- Start Blue Keycards
- Reset Blue Keycards
- Start Compboards
- Reset Compboards
- Start Red Keycards
- Reset Red Keycards
- Start Timer Doors
- Reset Timer Doors
- Reset All

Examples:

```text
/exec
/cztimer timer:Blue keycard terminal - 15 min
/cztimer timer:Compboard/tablet - 30 min started_minutes_ago:5
```
