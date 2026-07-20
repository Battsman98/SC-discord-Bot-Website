import asyncio
from types import SimpleNamespace

from src.cache import SQLiteCache
from src.web import (
    SHIP_LOANERS,
    _blueprint_match_confidence,
    _blueprint_text_candidates,
    _extract_rsi_pledge_ship_names,
    _inventory_items_from_text,
    _inventory_item_from_tooltip_text,
    _inventory_match_confidence,
    _inventory_scanner_accepted_matches,
    _normalize_inventory_tooltip_name,
    _inventory_scanner_text_candidates,
    _rsi_import_lookup_candidates,
    _ship_display_name,
    _ship_is_in_concept,
)


def test_ship_display_name_removes_manufacturer_prefix() -> None:
    assert _ship_display_name("Anvil F7C-M Super Hornet Mk II") == "F7C-M Super Hornet Mk II"
    assert _ship_display_name("RSI Galaxy") == "Galaxy"
    assert _ship_display_name("Aopoa Nox") == "Nox"
    assert _ship_display_name("Galaxy") == "Galaxy"


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


def test_rsi_import_lookup_candidates_simplify_package_names() -> None:
    assert "Avenger Titan" in _rsi_import_lookup_candidates("Avenger Titan Starter Pack")


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

        await cache.delete_user_ship(42, "Drake Corsair")

        assert await cache.user_ships(42) == []
        await cache.close()


def test_user_inventory_round_trip_and_transfer(tmp_path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "bot.sqlite3"))
        item_id = await cache.save_user_inventory_item(
            user_id=42,
            item_name="FS-9 LMG",
            category="Weapons",
            location="Everus Harbor",
            quantity=2,
            notes="Personal storage",
        )

        items = await cache.user_inventory_items(42, sort_by="location")
        assert items == [
            {
                "id": item_id,
                "name": "FS-9 LMG",
                "category": "Weapons",
                "location": "Everus Harbor",
                "quantity": 2,
                "quality": None,
                "item_type": None,
                "item_size": None,
                "volume_scu": None,
                "notes": "Personal storage",
                "updated_at": items[0]["updated_at"],
            }
        ]

        assert await cache.user_inventory_facets(42) == {
            "locations": ["Everus Harbor"],
            "categories": ["Weapons"],
            "item_types": [],
            "item_sizes": [],
        }

        assert await cache.transfer_user_inventory_item(42, item_id, "Seraphim Station")
        transferred = await cache.user_inventory_items(42, location="Seraphim Station")
        assert transferred[0]["location"] == "Seraphim Station"

        assert await cache.delete_user_inventory_item(42, item_id)
        assert await cache.user_inventory_items(42) == []
        await cache.close()

    asyncio.run(run())


def test_user_inventory_filters_type_size_and_case_insensitive_station(tmp_path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "bot.sqlite3"))
        await cache.save_user_inventory_item(
            user_id=42,
            item_name="250-E Laser Pointer",
            category="Personal Weapons",
            location="Everus Harbor",
            quantity=3,
            item_type="Attachments",
            item_size="1",
        )
        await cache.save_user_inventory_item(
            user_id=42,
            item_name="FS-9 LMG",
            category="Personal Weapons",
            location="Port Tressler",
            quantity=1,
            item_type="Weapons",
            item_size="2",
        )

        matches = await cache.user_inventory_items(
            42,
            location=" everus harbor ",
            category="personal weapons",
            item_type="attachments",
            item_size="1",
        )
        assert [item["name"] for item in matches] == ["250-E Laser Pointer"]
        assert await cache.user_inventory_facets(42) == {
            "locations": ["Everus Harbor", "Port Tressler"],
            "categories": ["Personal Weapons"],
            "item_types": ["Attachments", "Weapons"],
            "item_sizes": ["1", "2"],
        }
        await cache.close()

    asyncio.run(run())


def test_user_inventory_duplicate_merge_keeps_one_station_item(tmp_path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "bot.sqlite3"))
        await cache.save_user_inventory_item(
            user_id=42,
            item_name="250-E Laser Pointer",
            category="Personal Weapons",
            location="Orison",
            quantity=1,
            item_type="Attachments",
            item_size="1",
            notes="Imported from hover scanner",
        )
        await cache.save_user_inventory_item(
            user_id=42,
            item_name="250-E Laser Pointer",
            category="Personal Weapons",
            location="Orison",
            quantity=1,
            item_type="Attachments",
            item_size="1",
            notes="Imported from hover scanner",
        )

        assert await cache.merge_user_inventory_duplicates(42) == 1

        items = await cache.user_inventory_items(42)
        assert len(items) == 1
        assert items[0]["name"] == "250-E Laser Pointer"
        assert items[0]["location"] == "Orison"
        assert items[0]["quantity"] == 1
        await cache.close()

    asyncio.run(run())


