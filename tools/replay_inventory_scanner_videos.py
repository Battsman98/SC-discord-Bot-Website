from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.web import (  # noqa: E402
    _inventory_match_confidence,
    _inventory_scanner_text_candidates,
    _inventory_title_boxes,
    _inventory_title_candidate_is_plausible,
    _read_calibrated_inventory_title,
    _warm_rapid_title_ocr,
)


def _best_expected_match(text: str, sample: dict[str, object]) -> float:
    names = [str(sample["expected"]), *(str(value) for value in sample.get("aliases", []))]
    candidates = _inventory_scanner_text_candidates(text, set()) or [text]
    return max(_inventory_match_confidence(candidate, name) for candidate in candidates for name in names)


def replay_video(video_path: Path, fixture: dict[str, object]) -> tuple[Counter[str], list[str]]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open {video_path}")
    counts: Counter[str] = Counter()
    failures: list[str] = []
    try:
        for sample in fixture["samples"]:
            second = int(sample["second"])
            capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
            ok, frame = capture.read()
            if not ok:
                failures.append(f"{second}s: frame unavailable")
                continue
            encoded, data = cv2.imencode(
                ".webp",
                frame,
                [cv2.IMWRITE_WEBP_QUALITY, 90],
            )
            if not encoded:
                failures.append(f"{second}s: frame encoding failed")
                continue
            started = time.perf_counter()
            text = ""
            score = 0.0
            for title_box in _inventory_title_boxes(None):
                candidate_text = _read_calibrated_inventory_title(data.tobytes(), title_box)
                if not _inventory_title_candidate_is_plausible(candidate_text):
                    continue
                candidate_score = _best_expected_match(candidate_text, sample)
                if candidate_score > score:
                    text, score = candidate_text, candidate_score
                if candidate_score >= 0.88:
                    break
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            expected = str(sample["expected"])
            if elapsed_ms > 1000:
                failures.append(f"{second}s: {elapsed_ms} ms exceeds 1000 ms")
            if score < 0.88:
                failures.append(
                    f"{second}s: expected {expected!r}, read {text!r}, confidence {score:.3f}"
                )
                continue
            counts[expected] += 1
            print(f"{video_path.name} {second:>2}s {elapsed_ms:>4} ms  {expected}  ({score:.3f})")
    finally:
        capture.release()
    return counts, failures


def main() -> int:
    _warm_rapid_title_ocr()
    fixture_path = ROOT / "tests" / "fixtures" / "inventory_scanner_videos.json"
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    video_dir = ROOT / "output" / "scanner-fixtures"
    all_failures: list[str] = []
    for fixture in fixtures:
        video_path = video_dir / f"{fixture['name']}.mp4"
        if not video_path.exists():
            all_failures.append(
                f"{video_path} is missing; download the Medal fixture listed in {fixture_path}"
            )
            continue
        actual, failures = replay_video(video_path, fixture)
        expected = Counter(str(sample["expected"]) for sample in fixture["samples"])
        if actual != expected:
            failures.append(f"quantity mismatch: expected {dict(expected)}, got {dict(actual)}")
        all_failures.extend(f"{fixture['name']}: {failure}" for failure in failures)
    if all_failures:
        print("\nFAILED")
        print("\n".join(all_failures))
        return 1
    print("\nPASS: 100% titles, 100% quantities, and every sample completed within one second.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
