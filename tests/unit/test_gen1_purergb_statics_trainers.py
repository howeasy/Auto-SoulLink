"""data/games/gen1_purergb/{static_encounters,trainers}.json contract.

Regenerate with `python tools/gen_gen1_statics.py --foundation purergb` /
`python tools/gen_gen1_trainers.py` (both need SLINK_PURERGB_SRC + built ROMs). The W2
byte-verified ROM offsets below are literal numbers by design (worker card rule: "addresses
symbolic via gen1_foundation; numbers only in asserts/tests") -- this file is where they live,
not the generator.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "games" / "gen1_purergb"


def _statics() -> dict:
    return json.loads((DATA / "static_encounters.json").read_text(encoding="utf-8"))


def _trainers() -> dict:
    return json.loads((DATA / "trainers.json").read_text(encoding="utf-8"))


def _purered_rom() -> bytes:
    src = os.environ.get("SLINK_PURERGB_SRC")
    if not src:
        pytest.skip("SLINK_PURERGB_SRC not set")
    roms = os.environ.get("SLINK_PURERGB_ROMS", src)
    path = Path(roms) / "pokered.gbc"
    if not path.is_file():
        pytest.skip(f"built pokered.gbc not found at {path}")
    return path.read_bytes()


# ── statics: W2's byte-verified oracle (docs/purergb/PLAN.md §11.2 W2) ──────────────────────

# (name, internal species id, level, species byte flat offset, level byte flat offset)
_W2_SCRIPT_STATICS = [
    ("snorlax_route12", 132, 40, 0x59654, 0x59659),
    ("snorlax_route16", 132, 40, 0x59A41, 0x59A46),
    ("missingno_rockethouse", 181, 120, 0x759D5, 0x759D0),  # level byte precedes species here
    ("ghost_marowak", 145, 30, 0x60A5B, 0x60A60),
    ("weedle_viridian", 112, 5, 0x190AD, 0x190A8),           # level byte precedes species here
    ("mewtwo", 131, 70, 0x46166, 0x4616B),
    ("zapdos_inline", 75, 50, 0x1AB63, 0x1AB68),
    ("articuno", 74, 50, 0x46923, 0x46928),
    ("moltres_volcano", 73, 50, 0x4B730, 0x4B735),
    ("magmar_volcano", 51, 45, 0x4B4BC, 0x4B4C1),
    ("cloyster", 139, 45, 0x4452E, 0x44533),
]

# (name, internal species id, level, species byte flat offset); level is the very next byte
# for these 8-byte `object_event` rows.
_W2_OBJECT_STATICS = [
    ("zapdos_floor_object", 75, 50, 0x1EDAE),
    ("moltres_victoryroad_object", 73, 50, 0x516C3),
    ("powerplant_voltorb1", 6, 40, 0x1ED6E),
    ("powerplant_voltorb2", 6, 40, 0x1ED76),
    ("powerplant_voltorb3", 6, 40, 0x1ED7E),
    ("powerplant_electrode1", 141, 43, 0x1ED86),
    ("powerplant_voltorb4", 6, 40, 0x1ED8E),
    ("powerplant_voltorb5", 6, 40, 0x1ED96),
    ("powerplant_electrode2", 141, 43, 0x1ED9E),
    ("powerplant_voltorb6", 6, 40, 0x1EDA6),
]


@pytest.mark.parametrize("name,species,level,species_off,level_off", _W2_SCRIPT_STATICS)
def test_w2_script_static_offsets_hold_in_the_rom(name, species, level, species_off, level_off):
    rom = _purered_rom()
    assert rom[species_off] == species, f"{name}: species byte at 0x{species_off:x}"
    assert rom[level_off] == level, f"{name}: level byte at 0x{level_off:x}"


@pytest.mark.parametrize("name,species,level,species_off", _W2_OBJECT_STATICS)
def test_w2_object_static_offsets_hold_in_the_rom(name, species, level, species_off):
    rom = _purered_rom()
    assert rom[species_off] == species, f"{name}: species byte at 0x{species_off:x}"
    assert rom[species_off + 1] == level, f"{name}: level byte at 0x{species_off + 1:x}"


def test_generator_records_match_the_w2_oracle():
    """Every W2 static (species, level) pair the generator claims to have found is present in
    its own output -- ties the ROM-offset oracle above to the generator's derived facts."""
    records = _statics()["records"]
    found = {(r["species"], r["level"]) for r in records}
    for name, species, level, *_ in _W2_SCRIPT_STATICS + _W2_OBJECT_STATICS:
        assert (species, level) in found, f"{name}: ({species}, {level}) missing from records"


