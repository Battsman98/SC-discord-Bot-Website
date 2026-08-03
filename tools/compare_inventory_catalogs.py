from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.update_game_data_from_p4k import parse_localization, root_of  # noqa: E402
from src.web import (  # noqa: E402
    _inventory_match_confidence,
    _inventory_scanner_accepted_matches,
    _inventory_scanner_catalog_supplements,
    _inventory_scanner_text_candidates,
    _inventory_title_boxes,
    _inventory_title_candidate_is_plausible,
    _normalize_text,
    _read_calibrated_inventory_title,
    _warm_rapid_title_ocr,
)

DEFAULT_EXTRACTED = (
    Path.home()
    / "AppData"
    / "Local"
    / "StarCitizenCompanion"
    / "inventory-comparison-dataforge"
)


def p4k_items(extracted: Path) -> list[dict[str, object]]:
    loc = parse_localization(extracted / "Localization" / "english" / "global.ini")
    records = extracted / "libs" / "foundry" / "records" / "entities" / "scitem"
    items: list[dict[str, object]] = []
    for path in records.rglob("*.xml"):
        root = root_of(path)
        if root is None:
            continue
        localization = next(
            (
                node
                for node in root.iter()
                if node.tag == "Localization" and node.get("Name")
            ),
            None,
        )
        if localization is None:
            continue
        raw_name = str(localization.get("Name") or "").strip()
        if raw_name.startswith("@"):
            name = loc.get(raw_name[1:].casefold())
        else:
            name = raw_name
        name = " ".join(str(name or "").split()).strip()
        if not name or name.startswith("@") or name.casefold().startswith("loc_"):
            continue
        attach = next((node for node in root.iter() if node.tag == "AttachDef"), None)
        items.append(
            {
                "name": name,
                "normalized_name": _normalize_text(name),
                "class_name": path.stem,
                "type": attach.get("Type") if attach is not None else None,
                "subtype": attach.get("SubType") if attach is not None else None,
                "size": attach.get("Size") if attach is not None else None,
            }
        )
    return items


def wiki_items(database: Path) -> list[dict[str, object]]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(
            "SELECT item_name AS name, normalized_name, class_name, category, item_type, item_size AS size FROM item_catalog"
        )]
    finally:
        connection.close()


def catalog(items: list[dict[str, object]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for item in items:
        name = str(item["name"])
        class_name = str(item.get("class_name") or "").strip()
        result[name].add(name)
        if class_name and len(result[name]) < 8:
            result[name].update((class_name, f"item_Name{class_name}"))
    return result


def name_index(entries: dict[str, set[str]]) -> tuple[dict[str, set[str]], dict[str, str]]:
    normalized = {
        f"{name}\0{alias}": _normalize_text(alias)
        for name, aliases in entries.items()
        for alias in aliases
    }
    trigrams: dict[str, set[str]] = defaultdict(set)
    for key, value in normalized.items():
        name = key.split("\0", 1)[0]
        compact = f"  {value}  "
        for index in range(max(1, len(compact) - 2)):
            trigrams[compact[index:index + 3]].add(name)
    return trigrams, normalized


def lookup(text: str, entries: dict[str, set[str]], trigrams: dict[str, set[str]], normalized: dict[str, str]):
    for result in _inventory_scanner_catalog_supplements(text):
        if result.name in entries and max(
            _inventory_match_confidence(text, alias)
            for alias in (result.name, *result.catalog_aliases)
        ) >= 0.88:
            return result.name
    value = _normalize_text(text)
    compact = f"  {value}  "
    overlap: Counter[str] = Counter()
    for index in range(max(1, len(compact) - 2)):
        overlap.update(trigrams.get(compact[index:index + 3], ()))
    candidates = [name for name, _ in overlap.most_common(100)]
    ranked = sorted(
        candidates or list(entries)[:100],
        key=lambda name: max(_inventory_match_confidence(text, alias) for alias in entries[name]),
        reverse=True,
    )[:5]
    scored = [
        (
            SimpleNamespace(name=name),
            max(_inventory_match_confidence(text, alias) for alias in entries[name]),
        )
        for name in ranked
    ]
    accepted = _inventory_scanner_accepted_matches(scored, 0.88, text)
    return accepted[0][0].name if accepted else None


def video_comparison(fixtures: list[dict], wiki: dict[str, set[str]], p4k: dict[str, set[str]]) -> dict:
    indexes = {
        "wiki": name_index(wiki),
        "p4k": name_index(p4k),
    }
    counts = {"wiki": Counter(), "p4k": Counter()}
    failures = {"wiki": [], "p4k": []}
    latency = {"wiki": [], "p4k": []}
    _warm_rapid_title_ocr()
    for fixture in fixtures:
        capture = cv2.VideoCapture(str(ROOT / "output" / "scanner-fixtures" / f"{fixture['name']}.mp4"))
        try:
            for sample in fixture["samples"]:
                second = int(sample["second"])
                capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
                ok, frame = capture.read()
                encoded, data = cv2.imencode(".png", frame) if ok else (False, None)
                if not encoded:
                    for source in failures:
                        failures[source].append(f"{fixture['name']} {second}s frame unavailable")
                    continue
                text = ""
                for box in _inventory_title_boxes(None):
                    candidate = _read_calibrated_inventory_title(data.tobytes(), box)
                    if _inventory_title_candidate_is_plausible(candidate):
                        text = candidate
                        break
                candidates = _inventory_scanner_text_candidates(text) or [text]
                expected = str(sample["expected"])
                for source, entries in (("wiki", wiki), ("p4k", p4k)):
                    started = time.perf_counter()
                    matches = [
                        lookup(candidate, entries, *indexes[source])
                        for candidate in candidates[:1]
                    ]
                    latency[source].append((time.perf_counter() - started) * 1000)
                    match = next((value for value in matches if value), None)
                    if match == expected:
                        counts[source][expected] += 1
                    else:
                        failures[source].append(
                            f"{fixture['name']} {second}s expected={expected!r} OCR={text!r} got={match!r}"
                        )
        finally:
            capture.release()
    return {
        source: {
            "matched_samples": sum(counts[source].values()),
            "failures": failures[source],
            "lookup_ms_average": round(sum(latency[source]) / max(1, len(latency[source])), 3),
            "lookup_ms_max": round(max(latency[source], default=0), 3),
        }
        for source in ("wiki", "p4k")
    }


def main() -> int:
    extracted = DEFAULT_EXTRACTED
    wiki = wiki_items(ROOT / "data" / "bot.sqlite3")
    p4k = p4k_items(extracted)
    wiki_catalog = catalog(wiki)
    p4k_catalog = catalog(p4k)
    wiki_names = set(wiki_catalog)
    p4k_names = set(p4k_catalog)
    fixtures = json.loads(
        (ROOT / "tests" / "fixtures" / "inventory_scanner_videos.json").read_text(encoding="utf-8")
    )
    report = {
        "wiki": {"rows": len(wiki), "unique_names": len(wiki_names)},
        "p4k": {"rows": len(p4k), "unique_names": len(p4k_names)},
        "overlap": len(wiki_names & p4k_names),
        "wiki_only": sorted(wiki_names - p4k_names),
        "p4k_only": sorted(p4k_names - wiki_names),
        "videos": video_comparison(fixtures, wiki_catalog, p4k_catalog),
    }
    output = ROOT / "output" / "inventory-catalog-comparison.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "wiki": report["wiki"],
        "p4k": report["p4k"],
        "overlap": report["overlap"],
        "wiki_only": len(report["wiki_only"]),
        "p4k_only": len(report["p4k_only"]),
        "videos": report["videos"],
        "report": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
