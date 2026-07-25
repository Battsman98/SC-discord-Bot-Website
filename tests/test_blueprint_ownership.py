import asyncio
from types import SimpleNamespace

from src.cache import SQLiteCache
from src.web import (
    SHIP_LOANERS,
    _blueprint_match_confidence,
    _blueprint_text_candidates,
    _clean_redundant_loaner_note,
    _extract_rsi_pledge_ship_names,
    _rsi_import_lookup_candidates,
    _rsi_import_protected_names,
    _ship_basic_info,
    _ship_display_name,
    _ship_image_needs_refresh,
    _ship_is_in_concept,
)


def test_ship_display_name_removes_manufacturer_prefix() -> None:
    assert _ship_display_name("Anvil F7C-M Super Hornet Mk II") == "F7C-M Super Hornet Mk II"
    assert _ship_display_name("RSI Galaxy") == "Galaxy"
    assert _ship_display_name("Aopoa Nox") == "Nox"
    assert _ship_display_name("Galaxy") == "Galaxy"


def test_ship_image_refresh_detects_missing_and_low_resolution_urls() -> None:
    assert _ship_image_needs_refresh(None)
    assert _ship_image_needs_refresh("https://media.starcitizen.tools/thumb/x/600px-ship.webp")
    assert _ship_image_needs_refresh("https://media.robertsspaceindustries.com/x/store_small.jpg")
    assert not _ship_image_needs_refresh("https://media.starcitizen.tools/x/ship-4k.png")


def test_arrastra_loaners_are_mapped() -> None:
    assert SHIP_LOANERS["arrastra"] == ["Anvil Arrow", "Argo MOLE", "MISC Prospector"]
    assert SHIP_LOANERS["galaxy"] == ["Anvil Carrack"]
    assert SHIP_LOANERS["orion"] == ["Prospector", "Mole"]
    assert SHIP_LOANERS["merchantman"] == ["Hull C", "Defender", "Hercules C2"]
    assert SHIP_LOANERS["kraken"] == ["Polaris", "Ironclad Assault", "Buccaneer"]


def test_auto_loaners_require_in_concept_status() -> None:
    assert _ship_is_in_concept("in-concept")
    assert _ship_is_in_concept("In Concept")
    assert not _ship_is_in_concept("flight-ready")
    assert not _ship_is_in_concept(None)


def test_loaner_uses_the_same_ship_specs_as_other_ownership_types() -> None:
    detail = SimpleNamespace(
        career="Exploration",
        role="Expedition",
        vehicle_type="multi",
        size="large",
        status="flight-ready",
        cargo_capacity=456,
    )

    assert _ship_basic_info(detail) == "Exploration / Expedition | multi | large | flight-ready | 456 SCU"


def test_generated_loaner_note_is_removed_but_user_notes_are_preserved() -> None:
    assert _clean_redundant_loaner_note("Loaner for Galaxy", "Galaxy") is None
    assert _clean_redundant_loaner_note("  loaner FOR RSI-Galaxy  ", "RSI Galaxy") is None
    assert _clean_redundant_loaner_note("Keep the medical loadout", "Galaxy") == "Keep the medical loadout"


def test_extract_rsi_pledge_ship_names_from_saved_page() -> None:
    page = """
    <html>
      <body>
        <div>Standalone Ship - RSI Galaxy Serial 123 Insurance Lifetime</div>
        <div>Contains Anvil Carrack Also Contains Carrack Plushie</div>
        <div>Package - F7C-M Super Hornet Mk II Serial 999</div>
      </body>
    </html>
    """

    assert _extract_rsi_pledge_ship_names(page) == {
        "RSI Galaxy",
        "Anvil Carrack",
        "F7C-M Super Hornet Mk II",
    }


