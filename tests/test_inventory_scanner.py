import asyncio
import threading
import time
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pytest

import src.web as web_module
from src.cache import SQLiteCache
from src.web import (
    _inventory_catalog_item_type,
    _inventory_item_from_tooltip_text,
    _inventory_items_from_text,
    _inventory_match_confidence,
    _inventory_scanner_accepted_matches,
    _inventory_scanner_diagnostics,
    _inventory_scanner_lookups,
    _inventory_scanner_text_candidates,
    _match_inventory_scanner_text,
    _normalize_inventory_tooltip_name,
    _read_inventory_title_bands,
    _read_title_above_volume_anchor,
    _top_inventory_ocr_candidate,
)


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
        assert items[0]["quantity"] == 2
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
    assert _inventory_match_confidence("QuartzGCD-ArmySMG", "Quartz GCD-Army SMG") >= 0.95
    assert _inventory_match_confidence(
        'Arrowhead"ExecutiveSniperRifle',
        'Arrowhead "Executive" Sniper Rifle',
    ) >= 0.95


def test_inventory_title_normalization_recovers_medpen_hemozal_ocr() -> None:
    normalized = _normalize_inventory_tooltip_name("Med Pen CHemozaly")

    assert normalized == "MedPen Hemozal"
    assert _inventory_match_confidence(normalized, "MedPen (Hemozal)") >= 0.88


def test_inventory_match_ignores_optional_class_prefix_for_any_item_title() -> None:
    examples = (
        ("Mil/1/B Polar", "Polar"),
        ("Civ/2/C Frost-Star EX", "Frost-Star EX"),
        ("Cmp/3/A Venture Core", "Venture Core"),
        ("Ind/1/B Pyro RYT Multi-Tool", "Pyro RYT Multi-Tool"),
    )

    for scanned_title, catalog_title in examples:
        assert _normalize_inventory_tooltip_name(scanned_title) == catalog_title
        assert _inventory_match_confidence(scanned_title, catalog_title) == 1


def test_inventory_title_bands_keep_titles_and_reject_metadata(monkeypatch) -> None:
    calls = 0

    def fake_engine(_image):
        nonlocal calls
        calls += 1
        text = "Volume: 8000 uSCU" if calls == 1 else "Venture Core"
        return [[None, text]], None

    monkeypatch.setattr(web_module, "_initialize_rapid_title_ocr", lambda: fake_engine)
    image = Image.new("RGB", (240, 120), "black")
    output = BytesIO()
    image.save(output, format="PNG")

    text = _read_inventory_title_bands(output.getvalue())

    assert "Venture Core" in text
    assert "Volume" not in text


def test_inventory_title_uses_bounded_fallback_bands_when_default_misses(monkeypatch) -> None:
    attempted_boxes: list[str] = []

    def fake_read(_image_data: bytes, title_box: str) -> str:
        attempted_boxes.append(title_box)
        return "Venture Core" if len(attempted_boxes) == 3 else ""

    monkeypatch.setattr(web_module, "_read_calibrated_inventory_title", fake_read)

    text, calibrated_box, used_fast = web_module._read_inventory_title(b"image", None)

    assert text == "Venture Core"
    assert calibrated_box == attempted_boxes[2]
    assert used_fast is True
    assert len(attempted_boxes) == 3


def test_inventory_title_recalibrates_when_previous_title_position_misses(monkeypatch) -> None:
    attempted_boxes: list[str] = []

    def fake_read(_image_data: bytes, title_box: str) -> str:
        attempted_boxes.append(title_box)
        return "JS-400" if len(attempted_boxes) == 2 else ""

    monkeypatch.setattr(web_module, "_read_calibrated_inventory_title", fake_read)

    text, calibrated_box, used_fast = web_module._read_inventory_title(
        b"image",
        "0.525000,0.381500,0.275000,0.037000",
    )

    assert text == "JS-400"
    assert calibrated_box == attempted_boxes[1]
    assert used_fast is True


def test_inventory_title_does_not_calibrate_to_scanner_chrome(monkeypatch) -> None:
    attempted_boxes: list[str] = []

    def fake_read(_image_data: bytes, title_box: str) -> str:
        attempted_boxes.append(title_box)
        return "TOSTAR" if len(attempted_boxes) == 1 else "Regulus"

    monkeypatch.setattr(web_module, "_read_calibrated_inventory_title", fake_read)

    text, calibrated_box, used_fast = web_module._read_inventory_title(b"image", None)

    assert text == "Regulus"
    assert calibrated_box == attempted_boxes[1]
    assert used_fast is True


def test_inventory_scanner_preserves_internal_item_key_for_catalog_alias_matching() -> None:
    raw_key = "item_Namebehrsrife_ballstic_03_store"

    candidates = web_module._inventory_scanner_text_candidates(raw_key)

    assert candidates[0] == raw_key
    assert web_module._inventory_match_confidence(
        candidates[0],
        "item_Namebehr_rifle_ballistic_03_store01",
    ) >= 0.88