def test_user_inventory_bulk_clear_can_target_station_or_all(tmp_path) -> None:
    async def run() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "bot.sqlite3"))
        await cache.save_user_inventory_item(
            user_id=42,
            item_name="FS-9 LMG",
            category="Personal Weapons",
            location="Orison",
            quantity=1,
        )
        await cache.save_user_inventory_item(
            user_id=42,
            item_name="Stoic Suppressor2",
            category="Personal Weapons",
            location="Orison",
            quantity=1,
        )
        await cache.save_user_inventory_item(
            user_id=42,
            item_name="Argo Ore Pod",
            category="Utility",
            location="Port Tressler",
            quantity=1,
        )

        assert await cache.clear_user_inventory_items(42, " orison ") == 2
        remaining = await cache.user_inventory_items(42)
        assert [item["name"] for item in remaining] == ["Argo Ore Pod"]

        assert await cache.clear_user_inventory_items(42) == 1
        assert await cache.user_inventory_items(42) == []
        await cache.close()

    asyncio.run(run())


def test_inventory_items_from_text_parses_screen_capture_rows() -> None:
    text = "Inventory\nFS-9 LMG x2\n3 MedPen\nCategory\nPembroke Helmet"

    assert _inventory_items_from_text(text, "Everus Harbor", "Gear") == [
        {
            "name": "FS-9 LMG",
            "category": "Gear",
            "item_type": None,
            "item_size": None,
            "location": "Everus Harbor",
            "quantity": 2.0,
            "quality": None,
            "volume_scu": None,
            "notes": "Imported from screen capture",
        },
        {
            "name": "MedPen",
            "category": "Gear",
            "item_type": None,
            "item_size": None,
            "location": "Everus Harbor",
            "quantity": 3.0,
            "quality": None,
            "volume_scu": None,
            "notes": "Imported from screen capture",
        },
        {
            "name": "Pembroke Helmet",
            "category": "Gear",
            "item_type": None,
            "item_size": None,
            "location": "Everus Harbor",
            "quantity": 1.0,
            "quality": None,
            "volume_scu": None,
            "notes": "Imported from screen capture",
        },
    ]


def test_inventory_items_from_text_scanner_mode_uses_first_match() -> None:
    text = "FS-9 LMG x2\nDamage ballistic\nPersonal weapon"

    assert _inventory_items_from_text(text, "Everus Harbor", "Weapons", first_match=True) == [
        {
            "name": "FS-9 LMG",
            "category": "Personal Weapons",
            "item_type": "Primary",
            "item_size": None,
            "location": "Everus Harbor",
            "quantity": 2.0,
            "quality": None,
            "volume_scu": None,
            "notes": "Imported from hover scanner",
        }
    ]


def test_inventory_tooltip_parser_reads_quality_and_scu() -> None:
    text = """
    Irradiated Kopion Horn
    Volume: 1000 µSCU
    The horn of the kopion is made of a unique combination of bone and naturally-occurring carbon nanomaterials.
    Capacity: 1.00µSCU
    Kopion Horn 112 0.001 SCU
    """

    assert _inventory_items_from_text(text, "MIC-L1", None, first_match=True) == [
        {
            "name": "Irradiated Kopion Horn",
            "category": None,
            "item_type": None,
            "item_size": None,
            "location": "MIC-L1",
            "quantity": 0.001,
            "quality": 112.0,
            "volume_scu": 0.001,
            "notes": "Imported from hover scanner (Quality: 112, Volume: 0.001 SCU)",
        }
    ]


def test_inventory_tooltip_parser_classifies_weapon_attachment_without_scu() -> None:
    text = """
    TCRRGE RCCESE
    TART
    PT3"Deadfall"(3xHolographic)
    Volume:100µScU
    Manufacturer:Behring
    Type:Projection
    AttachmentPoint:Optic
    Magnification:3x
    Zoom:3x-3.5x
    Aim Time:+15%
    Size:1
    """

    assert _inventory_items_from_text(text, "Port Tressler", None, first_match=True) == [
        {
            "name": "PT3 Deadfall (3x Holographic)",
            "category": "Personal Weapons",
            "item_type": "Attachments",
            "item_size": "Size 1",
            "location": "Port Tressler",
            "quantity": 1.0,
            "quality": None,
            "volume_scu": None,
            "notes": "Imported from hover scanner",
        }
    ]


def test_inventory_tooltip_parser_reads_fs9_as_primary_weapon() -> None:
    text = """
    FS-9 LMG
    Volume: 18000 µSCU
    Manufacturer: Behring
    Item Type: LMG
    Class: Ballistic
    Magazine Size: 75
    Rate Of Fire: 800 rpm
    Effective Range: 40 m
    Attachments: Optics (S2), Barrel (S2), Underbarrel (S3)
    """

    assert _inventory_items_from_text(text, "Port Tressler", None, first_match=True) == [
        {
            "name": "FS-9 LMG",
            "category": "Personal Weapons",
            "item_type": "Primary",
            "item_size": None,
            "location": "Port Tressler",
            "quantity": 1.0,
            "quality": None,
            "volume_scu": None,
            "notes": "Imported from hover scanner",
        }
    ]


