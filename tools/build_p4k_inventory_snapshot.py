from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.update_game_data_from_p4k import parse_localization, root_of, version_label  # noqa: E402

DEFAULT_EXTRACTED = (
    Path.home() / "AppData" / "Local" / "StarCitizenCompanion" / "inventory-comparison-dataforge"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the deployable inventory catalog from Data.p4k extraction.")
    parser.add_argument("--extracted", type=Path, default=DEFAULT_EXTRACTED)
    parser.add_argument("--game-dir", type=Path, default=Path(r"C:\StarCitizen\LIVE"))
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "p4k_inventory_snapshot.json")
    args = parser.parse_args()

    localization = parse_localization(args.extracted / "Localization" / "english" / "global.ini")
    records = args.extracted / "libs" / "foundry" / "records" / "entities" / "scitem"
    grouped: dict[str, dict[str, object]] = {}
    aliases: dict[str, set[str]] = defaultdict(set)
    excluded = re.compile(r"(?:placeholder|test string|loc_(?:empty|placeholder|uninitialized))", re.I)
    for path in records.rglob("*.xml"):
        root = root_of(path)
        if root is None:
            continue
        node = next((item for item in root.iter() if item.tag == "Localization" and item.get("Name")), None)
        if node is None:
            continue
        raw_name = str(node.get("Name") or "").strip()
        name = localization.get(raw_name[1:].casefold()) if raw_name.startswith("@") else raw_name
        name = " ".join(str(name or "").replace("\\n", " ").split()).strip()
        if not name or name.startswith("@") or excluded.search(name):
            continue
        attach = next((item for item in root.iter() if item.tag == "AttachDef"), None)
        class_name = path.stem
        if name not in grouped:
            grouped[name] = {
                "name": name,
                "type": attach.get("Type") if attach is not None else None,
                "subtype": attach.get("SubType") if attach is not None else None,
                "size": attach.get("Size") if attach is not None else None,
                "aliases": [],
            }
        if len(aliases[name]) < 8:
            aliases[name].update((class_name, f"item_Name{class_name}"))

    for name, item in grouped.items():
        item["aliases"] = sorted(aliases[name])
    payload = {
        "source": {
            "kind": "local_data_p4k",
            "version": version_label(args.game_dir),
            "p4_change": json.loads((args.game_dir / "build_manifest.id").read_text(encoding="utf-8"))["Data"].get("RequestedP4ChangeNum"),
        },
        "items": sorted(grouped.values(), key=lambda item: str(item["name"]).casefold()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(payload['items']):,} unique P4K inventory names to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
