from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

def test_hotfix_overlay_uses_self_contained_wheel_and_expected_message() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_DIR / "hotfix-overlay.js").read_text(encoding="utf-8")
    stylesheet = (WEB_DIR / "hotfix-overlay.css").read_text(encoding="utf-8")
    assert 'href="/assets/hotfix-overlay.css?v=20260815-scanner-errors"' in html
    assert 'src="/assets/hotfix-overlay.js?v=20260815-scanner-errors"' in html
    assert 'class="hotfix-wheel"' in javascript
    assert "wafer-transport.html" not in javascript
    assert "@keyframes hotfix-wheel-spin" in stylesheet
    assert "Potential Hot-Fix coming" in javascript

def test_hotfix_overlay_handles_server_failures_for_twenty_seconds() -> None:
    javascript = (WEB_DIR / "hotfix-overlay.js").read_text(encoding="utf-8")
    assert "const DISPLAY_MS = 20_000;" in javascript
    assert "response.status >= 500" in javascript
    assert 'error?.name !== "AbortError"' in javascript
    assert "window.fetch = async" in javascript
    assert "window.setTimeout(hidePotentialHotfix, DISPLAY_MS)" in javascript

def test_hotfix_overlay_can_be_dismissed_without_navigation() -> None:
    javascript = (WEB_DIR / "hotfix-overlay.js").read_text(encoding="utf-8")
    assert "event.target === overlay" in javascript
    assert 'event.key === "Escape"' in javascript
    assert "previouslyFocused?.focus?.()" in javascript
    assert "location.href" not in javascript


def test_only_user_request_failures_trigger_hotfix_animation() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    application = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    overlay = (WEB_DIR / "hotfix-overlay.js").read_text(encoding="utf-8")

    assert 'src="/assets/app.js?v=20260828-scanner-progress"' in html
    assert 'function errorMessage(message) {\n  return `<div class="error">' in application
    assert 'function errorMessage(message) {\n  notifyPotentialHotfix();' not in application
    assert 'if (connectorCompleted)' in application
    assert 'outputs.savedShips.innerHTML = errorMessage(error.message);' in application
    assert 'outputs.savedShips.innerHTML = connectorInstallPrompt(error.message);' in application
    connector_catch = application.split('outputs.savedShips.innerHTML = connectorInstallPrompt(error.message);', 1)[0]
    assert 'notifyPotentialHotfix();' in connector_catch[-120:]
    assert 'new CustomEvent("hotfix:show")' in application
    assert "window.SCCompanionHotfix" in overlay
