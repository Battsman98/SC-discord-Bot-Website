from pathlib import Path


EXTENSION_DIR = Path(__file__).resolve().parents[1] / "tools" / "rsi-connector-extension"


def test_rsi_connector_reports_paginated_scan_progress() -> None:
    background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    content = (EXTENSION_DIR / "content.js").read_text(encoding="utf-8")
    manifest = (EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8")

    assert '"version": "0.4.6"' in manifest
    assert "function pledgePageCount(pageHTML)" in background
    assert "reportProgress({ page, totalPages, candidates: candidates.size })" in background
    assert 'direction: "from-game-assist-rsi-progress"' in background
    assert 'message.requestId = event.data.requestId' in content
    assert 'message?.direction !== "from-game-assist-rsi-progress"' in content
