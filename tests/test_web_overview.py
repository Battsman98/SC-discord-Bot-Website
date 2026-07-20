from pathlib import Path


WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def test_home_page_uses_companion_branding_and_guidance() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    assert '<h1 class="companion-title">Star Citizen Companion</h1>' in html
    assert "Game Assist Control Deck" not in html
    assert "Star Citizen Discord Companion" not in html
    assert "Welcome to your home page" in html
    assert "Select a destination below to get started." in html


def test_site_uses_gunmetal_and_amber_palette() -> None:
    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")

    assert "--bg: #050505;" in css
    assert "--surface: #17191b;" in css
    assert "--text: #e8e9e9;" in css
    assert "--accent: #e49a18;" in css
    assert "--accent-2: #ffc247;" in css


def test_home_page_rotates_official_responsive_fankit_wallpapers() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'class="home-background"' in html
    assert 'src="/assets/media/home/made-by-community.png"' in html
    assert 'const homeBackgrounds = ["10", "25", "29", "30", "31", "32", "34", "36"]' in javascript
    assert html.index('class="overview-options"') < html.index('class="home-background"') < html.index('class="overview-details"')
    assert 'return "mobile"' in javascript
    assert 'return "tablet"' in javascript
    assert 'return "wide"' in javascript
    assert "prefers-reduced-motion: reduce" in javascript
    for image_id in ("10", "25", "29", "30", "31", "32", "34", "36"):
        for size in ("wide", "tablet", "mobile"):
            assert (WEB_DIR / "media" / "home" / f"sc-{image_id}-{size}.jpg").is_file()


def test_fankit_trademark_notice_is_visible_on_the_home_page() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    assert "This site is not endorsed by or affiliated with the Cloud Imperium or Roberts Space Industries group of companies." in html
    assert "Star Citizen®, Squadron 42®, Roberts Space Industries®, and Cloud Imperium®" in html


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
