from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.web import _inventory_match_confidence, _read_inventory_title  # noqa: E402


def _best_expected_match(text: str, sample: dict[str, object]) -> float:
    names = [str(sample["expected"]), *(str(value) for value in sample.get("aliases", []))]
    return max(_inventory_match_confidence(text, name) for name in names)


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
            height = frame.shape[0]
            tooltip_region = frame[: max(1, height // 2)]
            encoded, data = cv2.imencode(
                ".webp",
                tooltip_region,
                [cv2.IMWRITE_WEBP_QUALITY, 90],
            )
            if not encoded:
                failures.append(f"{second}s: frame encoding failed")
                continue
            started = time.perf_counter()
            text, _, _ = _read_inventory_title(data.tobytes(), None)
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            score = _best_expected_match(text, sample)
            expected = str(sample["expected"])
            if elapsed_ms > 1000:
                failures.append(f"{second}s: {elapsed_ms} ms exceeds 1000 ms")
            if score < 0.72:
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
