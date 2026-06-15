import aiohttp

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import GameInfoSource, LookupResult, ShipResult
from src.sources.star_citizen_wiki import StarCitizenWikiSource


class SourceRegistry:
    def __init__(self, sources: list[GameInfoSource], session: aiohttp.ClientSession) -> None:
        self._sources = sources
        self._session = session

    async def lookup(self, query: str) -> LookupResult | None:
        for source in self._sources:
            result = await source.lookup(query)
            if result is not None:
                return result
        return None

    async def lookup_ship(self, query: str) -> ShipResult | None:
        for source in self._sources:
            result = await source.lookup_ship(query)
            if result is not None:
                return result
        return None

    async def autocomplete_ships(self, query: str, limit: int = 25) -> list[str]:
        seen: set[str] = set()
        matches: list[str] = []

        for source in self._sources:
            for name in await source.autocomplete_ships(query, limit):
                if name in seen:
                    continue
                seen.add(name)
                matches.append(name)
                if len(matches) >= limit:
                    return matches

        return matches

    async def close(self) -> None:
        for source in self._sources:
            await source.close()
        await self._session.close()


async def build_default_registry(settings: Settings, cache: SQLiteCache) -> SourceRegistry:
    timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)
    session = aiohttp.ClientSession(
        timeout=timeout,
        headers={
            "User-Agent": "GameAssistBot/0.1 (Discord bot; Star Citizen lookup)",
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        },
    )
    sources: list[GameInfoSource] = [
        StarCitizenWikiSource(settings, cache, session),
    ]
    return SourceRegistry(sources, session)
