import aiohttp

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import GameInfoSource, LookupResult
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

    async def close(self) -> None:
        for source in self._sources:
            await source.close()
        await self._session.close()


async def build_default_registry(settings: Settings, cache: SQLiteCache) -> SourceRegistry:
    timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)
    session = aiohttp.ClientSession(timeout=timeout)
    sources: list[GameInfoSource] = [
        StarCitizenWikiSource(settings, cache, session),
    ]
    return SourceRegistry(sources, session)