def test_extract_rsi_pledge_ship_names_from_game_package_blocks() -> None:
    page = """
    <html><body>
      <section>Game Package Avenger Titan Starter Pack Created 2026-01-01 Contains Avenger Titan Also Contains Self-Land Hangar</section>
      <section>Standalone Ship RSI Arrastra Attributed Contains RSI Arrastra Insurance 120 Month</section>
    </body></html>
    """

    assert {"Avenger Titan", "RSI Arrastra"}.issubset(_extract_rsi_pledge_ship_names(page))


def test_extract_rsi_pledge_ship_names_from_pledge_links() -> None:
    page = """
    <a href="/pledge/ships/600i/600i-Explorer">600i Explorer</a>
    <a href="/pledge/ships/anvil-hornet-mkii/F7C-M-Super-Hornet-Mk-II">F7C-M Super Hornet Mk II</a>
    """

    assert _extract_rsi_pledge_ship_names(page) == {
        "600i Explorer",
        "F7C M Super Hornet Mk II",
    }


def test_rsi_pledge_extraction_rejects_account_junk_chunks() -> None:
    page = """
    <div>Standalone Ship 600i Name Reservation Subscribers Store - Pyro RYT "Bloodline" Multi-tool [] null Attributed Created: May 15, 2026, Aeroview, Aurora MR Upgrades</div>
    <div>Package Pledges, Pound sterling, RediMake Item Fabricator AA Support Apollo Alliance Aid Red, Self-Land, United States dollar, VFG Industrial</div>
    """

    assert _extract_rsi_pledge_ship_names(page) == set()


def test_extract_rsi_pledge_ship_names_from_json_payload() -> None:
    page = r'''
    <script>
    window.__pledges = [
      {"title":"Standalone Ship - RSI Arrastra with Lifetime Insurance"},
      {"name":"Package - Avenger Titan Starter Pack"},
      {"label":"Carrack Plushie"}
    ];
    </script>
    '''

    assert _extract_rsi_pledge_ship_names(page) == {
        "RSI Arrastra",
        "Avenger Titan Starter Pack",
    }


def test_rsi_hangar_import_ignores_non_ship_pledge_items() -> None:
    page = r'''
    <script>
    window.__pledges = [
      {"title":"Upgrade - Aurora MR to Avenger Titan"},
      {"name":"Polar Paint Collection"},
      {"label":"CF-337 Panther Repeater"},
      {"title":"Standalone Ship - Anvil Arrow with Lifetime Insurance"}
    ];
    </script>
    <section>Upgrade Aurora MR to Avenger Titan</section>
    <section>Paints Anvil Arrow - Lovestruck Paint</section>
    <section>Add-Ons Greycat Armor Set</section>
    '''

    assert _extract_rsi_pledge_ship_names(page) == {"Anvil Arrow"}


def test_rsi_hangar_import_reads_colon_separated_contained_ships() -> None:
    page = r'''
    <article>Industrial Collection</article>
    <div>Contains: ARGO MOTH Also Contains: ARGO SRV</div>
    <div>Contains: Aegis Reclaimer Insurance 10 Year</div>
    <div>Upgrade - F8C to F8C with 10 Year Insurance</div>
    '''

    assert _extract_rsi_pledge_ship_names(page) == {
        "ARGO MOTH",
        "ARGO SRV",
        "Aegis Reclaimer",
    }


def test_rsi_hangar_import_reads_typed_ship_items_from_upgraded_pledges() -> None:
    page = r'''
    <li class="pledge">
      <input class="js-pledge-name" value="Upgrade - F8C to F8C with 10 Year Insurance">
      <div class="item"><span class="kind">Ship</span><strong class="title">Aegis Reclaimer</strong></div>
      <div class="item"><span class="kind">Vehicle</span><strong class="title">ARGO SRV</strong></div>
      <div class="item"><strong class="title">ARGO MOTH</strong><span class="kind">Ship</span></div>
      <div class="item"><span class="kind">Paint</span><strong class="title">MOTH Yellow Paint</strong></div>
    </li>
    '''

    assert _extract_rsi_pledge_ship_names(page) == {
        "Aegis Reclaimer",
        "ARGO SRV",
        "ARGO MOTH",
    }


