from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import LookupResult


class ExampleWebsiteSource:
    name = "Example Source"

    def __init__(self, settings: Settings, cache: SQLiteCache, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._cache = cache
        self._session = session

    async def lookup(self, query: str) -> LookupResult | None:
        normalized_query = query.strip()
        if not normalized_query:
            return None

        cache_key = f"example-source:{normalized_query.lower()}"
        cached = await self._cache.get(cache_key)
        if cached:
            return LookupResult(**cached)

        # Replace this with a real game wiki/API endpoint once the target sites are chosen.
        url = f"https://example.com/search?q={quote_plus(normalized_query)}"
        html = await self._fetch_text(url)
        if html is None:
            return None

        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else normalized_query

        result = LookupResult(
            title=title,
            summary=f"Found a possible match for '{normalized_query}'. Configure this source for a real website.",
            url=url,
            source_name=self.name,
        )
        await self._cache.set(cache_key, result.__dict__, self._settings.cache_ttl_seconds)
        return result

    async def _fetch_text(self, url: str) -> str | None:
        try:
            async with self._session.get(url) as response:
                response.raise_for_status()
                return await response.text()
        except aiohttp.ClientError:
            return None

    async def close(self) -> None:
        return None
