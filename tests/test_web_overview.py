from pathlib import Path


WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def test_home_page_uses_companion_branding_and_guidance() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    assert '<h1 class="companion-title">Star Citizen Companion</h1>' in html
    assert "Game Assist Control Deck" not in html
    assert "Star Citizen Discord Companion" not in html
    assert "Welcome to your home page" in html
    assert "Select a destination below to get started." in html


def test_overview_exposes_all_primary_destinations() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    for tab_id in ("lookup", "trade", "mining", "crafting", "items", "inventory", "timers", "commands", "admin"):
        assert f'data-overview-tab="{tab_id}"' in html


def test_overview_system_information_is_collapsed_by_default() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    assert '<details class="overview-details">' in html
    assert '<summary>System and shared logic</summary>' in html


def test_destination_selection_reveals_full_navigation() -> None:
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'appShell.classList.toggle("overview-mode", tabId === "overview")' in javascript
    assert 'document.querySelectorAll("[data-overview-tab]")' in javascript
