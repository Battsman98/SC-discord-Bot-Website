from pathlib import Path


WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def test_home_page_uses_companion_branding_and_guidance() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    assert '<h1 class="companion-title">Star Citizen Companion</h1>' in html
    assert "Game Assist Control Deck" not in html
    assert "Star Citizen Discord Companion" not in html
    assert "Your Star Citizen companion" in html
    assert "Plan your next session, organize what you own" in html
    assert "The guide below provides a complete walkthrough" in html


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
    assert '"25", "29", "30", "32", "34", "36"' in javascript
    assert html.index('class="overview-options"') < html.index('class="home-background"')
    assert 'return "mobile"' in javascript
    assert 'return "tablet"' in javascript
    assert 'return "wide"' in javascript
    assert "prefers-reduced-motion: reduce" in javascript
    for image_id in ("10", "25", "29", "30", "31", "32", "34", "36"):
        for size in ("wide", "tablet", "mobile"):
            assert (WEB_DIR / "media" / "home" / f"sc-{image_id}-{size}.jpg").is_file()
    for image_id in range(1, 10):
        assert (WEB_DIR / "media" / "home" / f"user-{image_id:02}.webp").is_file()
    for image_id in range(1, 8):
        assert (WEB_DIR / "media" / "home" / f"gallery-{image_id:02}.webp").is_file()


def test_home_page_uses_twenty_curated_images_and_compact_navigation() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")

    background_block = javascript.split("const homeBackgrounds = [", 1)[1].split("];", 1)[0]
    assert background_block.count('"') // 2 == 20
    assert len([line for line in html.splitlines() if "data-home-slide=" in line]) == 20
    assert ".app-shell.overview-mode .tabs" in css
    assert ".app-shell.overview-mode .overview-options" in css
    assert "aspect-ratio: 16 / 7;" in css


def test_primary_navigation_stays_at_the_top_on_every_page() -> None:
    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")

    tabs_css = css.split(".tabs {", 1)[1].split("}", 1)[0]
    assert "position: sticky;" in tabs_css
    assert "top: 0;" in tabs_css
    assert "justify-content: safe center;" in tabs_css
    assert "grid-template-columns: minmax(0, 1fr);" in css
    assert "align-content: start;" in css


def test_fankit_trademark_notice_is_visible_on_the_home_page() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    assert "This site is not endorsed by or affiliated with the Cloud Imperium or Roberts Space Industries group of companies." in html
    assert "Star Citizen®, Squadron 42®, Roberts Space Industries®, and Cloud Imperium®" in html


def test_overview_exposes_all_primary_destinations() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    for tab_id in ("lookup", "trade", "mining", "crafting", "items", "inventory", "timers", "admin"):
        assert f'data-overview-tab="{tab_id}"' in html


def test_mining_page_includes_original_industry_operation_tools_without_external_links() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'data-action="industrySplit"' in html
    assert 'data-action="refineryTimer"' in html
    assert 'data-action="operationBrief"' in html
    assert "renderCrewSplit" in javascript
    assert "renderRefineryCompletion" in javascript
    assert "renderOperationBrief" in javascript
    assert "cryon.rocks" not in html
    assert "regolith.rocks" not in html

def test_guide_is_embedded_on_overview_without_a_separate_tab() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert '<section id="guide" hidden>' in html
    assert "Website Guide" in html
    assert 'data-tab="guide"' not in html
    assert 'data-overview-tab="guide"' not in html
    assert 'overviewPanel.append(standaloneGuide.firstElementChild)' in javascript
    assert 'data-tab="commands"' not in html
    assert 'data-overview-tab="commands"' not in html
    assert '<section id="commands"' not in html


def test_audit_navigation_is_revealed_only_for_authorized_users() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")

    tabs_markup = html.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]
    overview_markup = html.split('<nav class="overview-options"', 1)[1].split("</nav>", 1)[0]
    assert 'data-tab="admin"' not in tabs_markup
    assert 'data-overview-tab="admin"' not in overview_markup
    assert html.count("data-admin-only") == 2
    assert "setAdminVisibility(Boolean(currentUser.authenticated && currentUser.can_manage_admin))" in javascript
    assert "if (currentUser.can_manage_admin) await loadAudit();" in javascript
    assert '\nloadAudit();\n' not in javascript
    assert 'document.querySelectorAll("[data-admin-only]").forEach((element) => element.remove())' in javascript
    assert 'classList.toggle("without-audit", !canManageAdmin)' in javascript
    assert ".app-shell.overview-mode .tabs.without-audit" in css
    assert css.count("justify-content: safe center;") >= 2


def test_overview_does_not_expose_internal_system_information() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    assert "System and shared logic" not in html
    assert 'id="healthOutput"' not in html


def test_ship_search_results_are_contained_inside_ship_search_panel() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    ship_form_start = html.index('data-action="ship"')
    ship_form_end = html.index("</form>", ship_form_start)
    lookup_output = html.index('id="lookupOutput"')

    assert ship_form_start < lookup_output < ship_form_end