def test_rsi_import_lookup_candidates_simplify_package_names() -> None:
    assert "Avenger Titan" in _rsi_import_lookup_candidates("Avenger Titan Starter Pack")


def test_rsi_sync_protects_canonical_and_display_ship_names() -> None:
    protected = _rsi_import_protected_names({"ARGO SRV", "Aegis Reclaimer"}, ["SRV", "Reclaimer"])

    assert "argo srv" in protected
    assert "srv" in protected
    assert "aegis reclaimer" in protected
    assert "reclaimer" in protected
    assert "moth" not in protected


def test_blueprint_text_candidates_clean_ocr_lines() -> None:
    text = "Owned\nAtlas Quantum Drive\n  VK-00 Quantum Drive  \nBlueprints"

    assert _blueprint_text_candidates(text) == ["Atlas Quantum Drive", "VK-00 Quantum Drive"]


def test_blueprint_match_confidence_scores_exact_and_partial_matches() -> None:
    assert _blueprint_match_confidence("Atlas Quantum Drive", "Atlas Quantum Drive") == 1
    assert _blueprint_match_confidence("Atlas Quantum", "Atlas Quantum Drive") > 0.5


def test_user_blueprint_ownership_round_trip(tmp_path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "bot.sqlite3"))
        await cache.save_user_blueprint(
            user_id=42,
            blueprint_name="Atlas Quantum Drive",
            category="Quantum Drive",
            source_name="SC Craft Tools",
            source_url="https://example.test/atlas",
        )

        blueprints = await cache.user_blueprints(42)

        assert blueprints == [
            {
                "name": "Atlas Quantum Drive",
                "category": "Quantum Drive",
                "source_name": "SC Craft Tools",
                "source_url": "https://example.test/atlas",
                "saved_at": blueprints[0]["saved_at"],
            }
        ]

        await cache.delete_user_blueprint(42, "Atlas Quantum Drive")

        assert await cache.user_blueprints(42) == []
        await cache.close()

    asyncio.run(run())


def test_user_ship_ownership_round_trip(tmp_path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "bot.sqlite3"))
        await cache.save_user_ship(
            user_id=42,
            ship_name="Drake Corsair",
            ownership_type="pledged",
            manufacturer="Drake Interplanetary",
            role="Exploration",
            source_name="Star Citizen Wiki",
            source_url="https://example.test/corsair",
        )

        ships = await cache.user_ships(42)

        assert ships == [
            {
                "name": "Drake Corsair",
                "ownership_type": "pledged",
                "manufacturer": "Drake Interplanetary",
                "role": "Exploration",
                "source_name": "Star Citizen Wiki",
                "source_url": "https://example.test/corsair",
                "image_url": None,
                "notes": None,
                "loaner_for": None,
                "quantity": 1,
                "saved_at": ships[0]["saved_at"],
            }
        ]

        await cache.save_user_ship(
            user_id=42,
            ship_name="Drake Corsair",
            ownership_type="loaner",
            manufacturer="Drake Interplanetary",
            role="Exploration",
            source_name="Star Citizen Wiki",
            source_url="https://example.test/corsair",
        )

        assert (await cache.user_ships(42))[0]["ownership_type"] == "loaner"

        await cache.save_user_ship(
            user_id=42,
            ship_name="Drake Corsair",
            ownership_type="loaner",
            manufacturer="Drake Interplanetary",
            role="Exploration",
            source_name="Star Citizen Wiki",
            source_url="https://example.test/corsair",
            quantity=2,
        )

        assert (await cache.user_ships(42))[0]["quantity"] == 2

        await cache.delete_user_ship(42, "Drake Corsair")

        assert await cache.user_ships(42) == []
        await cache.close()