def test_statics_exclude_tower_b1f_spirits_and_bills_garden():
    statics = _statics()["statics"]
    # POKEMON_TOWER_B1F (map 112) has no species write for its spirits -- no static at all.
    assert "112" not in statics
    # Bill's Garden's Pikachu is a wild capture (a water-table encounter), not a static.
    from tools.gen_gen1_area_map import parse_map_constants
    src = os.environ.get("SLINK_PURERGB_SRC")
    if src:
        _, name_to_id = parse_map_constants(
            (Path(src) / "constants" / "map_constants.asm").read_text(encoding="utf-8"))
        bills_garden_id = str(name_to_id["BILLS_GARDEN"])
        assert bills_garden_id not in statics


def test_statics_records_shape():
    for r in _statics()["records"]:
        assert set(r) >= {"map_id", "species", "level", "event_flag", "kind", "cite"}
        assert r["kind"] in ("script", "object_event")


# ── trainers ─────────────────────────────────────────────────────────────────────────────────

def test_56_classes_and_rival_ids():
    doc = _trainers()
    assert doc["num_trainers"] == 56
    assert len(doc["classes"]) == 56
    assert doc["opp_id_offset"] == 197
    assert doc["rival_ids"] == [221, 237, 238]
    assert set(doc["classes"]) == {str(197 + i) for i in range(1, 57)}


def test_rival_names_are_blank_by_design():
    doc = _trainers()
    for opp_id in (221, 237, 238):
        assert doc["classes"][str(opp_id)]["name"] is None


_S2_PARTY_COUNTS = [
    12, 15, 19, 7, 11, 24, 10, 10, 15, 15, 9, 5, 11, 15, 9, 9, 15, 6, 6, 10, 9, 17, 9, 9, 3, 14,
    4, 41, 10, 6, 3, 3, 3, 3, 3, 3, 3, 3, 7, 12, 9, 3, 24, 3, 3, 4, 7, 3, 2, 7, 6, 1, 2, 7, 7, 7,
]
_S2_KNOWN_DISCREPANCY = {5}  # JR_TRAINER_M: S2's raw digit array double-counts a debug branch


def test_class_counts_match_s2_array():
    doc = _trainers()
    for i, want in enumerate(_S2_PARTY_COUNTS, start=1):
        if i in _S2_KNOWN_DISCREPANCY:
            continue
        got = doc["classes"][str(197 + i)]["party_count"]
        assert got == want, f"class {i}: party_count {got} != S2's {want}"


def test_jr_trainer_m_debug_branch_is_not_double_counted():
    """The one documented S2 discrepancy: parties.asm wraps a single record in
    IF DEF(_DEBUG)/ELSE, which a naive db-line count over-counts by one."""
    doc = _trainers()
    assert doc["classes"][str(197 + 5)]["party_count"] == 10


def test_rookie_data_aliased_by_four_classes():
    doc = _trainers()
    rookie_classes = [c for c in doc["classes"].values() if c["data_label"] == "RookieData"]
    assert len(rookie_classes) == 4


def test_fe_and_fd_grammars_each_parse_at_least_one_record():
    doc = _trainers()
    seen = {"FE": False, "FD": False}
    for cls in doc["classes"].values():
        for grammar in seen:
            if grammar in cls["grammars"]:
                seen[grammar] = True
    assert seen["FE"], "no $FE (level|palette-bit) record found anywhere"
    assert seen["FD"], "no $FD (custom-moveset) record found anywhere"


def test_trainer_data_pointers_rom_cross_check():
    """Re-run the generator's own ROM check against the built pureRed ROM."""
    src = os.environ.get("SLINK_PURERGB_SRC")
    if not src:
        pytest.skip("SLINK_PURERGB_SRC not set")
    import sys
    sys.path.insert(0, str(ROOT))
    import tools.gen1_foundation as gf
    from tools.gen_gen1_trainers import _rom_check

    root = gf.source_root("purergb")
    problems = _rom_check(root)
    assert not problems, problems
