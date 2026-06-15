from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LookupResult:
    title: str
    summary: str
    url: str
    source_name: str


class GameInfoSource(Protocol):
    name: str

    async def lookup(self, query: str) -> LookupResult | None:
        ...

    async def close(self) -> None:
        ...