def test_inventory_title_regions_ignore_stale_calibration_and_cover_full_frame() -> None:
    stale = "0.300000,0.230000,0.380000,0.055000"

    boxes = web_module._inventory_title_boxes(stale)

    assert boxes[0] == web_module._DEFAULT_INVENTORY_TITLE_BOX
    assert boxes[1] == stale
    assert any(float(box.split(",")[1]) >= 0.5 for box in boxes)


def test_inventory_catalog_item_type_fills_missing_catalog_subtypes() -> None:
    assert _inventory_catalog_item_type("Navoi Boot and Pants Striker", "Clothing") == "Footwear"
    assert _inventory_catalog_item_type("ThermoWave Gloves ASD Edition", "Clothing") == "Gloves"
    assert _inventory_catalog_item_type("Pyro RYT microTech Multi-Tool", "Utility") == "Multitool"
    assert _inventory_catalog_item_type("Thunderbolt III Missile", "Components") == "Ordnance"
    assert _inventory_catalog_item_type("Wei-Tek L86 Radar", "Components") == "Radar"
    assert _inventory_catalog_item_type("Polar Paint", "Components") == "Liveries"
    assert _inventory_catalog_item_type("Atlas Quantum Drive", "Components") == "Quantum Drives"
    assert _inventory_catalog_item_type("Unknown Item", "Clothing") is None


def test_inventory_title_ocr_uses_top_line_and_rejects_metadata_calibration() -> None:
    title = ([[0, 4], [100, 4], [100, 14], [0, 14]], "FS-9 LMG", 0.98)
    metadata = ([[0, 30], [100, 30], [100, 40], [0, 40]], "Volume: 8000 µSCU", 0.99)

    assert _top_inventory_ocr_candidate([metadata, title]) == title
    assert _top_inventory_ocr_candidate([metadata]) is None
    compact_header = ([[0, 4], [100, 4], [100, 14], [0, 14]], "LOOTINGVIEW", 0.98)
    assert _top_inventory_ocr_candidate([compact_header]) is None


def test_inventory_title_ocr_uses_volume_anchor_instead_of_unrelated_top_text() -> None:
    unrelated = ([[900, 10], [1000, 10], [1000, 25], [900, 25]], "LOOTING VIEW", 0.99)
    title = ([[400, 180], [560, 180], [560, 198], [400, 198]], 'Demeco "Red Alert" LMG', 0.99)
    metadata = ([[400, 202], [520, 202], [520, 218], [400, 218]], "Volume: 18000 uSCU", 0.99)

    assert _top_inventory_ocr_candidate([unrelated, metadata, title]) == title


def test_inventory_title_anchor_keeps_detected_title_immediately_above_volume() -> None:
    title = ([[400, 180], [560, 180], [560, 198], [400, 198]], "SnowBlind", 0.99)
    volume = ([[400, 202], [540, 202], [540, 218], [400, 218]], "Volume: 84000 uSCU", 0.99)

    recovered = _read_title_above_volume_anchor(b"", [title, volume], title)

    assert recovered is not None
    assert recovered[0] == "SnowBlind"


def test_inventory_title_ocr_prefers_upper_hover_tooltip_over_equipped_item() -> None:
    hover_title = ([[400, 180], [620, 180], [620, 198], [400, 198]], 'Ravager-212 "Red Alert" Twin Shotgun', 0.99)
    hover_volume = ([[400, 202], [540, 202], [540, 218], [400, 218]], "Volume: 16000 uSCU", 0.99)
    equipped_title = ([[400, 450], [500, 450], [500, 468], [400, 468]], "FS-9 LMG", 0.99)
    equipped_volume = ([[400, 472], [540, 472], [540, 488], [400, 488]], "Volume: 18000 uSCU", 0.99)

    assert _top_inventory_ocr_candidate(
        [equipped_volume, hover_volume, equipped_title, hover_title]
    ) == hover_title


def test_inventory_title_ocr_allows_independent_engines_to_run_concurrently() -> None:
    active_calls = 0
    max_active_calls = 0
    state_lock = threading.Lock()

    def engine(_image_data: bytes):
        nonlocal active_calls, max_active_calls
        with state_lock:
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
        time.sleep(0.03)
        with state_lock:
            active_calls -= 1
        return [], 0

    threads = [
        threading.Thread(target=web_module._run_rapid_title_ocr, args=(b"image", engine))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active_calls == 2


def test_inventory_scanner_gate_runs_two_and_queues_two_without_user_overlap() -> None:
    async def run() -> None:
        gate = web_module.InventoryScannerGate(worker_count=2, capacity=4)
        active = 0
        max_active = 0
        entered: list[int] = []

        async def scan(user_id: int) -> None:
            nonlocal active, max_active
            async with gate.admit(user_id) as (scan_id, queue_ms):
                assert scan_id
                assert queue_ms >= 0
                active += 1
                max_active = max(max_active, active)
                entered.append(user_id)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*(scan(user_id) for user_id in range(1, 5)))
        assert max_active == 2
        assert sorted(entered) == [1, 2, 3, 4]

    asyncio.run(run())


