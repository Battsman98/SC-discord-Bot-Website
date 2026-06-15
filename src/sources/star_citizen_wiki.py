from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

from src.cache import SQLiteCache
from src.config import Settings
from src.sources.base import LookupResult


class StarCitizenWikiSource:
    name = "Star Citizen Wiki"
    base_url = "https://api.star-citizen.wiki"

    def __init__(self, settings: Settings, cache: SQLiteCache, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._cache = cache
        self._session = session

    async def lookup(self, query: str) -> LookupResult | None:
        normalized_query = " ".join(query.strip().split())
        if not normalized_query:
            return None

        cache_key = f"star-citizen-wiki:{normalized_query.lower()}"
        cached = await self._cache.get(cache_key)
        if cached:
            return LookupResult(**cached)

        search_url = f"{self.base_url}/search/{quote(normalized_query)}"
        html = await self._fetch_text(search_url)
        if not html:
            return None

        result = self._parse_result(html, normalized_query, search_url)
        if result is not None:
            await self._cache.set(cache_key, result.__dict__, self._settings.cache_ttl_seconds)
        return result

    async def _fetch_text(self, url: str) -> str | None:
        try:
            async with self._session.get(url) as response:
                response.raise_for_status()
                return await response.text()
        except aiohttp.ClientError:
            return None

    def _parse_result(self, html: str, query: str, fallback_url: str) -> LookupResult | None:
        soup = BeautifulSoup(html, "html.parser")

        title = self._meta_content(soup, "og:title")
        description = self._meta_content(soup, "description") or self._meta_content(soup, "og:description")
        canonical = self._canonical_url(soup) or fallback_url

        if not title:
            page_title = soup.title.get_text(strip=True) if soup.title else ""
            title = page_title or query

        if "No results found" in soup.get_text(" ", strip=True):
            return None

        summary = description or f"Found Star Citizen information for {query}."
        if len(summary) > 350:
            summary = f"{summary[:347].rstrip()}..."

        return LookupResult(
            title=title,
            summary=summary,
            url=canonical,
            source_name=self.name,
        )

    def _meta_content(self, soup: BeautifulSoup, name: str) -> str | None:
        tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
        if tag is None:
            return None
        content = tag.get("content")
        return str(content).strip() if content else None

    def _canonical_url(self, soup: BeautifulSoup) -> str | None:
        tag = soup.find("link", attrs={"rel": "canonical"})
        if tag is None:
            return None
        href = tag.get("href")
        return str(href).strip() if href else None

    async def close(self) -> None:
        return None