def test_hangar_modal_keeps_other_ships_visible() -> None:
    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")

    for state in (".hangar-modal-backdrop:hover", ".hangar-modal-backdrop:focus-visible", ".hangar-modal-backdrop:active"):
        assert state in css
    assert "background: transparent !important;" in css
    assert "backdrop-filter: none;" in css


def test_home_page_starts_on_a_random_background() -> None:
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "Math.floor(Math.random() * homeBackgrounds.length)" in javascript
    assert "showHomeBackground(homeSlideIndex, true)" in javascript


def test_destination_selection_reveals_full_navigation() -> None:
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'appShell.classList.toggle("overview-mode", tabId === "overview")' in javascript
    assert 'document.querySelectorAll("[data-overview-tab]")' in javascript


def test_each_tool_page_has_a_manufacturer_mfd_theme() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")

    assert 'data-mfd-theme="overview"' in html
    expected = {
        "lookup": ("drake", "DRAKE INTERPLANETARY"),
        "trade": ("grey-market", "GREY MARKET EXCHANGE"),
        "mining": ("argo", "ARGO ASTRONAUTICS"),
        "crafting": ("anvil", "ANVIL AEROSPACE"),
        "items": ("origin", "ORIGIN JUMPWORKS"),
        "inventory": ("rsi", "ROBERTS SPACE INDUSTRIES"),
        "timers": ("misc", "MISC INDUSTRIAL"),
        "admin": ("security", "SECURITY AUDIT"),
    }
    for tab_id, (theme, label) in expected.items():
        assert f'{tab_id}: {{ theme: "{theme}", label: "{label}" }}' in javascript
        assert f'body[data-mfd-theme="{theme}"]' in css
    assert "document.body.dataset.mfdTheme = mfdTheme.theme" in javascript
    assert "panel.dataset.mfdLabel = mfdTheme.label" in javascript


def test_selecting_ships_opens_and_refreshes_the_hangar() -> None:
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'if (tabId === "lookup")' in javascript
    assert 'showToolPanel(panel, "lookup-tool-0")' in javascript
    assert 'void loadSavedShips({ quiet: true })' in javascript
    assert "function showToolPanel(tab, id)" in javascript


def test_live_inventory_scans_use_the_low_overhead_request_path() -> None:
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'canvas.toBlob(resolve, "image/webp", 0.9)' in javascript
    assert 'if (options.liveScan) params.set("live_scan", "true")' in javascript


def test_live_inventory_scanner_retries_missed_reads_and_only_skips_exact_frames() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'frameRate: { ideal: 5, max: 8 }' in javascript
    assert 'imageHashDistance(inventoryScannerLastHash, capture.hash) === 0' in javascript
    assert 'if (payload?.items?.length)' in javascript
    assert 'inventoryScannerLastHash = ""' in javascript
    assert 'Math.max(1000' in javascript
    assert 'id="inventoryScannerSpacing" type="number" min="3000" step="500" value="3500"' in html
    assert 'inventoryScannerSpacingInput.value = "1200"' in javascript


def test_live_scanner_uses_preloaded_threaded_ocr_and_reduced_catalog_work() -> None:
    python = (WEB_DIR.parent / "src" / "web.py").read_text(encoding="utf-8")

    assert "await asyncio.to_thread(_initialize_rapid_ocr_pool)" in python
    assert "await asyncio.to_thread(_read_image_text, data)" in python
    assert "candidate_limit=4 if live_scan else None" in python


def test_live_scanner_runs_two_ocr_jobs_and_reports_stage_timings() -> None:
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    python = (WEB_DIR.parent / "src" / "web.py").read_text(encoding="utf-8")

    assert "inventoryScannerMaxInFlight = 2" in javascript
    assert "inventoryScannerPendingHashes" in javascript
    assert '"ocr_ms": ocr_ms' in python
    assert '"match_ms": match_ms' in python
    assert '"server_ms":' in python
    assert "_RAPID_OCR_POOL_SIZE = 2" in python


def test_inventory_clear_actions_use_centered_confirmation_dialog() -> None:
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")

    assert 'title: "Clear station inventory?"' in javascript
    assert 'title: "Clear all inventory?"' in javascript
    assert 'className = "inventory-confirm-backdrop"' in javascript
    assert "window.confirm" not in javascript
    assert ".inventory-confirm-backdrop" in css
    assert "place-items: center" in css


def test_audit_tab_displays_first_party_visitor_analytics() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="visitorAnalyticsOutput"' in html
    assert 'api("/api/audit/visitors")' in javascript
    assert "function renderVisitorAnalytics(data)" in javascript


def test_station_inventory_is_compact_at_partial_desktop_widths() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")

    assert "20260722-compact-inventory" in html
    assert "@media (min-width: 761px) and (max-width: 1200px)" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    assert "min-height: 52px" in css