def test_inventory_scanner_gate_rejects_overlapping_scan_for_same_user() -> None:
    async def run() -> None:
        gate = web_module.InventoryScannerGate(worker_count=1, capacity=4)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def first_scan() -> None:
            async with gate.admit(42):
                entered.set()
                await release.wait()

        task = asyncio.create_task(first_scan())
        await entered.wait()
        with pytest.raises(web_module.HTTPException) as error:
            async with gate.admit(42):
                pass
        assert error.value.status_code == 409
        release.set()
        await task

    asyncio.run(run())


def test_inventory_match_prefers_named_multitool_variant_over_generic_item() -> None:
    candidate = 'Pyro RYT "micro tech" Multi-Tool'
    variant = _inventory_match_confidence(candidate, 'Pyro RYT "microTech" Multi-Tool')
    generic = _inventory_match_confidence(candidate, "Pyro RYT Multi-Tool")

    assert variant >= 0.98
    assert generic <= 0.88
    assert variant - generic >= 0.04


def test_inventory_match_recovers_structured_item_codes_from_clear_suffixes() -> None:
    assert _inventory_match_confidence("MiBPolar", "Mil/1/B Polar") >= 0.9
    assert _inventory_match_confidence("MiCBracer", "Mil/1/C Bracer") >= 0.9
    assert _inventory_match_confidence("Sth/VA Snoweind", "Sth/1/A SnowBlind") >= 0.9
    assert _inventory_match_confidence("ind/ivc Thermax", "Ind/1/C Thermax") >= 0.9


def test_inventory_scanner_rejects_ambiguous_variant_matches_for_review() -> None:
    matches = [
        (SimpleNamespace(name='A03 "Canuto" Sniper Rifle'), 0.9),
        (SimpleNamespace(name='A03 "HighSec" Sniper Rifle'), 0.9),
        (SimpleNamespace(name='A03 "Wildwood" Sniper Rifle'), 0.9),
    ]

    accepted = _inventory_scanner_accepted_matches(matches, 0.72)

    assert accepted == []


def test_inventory_scanner_reuses_catalog_lookups_for_results_and_diagnostics(monkeypatch) -> None:
    text = "FS-9 LMG\nWeapon\nSize 1\nEffective Range 100 m"
    calls: list[str] = []

    async def fake_lookup(candidate: str, limit: int = 5):
        calls.append(candidate)
        return [(
            SimpleNamespace(
                name="FS-9 LMG",
                category="Weapons",
                section="Light machine gun",
                size="1",
                source_name="Test catalog",
                source_url="https://example.test/fs-9",
            ),
            1.0 if candidate == "FS-9 LMG" else 0.0,
        )]

    async def run() -> None:
        monkeypatch.setattr(web_module, "_inventory_lookup_scored_matches", fake_lookup)
        lookups = await _inventory_scanner_lookups(text, None, candidate_limit=1)
        assert len(lookups) == 1
        assert len(calls) == len(lookups)

        async def unexpected_lookup(*args, **kwargs):
            raise AssertionError("cached scanner lookups should be reused")

        monkeypatch.setattr(web_module, "_inventory_lookup_scored_matches", unexpected_lookup)
        await _match_inventory_scanner_text(text, "Port Tressler", None, 0.72, None, lookups)
        await _inventory_scanner_diagnostics(text, 0.72, None, lookups)

    asyncio.run(run())


def test_inventory_scanner_optional_type_filter_restricts_catalog_matches(monkeypatch) -> None:
    async def fake_lookup(candidate: str, limit: int = 5, category: str | None = None):
        del candidate, limit, category
        return [
            (SimpleNamespace(name="FS-9 LMG", category="Weapons", section="Light machine gun"), 1.0),
            (SimpleNamespace(name="Coda Pistol", category="Weapons", section="Pistol"), 0.9),
        ]

    async def run() -> None:
        monkeypatch.setattr(web_module, "_inventory_lookup_scored_matches", fake_lookup)
        primary = await _inventory_scanner_lookups(
            "FS-9 LMG", None, candidate_limit=1, category="Weapons", item_type="Primary"
        )
        sidearm = await _inventory_scanner_lookups(
            "Coda Pistol", None, candidate_limit=1, category="Weapons", item_type="Sidearm"
        )
        fallback = await _inventory_scanner_lookups(
            "FS-9 LMG", None, candidate_limit=1, category="Weapons", item_type="Undersuit"
        )

        assert [result.name for result, _score in next(iter(primary.values()))] == ["FS-9 LMG"]
        assert [result.name for result, _score in next(iter(sidearm.values()))] == ["Coda Pistol"]
        assert len(next(iter(fallback.values()))) == 2

    asyncio.run(run())
