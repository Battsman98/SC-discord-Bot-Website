import json
from pathlib import Path

from src.sources.base import WikeloMissionResult, WikeloRequirement


SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "data" / "wikelo_missions_snapshot.json"


class WikeloSource:
    name = "Star Citizen Wiki"

    def __init__(self, snapshot_path: Path = SNAPSHOT_PATH) -> None:
        self._snapshot_path = snapshot_path
        self._rows: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._rows is None:
            try:
                payload = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
                self._rows = payload.get("missions", []) if isinstance(payload, dict) else []
            except (OSError, ValueError):
                self._rows = []
        return self._rows

    async def close(self) -> None:
        return None

    async def lookup_wikelo(self, query: str, limit: int = 25) -> list[WikeloMissionResult]:
        needle = " ".join(str(query or "").casefold().split())
        if not needle:
            return []
        exact_reward_matches = []
        exact_mission_matches = []
        matches = []
        for row in self._load():
            mission_name = str(row.get("name") or "")
            reward_names = [str(item.get("name") or "") for item in row.get("rewards", [])]
            reward_choices = {
                choice.casefold()
                for name in reward_names
                for choice in self._reward_choices(name)
            }
            parsed = self._parse(row)
            if needle in reward_choices:
                exact_reward_matches.append(parsed)
                continue
            if needle == mission_name.casefold():
                exact_mission_matches.append(parsed)
                continue
            haystack = " ".join([
                mission_name,
                *reward_names,
                *(str(item.get("name") or "") for item in row.get("requirements", [])),
            ]).casefold()
            if needle in haystack:
                matches.append(parsed)
        if exact_reward_matches:
            matches = exact_reward_matches
        elif exact_mission_matches:
            matches = exact_mission_matches
        matches.sort(key=lambda item: self._rank(item, needle))
        return matches[: max(1, min(limit, 25))]

    async def autocomplete_wikelo(self, query: str, limit: int = 25) -> list[str]:
        needle = " ".join(str(query or "").casefold().split())
        names: set[str] = set()
        for row in self._load():
            names.add(str(row.get("name") or ""))
            for item in row.get("rewards", []):
                names.update(self._reward_choices(str(item.get("name") or "")))
        return sorted((name for name in names if name and needle in name.casefold()), key=str.casefold)[:limit]

    @staticmethod
    def _reward_choices(name: str) -> set[str]:
        choices = {name}
        simplified = name
        for prefix in ("RSI ", "Aegis ", "Anvil ", "Argo ", "Crusader ", "Drake ", "MISC ", "Mirai ", "Origin ", "Tumbril "):
            if simplified.startswith(prefix):
                simplified = simplified[len(prefix):]
                break
        for suffix in (" Wikelo War Special", " Wikelo Special"):
            if simplified.endswith(suffix):
                simplified = simplified[:-len(suffix)]
                break
        if simplified and simplified != name:
            choices.add(simplified)
        return choices

    @staticmethod
    def _parse(row: dict) -> WikeloMissionResult:
        def items(key: str) -> list[WikeloRequirement]:
            return [WikeloRequirement(
                name=str(item.get("name") or "Unknown item"),
                quantity=item.get("quantity") or 0,
                unit=str(item.get("unit") or "item"),
            ) for item in row.get(key, []) if isinstance(item, dict)]
        return WikeloMissionResult(
            mission_id=str(row.get("mission_id") or ""), name=str(row.get("name") or "Unknown mission"),
            rewards=items("rewards"), requirements=items("requirements"),
            reputation_required_name=str(row.get("reputation_required_name") or row.get("reputation") or "New Customer"),
            reputation_required=row.get("reputation_required") or 0,
            reputation_reward=row.get("reputation_reward"), version=row.get("version"),
            released=bool(row.get("released")), source_url=str(row.get("source_url") or ""),
        )

    @staticmethod
    def _rank(item: WikeloMissionResult, needle: str) -> tuple[int, str]:
        reward_names = [reward.name.casefold() for reward in item.rewards]
        mission = item.name.casefold()
        if needle in reward_names or needle == mission:
            rank = 0
        elif any(name.startswith(needle) for name in reward_names) or mission.startswith(needle):
            rank = 1
        elif any(needle in name for name in reward_names):
            rank = 2
        else:
            rank = 3
        return rank, mission
