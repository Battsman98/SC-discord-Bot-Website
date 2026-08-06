from pathlib import Path


EXTENSION_DIR = Path(__file__).resolve().parents[1] / "tools" / "rsi-connector-extension"


def test_rsi_connector_reports_paginated_scan_progress() -> None:
    background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    content = (EXTENSION_DIR / "content.js").read_text(encoding="utf-8")
    manifest = (EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8")

    assert '"version": "0.4.9"' in manifest
    assert "function pledgePageCount(pageHTML)" in background
    assert "return [...extractTypedItemShips(pageHTML)]" in background
    assert "function importDiagnostics(scannedPages, pageCount, typedCandidates)" in background
    assert 'parser_version: "typed-items-v2"' in background
    assert "markup_fingerprint: fnv1a(structure)" in background
    assert "shipLinks" not in background
    assert "containedShips" not in background
    assert "(?:Standalone Ship|Game Package|Package)" not in background
    assert "(?:ship|vehicle)" in background
    assert "Promise.all(remainingPages.map" in background
    assert "AbortSignal.timeout(20000)" in background
    assert "reportProgress({ page: completedPages, totalPages, candidates: candidates.size })" in background
    assert 'direction: "from-game-assist-rsi-progress"' in background
    assert 'message.requestId = event.data.requestId' in content
    assert 'message?.direction !== "from-game-assist-rsi-progress"' in content
