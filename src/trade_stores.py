from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlparse


MAX_STORE_SHEET_BYTES = 2 * 1024 * 1024
MAX_STORE_ITEMS = 500


@dataclass(frozen=True)
class StoreInventoryItem:
    name: str
    price: str | None
    quantity: str | None
    quality: str | None
    notes: str | None


@dataclass(frozen=True)
class ParsedStoreInventory:
    items: list[StoreInventoryItem]
    content_hash: str


def google_sheet_csv_url(value: str) -> str:
    """Convert a viewable Google Sheets URL into its CSV export URL."""
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme != "https" or parsed.hostname not in {"docs.google.com", "drive.google.com"}:
        raise ValueError("Use an https://docs.google.com Google Sheets sharing link.")
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", parsed.path)
    if not match:
        raise ValueError("That link is not a standard Google Sheets sharing link.")
    sheet_id = match.group(1)
    query = parse_qs(parsed.query)
    fragment = parse_qs(parsed.fragment)
    gid = (query.get("gid") or fragment.get("gid") or ["0"])[0]
    if not str(gid).isdigit():
        gid = "0"
    return f"https://docs.google.com/spreadsheets/d/{quote(sheet_id)}/export?format=csv&gid={gid}"


def parse_store_inventory_csv(data: bytes) -> ParsedStoreInventory:
    if not data:
        raise ValueError("The Google Sheet is empty.")
    if len(data) > MAX_STORE_SHEET_BYTES:
        raise ValueError("The Google Sheet is larger than the 2 MB store limit.")
    text = data.decode("utf-8-sig", errors="replace")
    if "<html" in text[:500].casefold():
        raise ValueError("Google returned a sign-in page. Share the sheet as view-only to anyone with the link.")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("The sheet needs a header row.")
    headers = {_normalize_header(name): name for name in reader.fieldnames if name}
    name_header = _find_header(headers, "item name", "item", "name", "product")
    if name_header is None:
        raise ValueError("The sheet needs an Item Name column.")
    price_header = _find_header(headers, "price auec", "price", "auec", "unit price")
    quantity_header = _find_header(headers, "quantity", "qty", "stock")
    quality_header = _find_header(headers, "quality", "grade")
    notes_header = _find_header(headers, "notes", "details", "description")
    items: list[StoreInventoryItem] = []
    for row in reader:
        name = _clean_cell(row.get(name_header))
        if not name:
            continue
        items.append(
            StoreInventoryItem(
                name=name[:150],
                price=_clean_cell(row.get(price_header)) if price_header else None,
                quantity=_clean_cell(row.get(quantity_header)) if quantity_header else None,
                quality=_clean_cell(row.get(quality_header)) if quality_header else None,
                notes=_clean_cell(row.get(notes_header)) if notes_header else None,
            )
        )
        if len(items) > MAX_STORE_ITEMS:
            raise ValueError(f"The sheet contains more than {MAX_STORE_ITEMS} inventory rows.")
    if not items:
        raise ValueError("No inventory rows with an item name were found.")
    digest = hashlib.sha256(data).hexdigest()
    return ParsedStoreInventory(items=items, content_hash=digest)


def _normalize_header(value: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())


def _find_header(headers: dict[str, str], *candidates: str) -> str | None:
    for candidate in candidates:
        normalized = _normalize_header(candidate)
        if normalized in headers:
            return headers[normalized]
    return None


def _clean_cell(value: object) -> str | None:
    cleaned = " ".join(str(value or "").strip().split())
    return cleaned[:500] if cleaned else None
