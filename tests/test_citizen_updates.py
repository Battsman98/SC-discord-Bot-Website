from pathlib import Path

from src.sources.citizen_updates import COMM_LINK_ARCHIVE_URLS, UPDATE_LOOKBACK_DAYS, CitizenUpdatesSource
from src.web import _website_audit_metadata


ROOT = Path(__file__).resolve().parents[1]


def test_direct_source_parsers_keep_official_and_unverified_items_separate() -> None:
    development = '''<a href="/en/comm-link/Patch-Notes/21245-Star-Citizen-Alpha-49">
      Star Citizen Alpha 4.9 Posted 6 days ago</a>'''
    status = '''<div class="issue" onclick="window.location='https:\\/\\/status.robertsspaceindustries.com\\/issues\\/live\\/index.html'">
      <div class="issue__header"><h3>Live Deployment</h3><span class="resolved">✔ Resolved</span></div>
      <small class="date" data-date="2026-07-21T12:00:00Z"></small>
      <span class="issue__content"><p>Servers are being updated.</p></span></div>'''
    comm_link = '''<a href="/en/comm-link/transmission/21251-Roadmap-Roundup-July-15-2026">
      post Roadmap Roundup - July 15, 2026 0 Posted: 1 week ago With the roadmap updated</a>'''
    community = '''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>New vehicle datamine leak</title><link href="https://www.reddit.com/r/starcitizen/comments/example"/>
      <updated>2026-07-21T01:02:03Z</updated><content type="html">Original public report</content>
      </entry></feed>'''

    patches = CitizenUpdatesSource.parse_patch_notes(development)
    incidents = CitizenUpdatesSource.parse_status_updates(status)
    previews = CitizenUpdatesSource.parse_comm_link_updates(comm_link)
    leaks = CitizenUpdatesSource.parse_community_intel(community)

    assert patches[0]["title"] == "Star Citizen Alpha 4.9"
    assert patches[0]["published"] == "6 days ago"
    assert patches[0]["confirmed"] is True
    assert incidents[0]["title"] == "Live Deployment"
    assert incidents[0]["url"].startswith("https://status.robertsspaceindustries.com/")
    assert previews[0]["title"] == "Roadmap Roundup - July 15, 2026"
    assert leaks[0]["confirmed"] is False
    assert leaks[0]["status"] == "Unverified"


def test_intel_tab_and_direct_source_disclosure_are_present() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

    assert 'data-tab="intel">Intel</button>' in html
    assert 'data-overview-tab="intel"' in html
    assert 'id="intelOutput"' in html
    assert "Leak and datamine posts are unverified" in html
    assert "Three months of official updates" in html
    assert 'id="intelUpdatedAt"' in html
    assert 'api("/api/updates")' in javascript
    assert html.index('data-tab="overview"') < html.index('data-tab="intel"') < html.index('data-tab="lookup"')
    assert html.index('data-overview-tab="intel"') < html.index('data-overview-tab="lookup"')
    assert 'intel: { theme: "aegis-intel", label: "AEGIS DYNAMICS INTELLIGENCE" }' in javascript
    assert 'body[data-mfd-theme="aegis-intel"]' in styles
    assert "--accent: #9fca62" in styles
    assert 'target="_blank" rel="noreferrer">Open source</a>' in javascript
    assert 'scroll through the past three months' in javascript
    assert "5 * 60_000" in javascript
    assert "void loadIntel(true, true)" in javascript
    assert "grid-auto-flow: column" in styles
    assert "overflow-x: auto" in styles
    assert UPDATE_LOOKBACK_DAYS == 90
    assert len(COMM_LINK_ARCHIVE_URLS) == 4
    assert all("robertsspaceindustries.com/en/comm-link" in url for url in COMM_LINK_ARCHIVE_URLS)


def test_direct_source_defaults_retain_a_three_month_sized_history() -> None:
    development = "".join(
        f'<a href="/en/comm-link/Patch-Notes/{number}-Patch-{number}">Patch {number} Posted 1 month ago</a>'
        for number in range(20)
    )
    status = "".join(
        f'<div class="issue"><div class="issue__header"><h3>Incident {number}</h3></div></div>'
        for number in range(20)
    )

    assert len(CitizenUpdatesSource.parse_patch_notes(development)) == 20
    assert len(CitizenUpdatesSource.parse_status_updates(status)) == 20


def test_updates_view_is_audited_as_updates() -> None:
    assert _website_audit_metadata("GET", "/api/updates") == ("updates", "Website Updates Viewed")
