from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LookupResult:
    title: str
    summary: str
    url: str
    source_name: str


@dataclass(frozen=True)
class ShipPurchase:
    price: int | float
    terminal_name: str
    location: str | None
    uex_link: str | None


@dataclass(frozen=True)
class ShipPledge:
    price: int | float | None
    currency: str
    is_on_sale: bool | None
    pledge_url: str | None
    warbond_price: int | float | None = None
    package_price: int | float | None = None


@dataclass(frozen=True)
class ShipResult:
    name: str
    manufacturer: str | None
    career: str | None
    role: str | None
    vehicle_type: str | None
    size: str | None
    status: str | None
    cargo_capacity: int | float | None
    crew: int | str | None
    length: int | float | None
    beam: int | float | None
    height: int | float | None
    description: str | None
    pledge: ShipPledge | None
    purchases: list[ShipPurchase]
    source_url: str
    source_name: str


@dataclass(frozen=True)
class CommodityMarket:
    terminal_name: str
    system: str | None
    planet: str | None
    location: str | None
    price: int | float
    demand: int | float | None
    game_version: str | None


@dataclass(frozen=True)
class CommodityResult:
    name: str
    code: str | None
    kind: str | None
    average_buy_price: int | float | None
    average_sell_price: int | float | None
    is_illegal: bool
    is_mineral: bool
    is_raw: bool
    is_refined: bool
    is_harvestable: bool
    wiki_url: str | None
    buy_from: list[CommodityMarket]
    sell_to: list[CommodityMarket]
    source_name: str


@dataclass(frozen=True)
class BlueprintIngredient:
    name: str
    quantity: int | float | None
    unit: str | None
    slot: str | None


@dataclass(frozen=True)
class BlueprintMission:
    name: str
    contractor: str | None
    mission_type: str | None
    locations: str | None
    min_standing_name: str | None
    min_standing_reputation: int | float | None
    drop_chance: int | float | None


@dataclass(frozen=True)
class BlueprintResult:
    name: str
    category: str | None
    craft_time_seconds: int | None
    tiers: int | None
    version: str | None
    ingredients: list[BlueprintIngredient]
    missions: list[BlueprintMission]
    source_name: str
    source_url: str
    component_size: str | None = None


@dataclass(frozen=True)
class TradeRouteLeg:
    commodity_name: str
    buy_price: int | float
    sell_price: int | float
    quantity_scu: int | float
    investment_used: int | float
    profit: int | float
    buy_system: str | None
    buy_planet: str | None
    buy_location: str | None
    buy_terminal: str
    sell_system: str | None
    sell_planet: str | None
    sell_location: str | None
    sell_terminal: str


@dataclass(frozen=True)
class TradeRouteResult:
    ship: str
    cargo_capacity_scu: int | float
    investment: int | float
    legs: list[TradeRouteLeg]
    source_name: str
    requires_empty_return_to_start: bool = False


class GameInfoSource(Protocol):
    name: str

    async def lookup(self, query: str) -> LookupResult | None:
        ...

    async def lookup_ship(self, query: str) -> ShipResult | None:
        ...

    async def autocomplete_ships(self, query: str, limit: int = 25) -> list[str]:
        ...

    async def lookup_commodity(
        self,
        query: str,
        system: str | None = None,
        purchase_system: str | None = None,
        sell_system: str | None = None,
    ) -> CommodityResult | None:
        ...

    async def autocomplete_commodities(self, query: str, limit: int = 25) -> list[str]:
        ...

    async def lookup_blueprints(
        self,
        query: str | None = None,
        category: str | None = None,
        material: str | None = None,
        mission_type: str | None = None,
        contractor: str | None = None,
        location: str | None = None,
        limit: int = 3,
        page: int = 1,
    ) -> list[BlueprintResult]:
        ...

    async def autocomplete_blueprints(self, query: str, limit: int = 25) -> list[str]:
        ...

    async def autocomplete_blueprint_filter(self, filter_name: str, query: str, limit: int = 25) -> list[str]:
        ...

    async def lookup_trade_routes(
        self,
        ship: str,
        cargo_capacity_scu: int | float,
        starting_point: str,
        investment: int | float,
        max_stops: int = 5,
        stay_system: str | None = None,
    ) -> TradeRouteResult | None:
        ...

    async def autocomplete_trade_locations(self, query: str, limit: int = 25) -> list[str]:
        ...

    async def close(self) -> None:
        ...
