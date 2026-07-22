from pathlib import Path

from src.sources.citizen_updates import CitizenUpdatesSource
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
    assert patches[0]["confirmed"] is True
    assert incidents[0]["title"] == "Live Deployment"
    assert incidents[0]["url"].startswith("https://status.robertsspaceindustries.com/")
    assert previews[0]["title"] == "Roadmap Roundup - July 15, 2026"
    assert leaks[0]["confirmed"] is False
    assert leaks[0]["status"] == "Unverified"


def test_intel_tab_and_direct_source_disclosure_are_present() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert 'data-tab="intel">Intel</button>' in html
    assert 'data-overview-tab="intel"' in html
    assert 'id="intelOutput"' in html
    assert "Leak and datamine posts are unverified" in html
    assert 'api("/api/updates")' in javascript
    assert 'intel: { theme: "aegis", label: "AEGIS DYNAMICS INTELLIGENCE" }' in javascript
    assert 'target="_blank" rel="noreferrer">Open source</a>' in javascript


def test_updates_view_is_audited_as_updates() -> None:
    assert _website_audit_metadata("GET", "/api/updates") == ("updates", "Website Updates Viewed")
