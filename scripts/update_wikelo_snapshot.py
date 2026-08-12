"""Download the current Wikelo mission catalog from the Star Citizen Wiki API."""
import asyncio
import json
from pathlib import Path

import aiohttp


API_URL = "https://api.star-citizen.wiki/api/missions"
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "wikelo_missions_snapshot.json"


async def main() -> None:
    timeout = aiohttp.ClientTimeout(total=60)
    headers = {"User-Agent": "GameAssistBot/0.1 (Wikelo data snapshot)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        params = {"filter[mission_giver]": "Wikelo", "page[size]": "200"}
        async with session.get(API_URL, params=params) as response:
            response.raise_for_status()
            rows = (await response.json()).get("data", [])
        missions = await asyncio.gather(*(_detail(session, row) for row in rows))
    payload = {"source": API_URL, "missions": sorted(missions, key=lambda row: row["name"].casefold())}
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(missions)} Wikelo missions to {OUTPUT}")


async def _detail(session: aiohttp.ClientSession, summary: dict) -> dict:
    async with session.get(summary["link"]) as response:
        response.raise_for_status()
        row = (await response.json()).get("data", {})
    return {
        "mission_id": row.get("uuid"), "name": row.get("title"),
        "requirements": [_requirement(item) for item in row.get("hauling_orders") or []],
        "rewards": [{"name": item.get("name"), "quantity": item.get("amount") or 1, "unit": "item"}
                    for item in row.get("reward_items") or []],
        "reputation_required_name": row.get("min_standing_name") or "New Customer",
        "reputation_required": (row.get("min_standing") or {}).get("min_reputation", 0),
        "reputation_reward": _wikelo_reputation_reward(row),
        "version": row.get("game_version"),
        "released": bool(row.get("released") and not row.get("not_for_release")),
        "source_url": row.get("web_url"),
    }


def _requirement(item: dict) -> dict:
    scu = item.get("max_scu") or item.get("min_scu")
    return {"name": item.get("name"), "quantity": scu if scu is not None else (item.get("max_amount") or item.get("min_amount") or 1),
            "unit": "SCU" if scu is not None else "item"}


def _wikelo_reputation_reward(row: dict) -> int | float | None:
    rewards = [
        item.get("amount")
        for item in row.get("reputation_gained") or []
        if item.get("scope") == "Wikelo" or item.get("faction") == "Wikelo Emporium"
    ]
    values = [value for value in rewards if isinstance(value, (int, float))]
    if values:
        return sum(values)
    value = row.get("reputation_amount")
    return value if isinstance(value, (int, float)) else None


if __name__ == "__main__":
    asyncio.run(main())
