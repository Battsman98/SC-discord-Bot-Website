"""Manually rebuild the mission/blueprint snapshot from an installed Data.p4k.

This command never downloads game data. It reads the user's installed Star
Citizen archive, extracts the localization and DataForge database with the
bundled community tools, and writes data/blueprints_snapshot.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAME = Path(r"C:\StarCitizen\LIVE")
DEFAULT_TOOLS = PROJECT_ROOT / "tools" / "sc-game-data"
DEFAULT_CACHE = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "StarCitizenCompanion" / "dataforge"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "blueprints_snapshot.json"
ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def run(command: list[str], cwd: Path, timeout: int) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Command failed: {command[0]}")
    if result.stdout.strip():
        print(result.stdout.strip().splitlines()[-1])


def extract_game_data(game_dir: Path, tools_dir: Path, cache_dir: Path, force: bool) -> tuple[Path, Path]:
    p4k = game_dir / "Data.p4k"
    unp4k = tools_dir / "unp4k.exe"
    unforge = tools_dir / "unforge.exe"
    for path in (p4k, unp4k, unforge):
        if not path.exists():
            raise FileNotFoundError(path)

    stamp = cache_dir / ".p4k_size"
    records = cache_dir / "libs" / "foundry" / "records"
    english_ini = cache_dir / "Localization" / "english" / "global.ini"
    fresh = (
        not force
        and stamp.exists()
        and records.exists()
        and english_ini.exists()
        and stamp.read_text(encoding="utf-8").strip() == str(p4k.stat().st_size)
    )
    if fresh:
        print("Using the existing local extraction cache.")
        return records, english_ini

    staging = cache_dir.with_name(f"{cache_dir.name}-staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    print("Extracting localization from Data.p4k...")
    run([str(unp4k), str(p4k), "global.ini"], staging, 600)
    print("Extracting DataForge from Data.p4k...")
    run([str(unp4k), str(p4k), ".dcb"], staging, 600)
    dcb_files = list((staging / "Data").glob("Game*.dcb"))
    if not dcb_files:
        raise FileNotFoundError("Data.p4k did not contain Data/Game*.dcb")
    print("Converting DataForge records...")
    run([str(unforge), str(dcb_files[0])], staging, 1800)

    staged_records = staging / "Data" / "libs" / "foundry" / "records"
    staged_localization = staging / "Data" / "Localization"
    if not staged_records.exists():
        raise FileNotFoundError("The DataForge converter did not produce records.")
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True)
    shutil.move(str(staging / "Data" / "libs"), str(cache_dir / "libs"))
    shutil.move(str(staged_localization), str(cache_dir / "Localization"))
    stamp.write_text(str(p4k.stat().st_size), encoding="utf-8")
    shutil.rmtree(staging)
    return cache_dir / "libs" / "foundry" / "records", cache_dir / "Localization" / "english" / "global.ini"


def parse_localization(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith(";"):
            continue
        key, value = line.split("=", 1)
        if key.endswith(",P"):
            key = key[:-2]
        values[key.strip().lower()] = value.strip()
    return values


def localized(value: str | None, loc: dict[str, str]) -> str | None:
    if not value:
        return None
    if value.startswith("@"):
        key = value[1:].lower()
        resolved = loc.get(key)
        if resolved:
            return re.sub(r"<[^>]+>", "", resolved).replace("\\n", " ").strip()
        if key in {"loc_placeholder", "loc_uninitialized", "loc_empty"}:
            return None
        return value[1:]
    return value.strip()


def xml_files(path: Path) -> Iterable[Path]:
    return path.rglob("*.xml") if path.exists() else ()


def root_of(path: Path) -> ET.Element | None:
    try:
        return ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None


def first_localized(root: ET.Element, loc: dict[str, str], *attributes: str) -> str | None:
    for elem in root.iter():
        for attribute in attributes:
            result = localized(elem.get(attribute), loc)
            if result:
                return result
    return None


def build_reference_names(records: Path, loc: dict[str, str]) -> dict[str, str]:
    names: dict[str, str] = {}
    paths = (
        records / "entities" / "scitem",
        records / "missiontype",
        records / "reputation" / "standings",
    )
    for base in paths:
        for path in xml_files(base):
            root = root_of(path)
            if root is None:
                continue
            ref = root.get("__ref")
            if not ref:
                continue
            name = first_localized(
                root,
                loc,
                "Name",
                "displayName",
                "name",
                "LocalisedTypeName",
                "IconName",
            )
            if not name and root.get("__type") == "MissionType":
                name = root.tag.split(".", 1)[-1].replace("_", " ")
            if name:
                names[ref] = name
    return names


def resolve_material_names(records: Path, wanted: set[str], loc: dict[str, str], names: dict[str, str]) -> dict[str, str]:
    resolved = {ref: names[ref] for ref in wanted if ref in names}
    unresolved = wanted - resolved.keys()
    if not unresolved:
        return resolved
    for path in xml_files(records / "entities" / "scitem"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        matches = [ref for ref in unresolved if ref in text]
        if not matches:
            continue
        root = root_of(path)
        if root is None:
            continue
        name = first_localized(root, loc, "Name", "displayName")
        if not name:
            stem = path.stem.lower()
            match = re.search(r"(?:commodity|harvestable)_(?:metal|mineral|ore|gas)(?:_\dh)?_(.+?)(?:_[a-d])?$", stem)
            name = match.group(1).replace("_", " ").title() if match else None
        if name:
            for ref in matches:
                resolved[ref] = name
                unresolved.discard(ref)
        if not unresolved:
            break
    return resolved


def number(value: str | None) -> int | float | None:
    if value is None:
        return None
    try:
        result = float(value)
        return int(result) if result.is_integer() else result
    except ValueError:
        return None


def version_label(game_dir: Path) -> str:
    manifest = game_dir / "build_manifest.id"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))["Data"]
        branch = str(data.get("Branch") or "LIVE").upper()
        change = str(data.get("RequestedP4ChangeNum") or data.get("BuildId") or "")
        return f"{branch}-{change}".strip("-")
    except (OSError, ValueError, KeyError, TypeError):
        return f"LOCAL-{int((game_dir / 'Data.p4k').stat().st_mtime)}"


def parse_blueprints(records: Path, loc: dict[str, str], version: str) -> tuple[list[dict], dict[str, dict]]:
    bp_dir = records / "crafting" / "blueprints" / "crafting"
    names = build_reference_names(records, loc)
    parsed: list[tuple[Path, ET.Element, str | None, set[str]]] = []
    material_refs: set[str] = set()
    for path in xml_files(bp_dir):
        root = root_of(path)
        if root is None:
            continue
        entity_ref = next(
            (elem.get("entityClass") for elem in root.iter() if elem.tag == "CraftingProcess_Creation"),
            None,
        )
        refs = {
            elem.get("resource") or elem.get("entityClass")
            for elem in root.iter()
            if elem.tag in {"CraftingCost_Resource", "CraftingCost_Item"}
        }
        refs.discard(None)
        refs.discard(ZERO_UUID)
        material_refs.update(refs)
        parsed.append((path, root, entity_ref, refs))

    materials = resolve_material_names(records, material_refs, loc, names)
    items: list[dict] = []
    by_record: dict[str, dict] = {}
    for index, (path, root, entity_ref, _) in enumerate(parsed, 1):
        blueprint_ref = root.get("__ref")
        name = names.get(entity_ref or "") or localized(
            next((elem.get("blueprintName") for elem in root.iter() if elem.get("blueprintName")), None),
            loc,
        )
        if not name:
            name = re.sub(r"^bp_craft_", "", path.stem, flags=re.I).replace("_", " ").title()
        relative = path.relative_to(bp_dir)
        category = " / ".join(part.replace("_", " ").title() for part in relative.parts[:-1])
        time_elem = next((elem for elem in root.iter() if elem.tag == "TimeValue_Partitioned"), None)
        craft_time = None
        if time_elem is not None:
            craft_time = (
                int(time_elem.get("days", "0")) * 86400
                + int(time_elem.get("hours", "0")) * 3600
                + int(time_elem.get("minutes", "0")) * 60
                + int(time_elem.get("seconds", "0"))
            )
        ingredients = []
        for elem in root.iter():
            if elem.tag not in {"CraftingCost_Resource", "CraftingCost_Item"}:
                continue
            ref = elem.get("resource") or elem.get("entityClass")
            quantity_elem = next((child for child in elem.iter() if child.get("standardCargoUnits") is not None), None)
            ingredients.append({
                "slot": None,
                "name": materials.get(ref or "", names.get(ref or "", "Unknown material")),
                "quantity_scu": number(quantity_elem.get("standardCargoUnits")) if quantity_elem is not None else None,
                "options": [{"unit": "scu"}],
            })
        tiers = sum(1 for elem in root.iter() if elem.tag == "CraftingBlueprintTier") or 1
        item = {
            "id": index,
            "blueprint_id": path.stem,
            "name": name,
            "loc_key": None,
            "category": category,
            "craft_time_seconds": craft_time,
            "tiers": tiers,
            "default_owned": 0,
            "item_stats": None,
            "version": version,
            "ingredients": ingredients,
            "missions": [],
        }
        items.append(item)
        if blueprint_ref:
            by_record[blueprint_ref] = item
    return items, by_record


def standing_lookup(records: Path, loc: dict[str, str]) -> dict[str, tuple[str | None, int | float | None]]:
    result = {}
    for path in xml_files(records / "reputation" / "standings"):
        root = root_of(path)
        if root is None or not root.get("__ref"):
            continue
        result[root.get("__ref")] = (
            localized(root.get("displayName"), loc) or root.get("name"),
            number(root.get("minReputation")),
        )
    return result


def pool_lookup(records: Path) -> dict[str, list[str]]:
    pools = {}
    for path in xml_files(records / "crafting" / "blueprintrewards"):
        root = root_of(path)
        if root is None or not root.get("__ref"):
            continue
        pools[root.get("__ref")] = [
            elem.get("blueprintRecord")
            for elem in root.iter("BlueprintReward")
            if elem.get("blueprintRecord")
        ]
    return pools


def parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def ancestor(elem: ET.Element, parents: dict[ET.Element, ET.Element], tags: set[str]) -> ET.Element | None:
    current = elem
    while current in parents:
        current = parents[current]
        if current.tag in tags:
            return current
    return None


def contract_text(contract: ET.Element, param: str, loc: dict[str, str]) -> str | None:
    for elem in contract.iter("ContractStringParam"):
        if elem.get("param", "").lower() == param.lower():
            value = localized(elem.get("value"), loc)
            if value:
                return value
    return None


def infer_region(elem: ET.Element, path: Path) -> str | None:
    text = " ".join([str(path), *(value for node in elem.iter() for value in node.attrib.values())]).lower()
    regions = [name for name in ("Stanton", "Pyro", "Nyx") if name.lower() in text]
    return ", ".join(regions) or None


def attach_mission(item: dict, mission: dict) -> None:
    identity = (mission["mission_id"], mission["name"], mission.get("contractor"))
    if any((row["mission_id"], row["name"], row.get("contractor")) == identity for row in item["missions"]):
        return
    item["missions"].append(mission)


def parse_missions(
    records: Path,
    loc: dict[str, str],
    blueprint_records: dict[str, dict],
) -> tuple[int, list[dict]]:
    pools = pool_lookup(records)
    standings = standing_lookup(records, loc)
    mission_types = build_reference_names(records, loc)
    linked = 0
    missions: dict[tuple[str, str], dict] = {}

    for path in xml_files(records / "missionbroker" / "pu_missions"):
        root = root_of(path)
        if root is None or root.get("notForRelease") == "1":
            continue
        name = localized(root.get("title"), loc) or root.tag.split(".", 1)[-1].replace("_", " ")
        standing_elem = next(
            (elem for elem in root.iter() if elem.tag == "ContractPrerequisite_Reputation"),
            None,
        )
        standing_name, standing_rep = standings.get(
            standing_elem.get("minStanding", "") if standing_elem is not None else "",
            (None, None),
        )
        mission_id = root.get("__ref") or path.stem
        mission = {
            "mission_id": mission_id,
            "name": name,
            "contractor": localized(root.get("missionGiver"), loc),
            "mission_type": mission_types.get(root.get("type", "")),
            "locations": infer_region(root, path),
            "min_standing": {
                "name": standing_name,
                "reputation": standing_rep,
            } if standing_name or standing_rep is not None else None,
            "version": None,
            "blueprint_rewards": [],
        }
        missions[(mission_id, name)] = mission

    contract_dir = records / "contracts" / "contractgenerator"
    for path in xml_files(contract_dir):
        root = root_of(path)
        if root is None:
            continue
        parents = parent_map(root)
        default_contractor = contract_text(root, "Contractor", loc)
        contracts = [
            elem for elem in root.iter()
            if elem.tag in {"Contract", "CareerContract", "ContractLegacy"}
            and elem.get("notForRelease") != "1"
        ]
        for contract in contracts:
            name = contract_text(contract, "Title", loc) or contract.get("debugName") or "Unknown mission"
            contractor = contract_text(contract, "Contractor", loc) or default_contractor
            standing_name, standing_rep = standings.get(contract.get("minStanding", ""), (None, None))
            param_overrides = next((elem for elem in contract.iter("paramOverrides")), None)
            mission_type_ref = param_overrides.get("missionTypeOverride") if param_overrides is not None else None
            mission_id = contract.get("id") or contract.get("__ref") or name
            mission = {
                "mission_id": mission_id,
                "name": name,
                "contractor": contractor,
                "mission_type": mission_types.get(mission_type_ref or ""),
                "locations": infer_region(contract, path),
                "min_standing": {
                    "name": standing_name,
                    "reputation": standing_rep,
                } if standing_name or standing_rep is not None else None,
                "version": None,
                "blueprint_rewards": [],
            }
            for reward in contract.iter("BlueprintRewards"):
                chance = reward.get("chance")
                for blueprint_ref in pools.get(reward.get("blueprintPool", ""), []):
                    item = blueprint_records.get(blueprint_ref)
                    if item is None:
                        continue
                    linked_mission = {
                        key: value for key, value in mission.items()
                        if key not in {"version", "blueprint_rewards"}
                    }
                    linked_mission["drop_chance"] = chance
                    attach_mission(item, linked_mission)
                    mission["blueprint_rewards"].append({
                        "name": item["name"],
                        "drop_chance": number(chance),
                    })
                    linked += 1
            missions[(mission_id, name)] = mission
    return linked, list(missions.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    parser.add_argument("--tools-dir", type=Path, default=DEFAULT_TOOLS)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--use-extracted", type=Path, help="Use an existing unforge records directory.")
    parser.add_argument("--localization", type=Path, help="global.ini to use with --use-extracted.")
    args = parser.parse_args()

    if args.use_extracted:
        records = args.use_extracted
        localization = args.localization
        if localization is None:
            raise ValueError("--localization is required with --use-extracted")
    else:
        records, localization = extract_game_data(args.game_dir, args.tools_dir, args.cache_dir, args.force_extract)

    print("Reading game localization...")
    loc = parse_localization(localization)
    version = version_label(args.game_dir)
    print("Building blueprint recipes...")
    items, blueprint_records = parse_blueprints(records, loc, version)
    print("Linking blueprint rewards to missions...")
    links, missions = parse_missions(records, loc, blueprint_records)
    for mission in missions:
        mission["version"] = version
    payload = {
        "source": {
            "kind": "local_data_p4k",
            "path": str(args.game_dir / "Data.p4k"),
            "version": version,
            "manual_update": True,
        },
        "versions": [{"id": 1, "version": version, "channel": args.game_dir.name.lower(), "active": 1}],
        "missions": sorted(missions, key=lambda row: row["name"].lower()),
        "items": sorted(items, key=lambda row: row["name"].lower()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(args.output)
    print(
        f"Wrote {len(items):,} blueprints, {len(missions):,} missions, "
        f"and {links:,} mission reward links to {args.output}"
    )


if __name__ == "__main__":
    main()
