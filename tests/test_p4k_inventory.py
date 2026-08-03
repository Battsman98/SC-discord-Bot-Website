from pathlib import Path

from src.sources.p4k_inventory import P4KInventoryCatalog


def test_p4k_catalog_resolves_display_names_and_internal_aliases() -> None:
    catalog = P4KInventoryCatalog(Path("data/p4k_inventory_snapshot.json"))

    assert catalog.item_count >= 7_500
    assert catalog.lookup('Pyro RYT "Bloodline" Multi-Tool')[0].name == 'Pyro RYT "Bloodline" Multi-Tool'
    assert catalog.lookup("item_Namebehr_rifle_ballistic_03_store01")[0].name == 'CQ7 "Goldsmith" Rifle'
    assert catalog.lookup("grin_multitool_01_tractorbeam")[0].name == "TruHold Tractor Beam Attachment"
