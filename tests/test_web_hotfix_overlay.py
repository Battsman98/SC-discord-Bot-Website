from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

def test_hotfix_overlay_uses_wafer_animation_and_expected_message() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_DIR / "hotfix-overlay.js").read_text(encoding="utf-8")
    assert 'href="/assets/hotfix-overlay.css?v=20260720"' in html
    assert 'src="/assets/hotfix-overlay.js?v=20260720"' in html
    assert 'src="/assets/media/wafer-transport.html"' in javascript
    assert "Potential Hot-Fix coming" in javascript
    assert (WEB_DIR / "media" / "wafer-transport.html").is_file()

def test_hotfix_overlay_handles_server_and_network_failures_for_twenty_seconds() -> None:
    javascript = (WEB_DIR / "hotfix-overlay.js").read_text(encoding="utf-8")
    assert "const DISPLAY_MS = 20_000;" in javascript
    assert "response.status >= 500" in javascript
    assert "window.fetch = async" in javascript
    assert "window.setTimeout(hidePotentialHotfix, DISPLAY_MS)" in javascript

def test_hotfix_overlay_can_be_dismissed_without_navigation() -> None:
    javascript = (WEB_DIR / "hotfix-overlay.js").read_text(encoding="utf-8")
    assert "event.target === overlay" in javascript
    assert 'event.key === "Escape"' in javascript
    assert "previouslyFocused?.focus?.()" in javascript
    assert "location.href" not in javascript
