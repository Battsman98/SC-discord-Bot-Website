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


class GameInfoSource(Protocol):
    name: str

    async def lookup(self, query: str) -> LookupResult | None:
        ...

    async def lookup_ship(self, query: str) -> ShipResult | None:
        ...

    async def close(self) -> None:
        ...
