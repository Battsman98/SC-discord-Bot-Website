"""Download the current blueprint catalog for Render-safe fallback searches."""

import json
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "https://sc-craft.tools"
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "blueprints_snapshot.json"


def fetch(path: str) -> dict:
    request = Request(f"{BASE_URL}{path}", headers={"Accept": "application/json", "User-Agent": "SCCompanion-Snapshot/1.0"})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> None:
    first = fetch("/api/blueprints?limit=100&page=1")
    items = list(first.get("items", []))
    pages = int(first.get("pagination", {}).get("pages", 1))
    for page in range(2, pages + 1):
        items.extend(fetch(f"/api/blueprints?limit=100&page={page}").get("items", []))
    config = fetch("/api/config")
    missions = config.get("missions", {})
    for item in items:
        for mission in item.get("missions", []):
            details = missions.get(str(mission.get("mission_id")), {})
            for key in ("contractor", "mission_type", "locations", "min_standing"):
                if key in details:
                    mission[key] = details[key]
    payload = {"versions": config.get("versions", []), "items": items}
    OUTPUT.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(items)} blueprints to {OUTPUT}")


if __name__ == "__main__":
    main()
