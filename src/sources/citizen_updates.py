import asyncio
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from src.cache import SQLiteCache
from src.config import Settings


RSI_BASE = "https://robertsspaceindustries.com"
DEVELOPMENT_URL = f"{RSI_BASE}/en/development"
COMM_LINK_URL = f"{RSI_BASE}/en/comm-link"
COMM_LINK_ARCHIVE_URLS = (
    f"{COMM_LINK_URL}?series=this-week-in-sc&sort=publish_new",
    f"{COMM_LINK_URL}?series=monthly-report&sort=publish_new",
    f"{COMM_LINK_URL}?series=roadmap-roundup&sort=publish_new",
    f"{COMM_LINK_URL}?series=inside-star-citizen&sort=publish_new",
)
STATUS_URL = "https://status.robertsspaceindustries.com/"
COMMUNITY_INTEL_URL = "https://www.reddit.com/r/starcitizen/search.rss?q=leak%20OR%20datamine%20OR%20spoiler&restrict_sr=on&sort=new"
UPDATE_LOOKBACK_DAYS = 90


class CitizenUpdatesSource:
    """Direct-source Star Citizen updates, kept independent from Discord feeds."""

    def __init__(self, settings: Settings, cache: SQLiteCache) -> None:
        self._cache = cache
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=settings.http_timeout_seconds),
            headers={"User-Agent": "SCCompanion/1.0 (+https://sccompanion.org)"},
        )

    async def close(self) -> None:
        await self._session.close()

    async def get_updates(self) -> dict:
        cache_key = "citizen-updates:direct-sources:v4:dated-auto-refresh"
        cached = await self._cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

        pages = await asyncio.gather(
            self._fetch_text(DEVELOPMENT_URL),
            self._fetch_text(STATUS_URL),
            self._fetch_text(COMM_LINK_URL),
            self._fetch_text(COMMUNITY_INTEL_URL),
            *(self._fetch_text(url) for url in COMM_LINK_ARCHIVE_URLS),
            return_exceptions=True,
        )
        development, status, comm_link, community, *comm_link_archives = [
            page if isinstance(page, str) else "" for page in pages
        ]
        comm_link_history = "\n".join((comm_link, *comm_link_archives))
        payload = {
            "patch_notes": self.parse_patch_notes(development),
            "pu_updates": self.parse_status_updates(status),
            "sneak_peeks": self.parse_comm_link_updates(comm_link_history),
            "leaks": self.parse_community_intel(community),
            "lookback_days": UPDATE_LOOKBACK_DAYS,
            "sources": {
                "patch_notes": DEVELOPMENT_URL,
                "pu_updates": STATUS_URL,
                "sneak_peeks": COMM_LINK_URL,
                "leaks": COMMUNITY_INTEL_URL,
            },
        }
        if any(payload[key] for key in ("patch_notes", "pu_updates", "sneak_peeks", "leaks")):
            await self._cache.set(cache_key, payload, 5 * 60)
        return payload

    async def _fetch_text(self, url: str) -> str:
        try:
            async with self._session.get(url) as response:
                if response.status != 200:
                    return ""
                return await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return ""

    @staticmethod
    def parse_patch_notes(html: str, limit: int = 24) -> list[dict]:
        soup = BeautifulSoup(html or "", "html.parser")
        rows = []
        seen = set()
        for anchor in soup.select('a[href*="/comm-link/Patch-Notes/"]'):
            url = urljoin(RSI_BASE, anchor.get("href", ""))
            if not url or url in seen:
                continue
            seen.add(url)
            text = _clean(anchor.get_text(" ", strip=True))
            title = _clean(anchor.get("title", "")) or re.sub(r"\s+Posted:?\s+.*$", "", text, flags=re.IGNORECASE).strip()
            posted = _posted_text(text)
            rows.append(_item(title, url, "RSI Patch Notes", posted, "Official", True))
            if len(rows) >= limit:
                break
        return rows

    @staticmethod
    def parse_status_updates(html: str, limit: int = 32) -> list[dict]:
        soup = BeautifulSoup(html or "", "html.parser")
        rows = []
        for issue in soup.select(".issue"):
            title = _clean(issue.select_one("h3").get_text(" ", strip=True)) if issue.select_one("h3") else ""
            if not title:
                continue
            onclick = issue.get("onclick", "")
            match = re.search(r'https?:\\?/\\?/[^\'\"]+', onclick)
            url = match.group(0).replace("\\/", "/") if match else STATUS_URL
            date = issue.select_one(".date")
            published = (date.get("data-date") or _clean(date.get_text(" ", strip=True))) if date else ""
            state = issue.select_one(".issue__header span")
            status = _clean(state.get_text(" ", strip=True)).lstrip("✔ ") if state else "Update"
            summary_node = issue.select_one(".issue__content p")
            summary = _clean(summary_node.get_text(" ", strip=True)) if summary_node else ""
            rows.append(_item(title, url, "RSI Status", published, status, True, summary))
            if len(rows) >= limit:
                break
        return rows

    @staticmethod
    def parse_comm_link_updates(html: str, limit: int = 40) -> list[dict]:
        soup = BeautifulSoup(html or "", "html.parser")
        keywords = (
            "inside star citizen", "roadmap roundup", "this week in star citizen", "monthly report",
            "sneak", "teaser", "behind the ships", "squadron 42", "citizencon", "letter from",
        )
        rows = []
        seen = set()
        for anchor in soup.select('a[href*="/comm-link/"]'):
            text = _clean(anchor.get_text(" ", strip=True))
            lowered = text.lower()
            if not any(keyword in lowered for keyword in keywords):
                continue
            url = urljoin(RSI_BASE, anchor.get("href", ""))
            if not url or url in seen:
                continue
            seen.add(url)
            title = re.sub(r"^(post|video|slideshow|poll)\s+", "", text, flags=re.IGNORECASE)
            title = re.sub(r"\s+\d+\s+Posted:.*$", "", title, flags=re.IGNORECASE).strip()
            rows.append(_item(title, url, "RSI Comm-Link", _posted_text(text), "Official preview", True))
            if len(rows) >= limit:
                break
        return rows

    @staticmethod
    def parse_community_intel(xml: str, limit: int = 25) -> list[dict]:
        try:
            root = ET.fromstring(xml or "<feed />")
        except ET.ParseError:
            return []
        rows = []
        for entry in root.findall("{*}entry"):
            title_node = entry.find("{*}title")
            link_node = entry.find("{*}link")
            if title_node is None or link_node is None:
                continue
            title = _clean("".join(title_node.itertext()))
            if not any(word in title.lower() for word in ("leak", "datamine", "spoiler", "pipeline")):
                continue
            updated = entry.find("{*}updated")
            content = entry.find("{*}content")
            content_html = "".join(content.itertext()) if content is not None else ""
            summary = _clean(BeautifulSoup(content_html, "html.parser").get_text(" ", strip=True))
            rows.append(_item(
                title,
                link_node.get("href", ""),
                "r/starcitizen original post",
                _clean("".join(updated.itertext())) if updated is not None else "",
                "Unverified",
                False,
                summary[:280],
            ))
            if len(rows) >= limit:
                break
        return rows


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


def _posted_text(value: str) -> str:
    relative = re.search(
        r"\bPosted:?\s+((?:\d+|an?|one)\s+(?:minute|hour|day|week|month|year)s?\s+ago|today|yesterday)",
        value,
        flags=re.IGNORECASE,
    )
    if relative:
        return _clean(relative.group(1))
    match = re.search(r"\bPosted:?\s+(.+?)(?:\s+[A-Z][a-z]+\s|$)", value)
    return _clean(match.group(1)) if match else ""


def _item(title: str, url: str, source: str, published: str, status: str, confirmed: bool, summary: str = "") -> dict:
    parsed_url = urlparse(str(url or ""))
    safe_url = str(url) if parsed_url.scheme in {"http", "https"} and parsed_url.netloc else ""
    return {
        "title": _clean(title),
        "url": safe_url,
        "source": source,
        "published": _clean(published),
        "status": status,
        "confirmed": confirmed,
        "summary": _clean(summary),
    }