def test_inventory_scanner_candidates_ignore_tooltip_stats() -> None:
    text = """
    FS-9 LMG
    Volume: 18000 µSCU
    Manufacturer: Behring
    Item Type: LMG
    Class: Ballistic
    Magazine Size: 75
    Rate Of Fire: 800 rpm
    Effective Range: 40 m
    Attachments: Optics (S2), Barrel (S2), Underbarrel (S3)
    Behring designed the FS-9 to be an overwhelming battlefield force.
    """

    candidates = _inventory_scanner_text_candidates(text)

    assert candidates[0] == "FS-9 LMG"
    assert "Effective Range: 40 m" not in candidates
    assert "Attachments: Optics (S2), Barrel (S2), Underbarrel (S3)" not in candidates


def test_inventory_scanner_ignores_grey_description_after_weapon_stats() -> None:
    text = """
    HG-2 Jaeger (2x Holographic)
    Volume: 100 uSCU
    Manufacturer: Klaus & Werner
    Type: Holographic
    Attachment Point: Optic
    Magnification: 2x - 4x
    Aim Time: +5%
    Parallax: Low
    Size: 1
    Specializing in medium distance combat, the HG-2 Jaeger excels in situations where you want to keep your distance from hostiles.
    Tau Plus LL (4x Telescopic)
    Volume: 700 uSCU
    """

    candidates = _inventory_scanner_text_candidates(text)

    assert candidates[0] == "HG-2 Jaeger (2x Holographic)"
    assert "Tau Plus LL (4x Telescopic)" not in candidates


def test_inventory_scanner_can_read_multiple_white_tooltip_blocks() -> None:
    text = """
    HG-2 Jaeger (2x Holographic)
    Volume: 100 uSCU
    Manufacturer: Klaus & Werner
    Type: Holographic
    Attachment Point: Optic
    Size: 1
    Specializing in medium distance combat, the HG-2 Jaeger excels in situations where you want to keep your distance from hostiles.
    Tau Plus LL (4x Telescopic)
    Volume: 700 uSCU
    Manufacturer: NV-TAC
    Type: Telescopic
    Attachment Point: Optic
    Size: 2
    The Tau Plus 4x telescopic sight from NV-TAC uses a proprietary optics coating.
    """

    candidates = _inventory_scanner_text_candidates(text)

    assert candidates[:2] == ["HG-2 Jaeger (2x Holographic)", "Tau Plus LL (4x Telescopic)"]
    assert not any("proprietary optics" in candidate for candidate in candidates)


def test_inventory_tooltip_parser_uses_block_matching_catalog_item() -> None:
    text = """
    HG-2 Jaeger (2x Holographic)
    Volume: 100 uSCU
    Manufacturer: Klaus & Werner
    Type: Holographic
    Attachment Point: Optic
    Size: 1
    Tau Plus LL (4x Telescopic)
    Volume: 700 uSCU
    Manufacturer: NV-TAC
    Type: Telescopic
    Attachment Point: Optic
    Size: 2
    """

    item = _inventory_item_from_tooltip_text(text, "Orison", None, "Tau Plus LL (4x Telescopic)")

    assert item is not None
    assert item["name"] == "Tau Plus LL (4x Telescopic)"
    assert item["item_size"] == "Size 2"


def test_inventory_scanner_corrects_common_weapon_ocr_typos() -> None:
    assert _normalize_inventory_tooltip_name("Kilshot Rrie") == "Killshot Rifle"
    assert _normalize_inventory_tooltip_name("Paralax'Sorguine Energy Assault Rifle") == "Parallax'Sanguine Energy Assault Rifle"
    assert _inventory_match_confidence("Kilshot Rrie", "Killshot Rifle") >= 0.72


def test_inventory_match_confidence_does_not_mix_attachment_families() -> None:
    assert _inventory_match_confidence("Stoic Suppressor2", "Sion Compensator") < 0.72
    assert _inventory_match_confidence("Stoic Suppressor3", "Sion Compensator") < 0.72
    assert _inventory_match_confidence("Stoic Suppressor2", "Stoic Suppressor2") == 1


def test_inventory_match_confidence_scores_catalog_names() -> None:
    assert _inventory_match_confidence("FS-9 LMG", "FS-9 LMG") == 1
    assert _inventory_match_confidence("FS-9", "FS-9 LMG") >= 0.58
    assert _inventory_match_confidence("Effective Range", "FS-9 LMG") == 0


def test_inventory_scanner_accepts_only_best_match_per_hover_candidate() -> None:
    matches = [
        (SimpleNamespace(name='A03 "Canuto" Sniper Rifle'), 0.9),
        (SimpleNamespace(name='A03 "HighSec" Sniper Rifle'), 0.9),
        (SimpleNamespace(name='A03 "Wildwood" Sniper Rifle'), 0.9),
    ]

    accepted = _inventory_scanner_accepted_matches(matches, 0.72)

    assert len(accepted) == 1
    assert accepted[0][0].name == 'A03 "Canuto" Sniper Rifle'
