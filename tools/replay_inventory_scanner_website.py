from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import cv2
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.web import app, require_user  # noqa: E402


def _test_user() -> SimpleNamespace:
    return SimpleNamespace(id=9_999_999, username="scanner-release-gate")


def main() -> int:
    fixtures = json.loads(
        (ROOT / "tests" / "fixtures" / "inventory_scanner_videos.json").read_text(
            encoding="utf-8"
        )
    )
    failures: list[str] = []
    app.dependency_overrides[require_user] = _test_user
    try:
        with TestClient(app) as client:
            for fixture in fixtures:
                path = ROOT / "output" / "scanner-fixtures" / f"{fixture['name']}.mp4"
                capture = cv2.VideoCapture(str(path))
                actual: Counter[str] = Counter()
                if not capture.isOpened():
                    failures.append(f"{fixture['name']}: video unavailable")
                    continue
                try:
                    for sample in fixture["samples"]:
                        second = int(sample["second"])
                        capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
                        ok, frame = capture.read()
                        encoded, data = cv2.imencode(".png", frame) if ok else (False, None)
                        if not encoded:
                            failures.append(f"{fixture['name']} {second}s: frame unavailable")
                            continue
                        response = client.post(
                            "/api/me/inventory/import/images",
                            params={
                                "default_location": "Release Gate",
                                "default_category": sample.get("category", fixture["category"]),
                                "scanner_mode": "true",
                                "live_scan": "true",
                                "min_score": "0.88",
                            },
                            files={"files": ("frame.png", data.tobytes(), "image/png")},
                        )
                        if response.status_code != 200:
                            failures.append(
                                f"{fixture['name']} {second}s: HTTP {response.status_code} {response.text[:160]}"
                            )
                            continue
                        payload = response.json()
                        items = payload.get("items") or []
                        names = [str(item.get("name")) for item in items]
                        expected = str(sample["expected"])
                        request_ms = int((payload.get("performance") or {}).get("server_ms") or 0)
                        if names != [expected]:
                            failures.append(
                                f"{fixture['name']} {second}s: expected {expected!r}, got {names!r}; "
                                f"OCR={payload.get('ocr_text')!r}"
                            )
                            continue
                        if request_ms > 1000:
                            failures.append(
                                f"{fixture['name']} {second}s: website processing {request_ms} ms exceeds 1000 ms"
                            )
                        actual[expected] += 1
                        print(
                            f"{fixture['name']} {second:>3}s {request_ms:>4} ms  {expected}"
                        )
                finally:
                    capture.release()
                expected_counts = Counter(str(sample["expected"]) for sample in fixture["samples"])
                if actual != expected_counts:
                    failures.append(
                        f"{fixture['name']}: quantities expected {dict(expected_counts)}, got {dict(actual)}"
                    )
    finally:
        app.dependency_overrides.pop(require_user, None)

    if failures:
        print("\nFAILED: OCR + website release gate")
        print("\n".join(failures))
        return 1
    print("\nPASS: every saved video passed OCR + the real website scanner endpoint.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
