from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from src.sources.base import ItemLocatorResult


class P4KInventoryCatalog:
    """Compact, read-only Data.p4k name and class-alias index."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.version = "Unknown"
        self._items: dict[str, ItemLocatorResult] = {}
        self._aliases: dict[str, tuple[str, ...]] = {}
        self._exact: dict[str, set[str]] = defaultdict(set)
        self._trigrams: dict[str, set[str]] = defaultdict(set)
        self._load()

    @staticmethod
    def _normalize(value: object) -> str:
        return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())

    @staticmethod
    def _grams(value: str) -> set[str]:
        compact = f"  {value}  "
        return {compact[index:index + 3] for index in range(max(1, len(compact) - 2))}

    def _load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        source = payload.get("source") or {}
        self.version = str(source.get("version") or "Unknown")
        for index, row in enumerate(payload.get("items") or [], 1):
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            aliases = tuple(str(value) for value in row.get("aliases") or [] if value)
            subtype = str(row.get("subtype") or "").strip()
            item_type = str(row.get("type") or "").strip()
            section = item_type if subtype.casefold() in {"", "undefined"} else subtype
            result = ItemLocatorResult(
                id=-1_000_000 - index,
                name=name,
                section=section or None,
                category=None,
                company_name=None,
                size=str(row.get("size") or "") or None,
                wiki_url=None,
                source_url="https://robertsspaceindustries.com/",
                source_name=f"Star Citizen Data.p4k ({self.version})",
                purchases=[],
                catalog_aliases=aliases,
            )
            self._items[name] = result
            values = (name, *aliases)
            self._aliases[name] = values
            for value in values:
                normalized = self._normalize(value)
                if not normalized:
                    continue
                self._exact[normalized].add(name)
                for gram in self._grams(normalized):
                    self._trigrams[gram].add(name)

    def lookup(self, query: str, limit: int = 10) -> list[ItemLocatorResult]:
        normalized = self._normalize(query)
        if not normalized:
            return []
        exact = self._exact.get(normalized)
        if exact:
            return [self._items[name] for name in sorted(exact)[:limit]]
        overlap: Counter[str] = Counter()
        query_grams = self._grams(normalized)
        for gram in query_grams:
            overlap.update(self._trigrams.get(gram, ()))
        ranked = sorted(
            overlap,
            key=lambda name: (
                -overlap[name],
                min(abs(len(self._normalize(alias)) - len(normalized)) for alias in self._aliases[name]),
                name.casefold(),
            ),
        )
        return [self._items[name] for name in ranked[:limit]]

    @property
    def item_count(self) -> int:
        return len(self._items)
