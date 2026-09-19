"""data/games/gen1_purergb/encounter_tables.json contract.

Regenerate with `python tools/gen_gen1_encounters.py --foundation purergb` (needs
SLINK_PURERGB_SRC + the built ROMs). The ROM-walk cross-check itself only runs when that env
var is set; everything else reads the committed JSON.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _pure_src() -> str:
    """The pinned checkout: $SLINK_PURERGB_SRC, else tools/gen1_foundation.py's default .cache/purergb."""
    src = os.environ.get("SLINK_PURERGB_SRC") or os.path.join(REPO, ".cache", "purergb")
    if not os.path.isdir(src):
        pytest.skip(f"pureRGB checkout not found at {src} (set SLINK_PURERGB_SRC)")
    return src

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "games" / "gen1_purergb"

_SLOT_CHANCES_256 = [51, 51, 39, 25, 25, 25, 13, 13, 11, 3]


def _encounters() -> dict:
    return json.loads((DATA / "encounter_tables.json").read_text(encoding="utf-8"))


def test_species_id_space_is_internal():
    assert _encounters()["species_id_space"] == "internal"


def test_all_three_titles_present():
    doc = _encounters()
    for title in ("purered", "pureblue", "puregreen"):
        assert title in doc and doc[title], title


def test_route_1_grass_matches_source():
    """Independent re-derivation of Route 1's grass table from the pinned source, cross-checked
    against the generated file -- the same source list `tools/gen_gen1_area_map.py` scans."""
    src = _pure_src()
    root = Path(src)
    text = (root / "data" / "wild" / "maps" / "Route1.asm").read_text(encoding="utf-8")
    grass = re.findall(r"^\s*db\s+(\d+)\s*,\s*([A-Z_0-9]+)\s*$", text, re.MULTILINE)
    # Route1.asm has one grass block and no water block, no IF DEF branches.
    by_species: dict[str, dict] = {}
    for level, sp in grass:
        level = int(level)
        by_species.setdefault(sp, {"min": level, "max": level, "slots": 0})
        by_species[sp]["min"] = min(by_species[sp]["min"], level)
        by_species[sp]["max"] = max(by_species[sp]["max"], level)
        by_species[sp]["slots"] += 1
    got = {e["name"].upper(): e for e in _encounters()["purered"]["route_1"]["Grass"]}
    assert set(got) == set(by_species), (set(got), set(by_species))
    for sp, expect in by_species.items():
        row = got[sp]
        assert row["min_level"] == expect["min"]
        assert row["max_level"] == expect["max"]
    assert sum(e["rate"] for e in _encounters()["purered"]["route_1"]["Grass"]) == 100


def test_old_rod_shape():
    """Random & 1, 50/50, both L10 (item_effects.asm ItemUseOldRod) -- Goldeen or Magikarp."""
    bills_garden_old_rod = _encounters()["purered"]["bills_garden"]["OldRod"]
    assert len(bills_garden_old_rod) == 2
    names = {e["name"] for e in bills_garden_old_rod}
    assert names == {"Goldeen", "Magikarp"}
    for e in bills_garden_old_rod:
        assert e["rate"] == 50
        assert e["min_level"] == e["max_level"] == 10


def test_good_rod_shape_fresh_vs_ocean():
    doc = _encounters()["purered"]
    fresh = doc["bills_garden"]["GoodRod"]  # not an OceanMaps member
    assert len(fresh) == 4
    assert {e["rate"] for e in fresh} == {25}
    ocean = doc["cinnabar_island"]["GoodRodOcean"]  # an OceanMaps member
    assert len(ocean) == 4
    assert {e["name"] for e in ocean} == {"Horsea", "Magikarp", "Shellder", "Tentacool"}


def test_super_rod_present_only_where_a_super_rod_data_row_exists():
    doc = _encounters()["purered"]
    assert "SuperRod" in doc["cinnabar_island"]
    assert "SuperRod" not in doc["power_plant"], "no SuperRodData row for Power Plant"


def test_slot_chances_256_are_source_asserted():
    src = _pure_src()
    text = (Path(src) / "data" / "wild" / "probabilities.asm").read_text(encoding="utf-8")
    for chance in _SLOT_CHANCES_256:
        assert f"wild_chance {chance}" in text.replace("  ", " ")


def test_rom_walk_zero_mismatches():
    """Re-run the generator's own build for one title and confirm it does not raise -- the
    build function itself asserts 0 ROM-vs-source mismatches or calls SystemExit."""
    _pure_src()  # skip when no checkout
    import sys
    sys.path.insert(0, str(ROOT))
    import tools.gen1_foundation as gf
    import tools.gen_gen1_area_map as area_map_gen
    from tools.gen_gen1_encounters import (
        build_purergb_title,
        parse_good_rod_pools,
        parse_map_id_list,
        parse_pokemon_constants,
        parse_super_rod_groups,
        parse_super_rod_rows,
    )

    root = gf.source_root("purergb")
    area_map = json.loads((DATA / "area_map.json").read_text(encoding="utf-8"))
    floor_labels = json.loads((DATA / "floor_labels.json").read_text(encoding="utf-8"))
    map_id_to_area = {int(k): v["area_id"] for k, v in area_map.items()}
    species_to_id = parse_pokemon_constants(str(root / "constants" / "pokemon_constants.asm"))
    _, name_to_map_id = area_map_gen.parse_map_constants(
        (root / "constants" / "map_constants.asm").read_text(encoding="utf-8"))
    ocean_ids = {name_to_map_id[n] for n in
                parse_map_id_list(gf.read_source("purergb", "data/maps/ocean_maps.asm"),
                                  "OceanMaps") if n in name_to_map_id}
    good_rod_pools = parse_good_rod_pools(gf.read_source("purergb", "data/wild/good_rod.asm"))
    super_rod_text = gf.read_source("purergb", "data/wild/super_rod.asm")
    super_rod_rows = parse_super_rod_rows(super_rod_text)
    super_rod_group_by_map = {name_to_map_id[m]: g for m, g in super_rod_rows
                              if m in name_to_map_id}
    super_rod_groups = parse_super_rod_groups(super_rod_text)

    areas = build_purergb_title("purered", root, species_to_id, {}, map_id_to_area,
                                floor_labels, ocean_ids, good_rod_pools,
                                super_rod_group_by_map, super_rod_groups)
    assert areas["route_1"]["Grass"]
