"""RR ROM slot oracles. No vanilla wild data is a source of RR encounter facts."""

import os
import struct
from pathlib import Path

import pytest

from tools import rr_rom_encounters as rr

ROOT = Path(__file__).resolve().parents[2]


def load_pinned_rr_rom():
    explicit = os.environ.get("SLINK_RR_ROM")
    path = Path(explicit) if explicit else Path(os.environ.get("SLINK_GEN3_ROMS", ROOT)) / "Pokemon - Radical Red.gba"
    if not path.exists():
        if explicit:
            pytest.fail(f"SLINK_RR_ROM does not exist: {path}")
        pytest.skip("RR encounter oracle requires the pinned RR ROM (SLINK_RR_ROM or SLINK_GEN3_ROMS)")
    return rr.load_rom(path)


@pytest.fixture(scope="module")
def rr_rom():
    return load_pinned_rr_rom()


def fake_rom():
    rom = bytearray(0x200)
    struct.pack_into("<BBHIIII", rom, 0x20, 3, 19, 0, rr.BASE+0xA0, 0, 0, 0)
    rom[0x34:0x36] = b"\xff\xff"
    struct.pack_into("<B3xI", rom, 0xA0, 20, rr.BASE+0x120)
    for i in range(12):
        struct.pack_into("<BBH", rom, 0x120+i*4, 2, 4, 1222)
    return rom


def test_repointed_table_follows_info_and_slots_without_a_base_species_conversion():
    table = rr.read_table(bytes(fake_rom()), rr.BASE+0x20)
    assert len(table) == 1
    land = table[0]["habitats"]["land"]
    assert land["info_address"] == rr.BASE+0xA0 and land["slots_address"] == rr.BASE+0x120
    assert [r["species_id"] for r in land["slots"]] == [1222]*12
    assert land["slots"][0]["raw_hex"] == "0204c604"


@pytest.mark.parametrize("where", [0x24, 0xA4])
def test_out_of_range_pointer_refuses_the_walk(where):
    rom = fake_rom()
    struct.pack_into("<I", rom, where, 0x09FFFFFE)
    with pytest.raises(ValueError, match="out of range"):
        rr.read_table(bytes(rom), rr.BASE+0x20)


def test_missing_sentinel_is_bounded():
    with pytest.raises(ValueError, match="no sentinel"):
        rr.read_table(bytes(fake_rom()), rr.BASE+0x20, max_headers=1)


def test_rr_selector_resolves_primary_tables_and_the_distinct_legacy_fallback(rr_rom):
    decoded = rr.decode_encounters(rr_rom)
    assert decoded["heads"] == {"Day": 0x09166AB8, "Night": 0x09166428, "Fallback": 0x0872C984}
    assert {k: len(v) for k, v in decoded["tables"].items()} == {"Day": 83, "Night": 83, "Fallback": 142}
    night = rr.effective_maps(decoded, "Night")[(3, 19)]["habitats"]["land"]
    assert night["selected_from"] == "Night"
    assert [slot["species_id"] for slot in night["slots"]] == [286, 1222, 1020, 612, 1208, 163, 16, 16, 298, 298, 566, 566]
    changed = bytearray(rr_rom)
    changed[0x10C356E] ^= 1
    with pytest.raises(ValueError, match="selector instruction changed"):
        rr.table_heads(bytes(changed))


def test_catalog_diff_retains_species_and_slot_order_discrepancies():
    headers = rr.read_table(bytes(fake_rom()), rr.BASE+0x20)
    decoded = {"rom_sha1": "model", "tables": {"Day": headers, "Night": [], "Fallback": []}}
    areas = {"3:19": "route_1"}
    catalog = {"route_1": {"Day": [{"species_id": 288, "min_level": 2, "max_level": 4}]*12}}
    diff = rr.catalog_diff(decoded, areas, catalog)
    assert diff["mismatched_methods"] == 1
    assert diff["mismatches"][0]["rom_only"][0]["species_id"] == 1222
    assert diff["mismatches"][0]["catalog_only"][0]["species_id"] == 288
