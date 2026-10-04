"""C-ROMTABLES: lua/gen2/rom.lua reads Polished Crystal's encounter tables through the generated profile
`layout` (tools/gen_polished_profile.py, docs/polished/ROMTABLES.md), and a profile without one is vanilla.

The truth is data/games/polished_crystal/encounter_tables.json, generated from the pinned source by
tools/gen_polished_pack.py (no Lua). Pack conventions the comparison maps, and nothing else:
  * the ROM `dp` form byte is NO_FORM (0) where the pack writes PLAIN_FORM (1);
  * a wild/fish level byte above MAX_LEVEL is LEVEL_FROM_BADGES +/- n: the pack writes level None plus
    level_raw/level_from_badges_offset, the reader omits level and gives the same two fields; tree packs
    keep the raw byte (175) in `level`, compared against the reader's level_raw;
  * probability rows: pack slot_index == reader slot_offset / 2.
The real release ROM is absent -> skip; present but not the pinned sha1 -> fail.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

REPO = Path(__file__).resolve().parents[2]
LUA = (REPO / "lua/gen2/rom.lua").read_text(encoding="utf-8")
PROFILE = json.loads((REPO / "data/games/polished_crystal/profile.json").read_text(encoding="utf-8"))["titles"]["polished"]
TRUTH = json.loads((REPO / "data/games/polished_crystal/encounter_tables.json").read_text(encoding="utf-8"))
ROM = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"


def native(v):
    if not hasattr(v, "keys"):
        return v
    keys = list(v.keys())
    if not keys:
        return []
    if all(isinstance(k, int) for k in keys):
        return [native(v[i]) for i in range(1, len(keys) + 1)]
    return {k: native(v[k]) for k in keys}


def reader(profile, image):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    mod = lua.execute(LUA)
    return mod.new(lua.table_from(profile, recursive=True), lua.table_from({"read_u8": lambda flat, _d: image[flat]}))


@pytest.fixture(scope="module")
def image():
    if not ROM.is_file():
        pytest.skip(f"Polished release ROM absent: {ROM}")
    data = ROM.read_bytes()
    assert hashlib.sha1(data).hexdigest() == PROFILE["rom_sha1"], "release ROM is not the pinned build"
    return data


def decode(image):
    r = reader(PROFILE, image)
    return {k: native(getattr(r, k)()) for k in ("wild", "tree", "fishing", "roamers", "contest")}


def compare(got, truth):
    """(counts, mismatches) of the reader's decode against the generated pack."""
    counts, bad = {}, []

    def same(where, a, b):
        if a != b:
            bad.append((where, a, b))

    def slot(where, mine, pack, tree=False):
        counts["slots"] = counts.get("slots", 0) + 1
        m, p = {"species": mine["species"]}, {"species": pack["species"]}
        if "form" in pack:
            m["form"], p["form"] = mine.get("form") or 1, pack["form"]  # NO_FORM 0 -> PLAIN_FORM 1
        if tree:
            m["level"], p["level"] = mine.get("level", mine.get("level_raw")), pack["level"]
        else:
            for k in ("level", "level_raw", "level_from_badges_offset"):
                m[k], p[k] = mine.get(k), pack.get(k)
        for k in ("threshold", "weight", "min_level", "max_level", "time_dependent"):
            m[k], p[k] = mine.get(k), pack.get(k)
        same(where, m, p)

    for kind in ("grass", "water"):
        mine, pack = got["wild"][kind], truth["wild"][kind]
        counts[f"wild_{kind}_rows"] = len(mine)
        same(f"wild.{kind}.rows", len(mine), len(pack))
        for i, (a, b) in enumerate(zip(mine, pack, strict=False)):
            same(f"wild.{kind}[{i}]", [a[k] for k in ("table", "map_group", "map_number", "time", "rate")],
                 [b[k] for k in ("table", "map_group", "map_number", "time", "rate")])
            same(f"wild.{kind}[{i}].n", len(a["slots"]), len(b["slots"]))
            for j, (s, t) in enumerate(zip(a["slots"], b["slots"], strict=False)):
                slot(f"wild.{kind}[{i}].slot{j}", s, t)
        same(f"wild.{kind}_probabilities",
             [(p["threshold"], p["slot_offset"] // 2) for p in got["wild"][f"{kind}_probabilities"]],
             [(p["threshold"], p["slot_index"]) for p in truth["wild"][f"{kind}_probabilities"]])
    for key in ("headbutt_maps", "rock_smash_maps"):
        same(f"tree.{key}", [(m["map_group"], m["map_number"], m["set_id"]) for m in got["tree"][key]],
             [(m["map_group"], m["map_number"], m["set_id"]) for m in truth["tree"][key]])
    counts["tree_sets"] = len(got["tree"]["sets"])
    same("tree.sets", len(got["tree"]["sets"]), len(truth["tree"]["sets"]))
    for a, b in zip(got["tree"]["sets"], truth["tree"]["sets"], strict=False):
        same(f"tree.set{b['set_id']}", (a["set_id"], a["kind"]), (b["set_id"], b["kind"]))
        for part in ("common", "rare"):
            same(f"tree.set{b['set_id']}.{part}.n", len(a[part]), len(b[part]))
            for j, (s, t) in enumerate(zip(a[part], b[part], strict=False)):
                slot(f"tree.set{b['set_id']}.{part}{j}", s, t, tree=True)
    counts["fish_groups"] = len(got["fishing"]["groups"])
    same("fishing.groups", len(got["fishing"]["groups"]), len(truth["fishing"]["groups"]))
    same("fishing.time_groups", got["fishing"]["time_groups"], truth["fishing"]["time_groups"])
    for a, b in zip(got["fishing"]["groups"], truth["fishing"]["groups"], strict=False):
        same(f"fishing.g{b['group_id']}", [a[k] for k in ("group_id", "bite_threshold", "bite_or_item_threshold")],
             [b[k] for k in ("group_id", "bite_threshold", "bite_or_item_threshold")])
        for rod in ("old", "good", "super"):
            same(f"fishing.g{b['group_id']}.{rod}.n", len(a[rod]), len(b[rod]))
            for j, (s, t) in enumerate(zip(a[rod], b[rod], strict=False)):
                slot(f"fishing.g{b['group_id']}.{rod}{j}", s, t)

    def roam(maps):
        return [(m["map_group"], m["map_number"], [(d["map_group"], d["map_number"]) for d in m["destinations"]])
                for m in maps]

    counts["roamer_maps"] = len(got["roamers"]["maps"])
    same("roamers.initial", got["roamers"]["initial"], truth["roamers"]["initial"])
    same("roamers.maps", roam(got["roamers"]["maps"]), roam(truth["roamers"]["maps"]))
    counts["contest_slots"] = len(got["contest"])
    same("contest.n", len(got["contest"]), len(truth["contest"]["slots"]))
    for j, (s, t) in enumerate(zip(got["contest"], truth["contest"]["slots"], strict=False)):
        slot(f"contest{j}", s, t)
    return counts, bad


def test_polished_tables_equal_the_generated_encounter_pack(image):
    counts, bad = compare(decode(image), TRUTH)
    assert bad == []
    assert counts == {"wild_grass_rows": 495, "wild_water_rows": 107, "tree_sets": 10, "fish_groups": 15,
                      "roamer_maps": 16, "contest_slots": 12, "slots": 4025}


def test_the_comparison_sees_one_changed_byte(image):
    # known-positive control: Sprout Tower 2F morning slot 0 is RATTATA (`03 13 00` at JohtoGrassWildMons+5)
    flat = PROFILE["rom"]["JohtoGrassWildMons"]["flat"] + 6
    assert image[flat] == 0x13
    changed = bytearray(image)
    changed[flat] = 0x14
    _, bad = compare(decode(changed), TRUTH)
    assert [where for where, _a, _b in bad] == ["wild.grass[0].slot0"]


def test_roamers_need_the_layout_inc_a_and_decode_raikou_entei(image):
    assert decode(image)["roamers"]["initial"] == [
        {"species": 243, "level": 40, "map_group": 2, "map_number": 5},
        {"species": 244, "level": 40, "map_group": 4, "map_number": 14}]
    profile = copy.deepcopy(PROFILE)
    profile["layout"]["roamer_inc_a"] = False
    with pytest.raises(lupa.LuaError, match="opcode 60"):
        reader(profile, image).roamers()


def test_polished_base_stats_read_plain_form_records(image):
    # BaseData 11:4b18: Bulbasaur `2d 31 31 2d 41 41`, Ivysaur `3c 3e` exactly 34 bytes on (no species byte)
    r = reader(PROFILE, image)
    bulbasaur, ivysaur = native(r.base_stats(1)), native(r.base_stats(2))
    assert [bulbasaur[k] for k in ("hp", "attack", "defense", "speed", "special_attack", "special_defense")] == \
        [45, 49, 49, 45, 65, 65]
    assert (ivysaur["hp"], ivysaur["attack"]) == (60, 62)
    assert len(bulbasaur["tmhm_bytes"]) == 14 and bulbasaur.get("hatch_cycles") is None


@pytest.mark.parametrize("edit,message", (
    (lambda p: p["derived"].__setitem__("base_stats_stride", 32), "geometry"),
    (lambda p: p["derived"].__setitem__("species_count", 289), "geometry"),
    (lambda p: p["layout"]["base_fields"].__setitem__("hp", 20), "base_fields.hp"),
    (lambda p: p.pop("layout"), "requires layout"),
))
def test_declared_geometry_must_agree(edit, message):
    """The removed `count == 251 and stride == 32` pin is now: derived (source) == layout (UPR ini), fields in
    the record before the TM/HM block. No ROM read happens before these refuse."""
    profile = copy.deepcopy(PROFILE)
    edit(profile)
    with pytest.raises(lupa.LuaError, match=message):
        reader(profile, b"")


def test_a_wrong_declared_row_length_refuses(image):
    profile = copy.deepcopy(PROFILE)
    profile["layout"]["wild_grass_row"] = 67
    with pytest.raises(lupa.LuaError, match="row length"):
        reader(profile, image).wild()


def test_an_explicit_vanilla_layout_equals_no_layout():
    """A layout carrying the vanilla defaults decodes the real Crystal ROM exactly like no layout at all."""
    lock = json.loads((REPO / "data/gen2_sources.lock.json").read_text())["outputs"]["pokecrystal"]
    path = REPO / ".cache/gen2-build" / lock["source"] / lock["filename"]
    if not path.is_file():
        pytest.skip(f"pokecrystal not cloned: {path.parent}")
    crystal = path.read_bytes()
    assert hashlib.sha1(crystal).hexdigest() == lock["sha1"]
    plain = json.loads((REPO / "data/games/gen2_crystal/profile.json").read_text())["titles"]["crystal"]
    explicit = copy.deepcopy(plain)
    explicit["layout"] = {"species_bytes": 1, "prob_width": 2, "fish_group_header": 7, "fish_group_base": 1,
                          "tree_first_set": 1, "species_count": 251, "base_stats_stride": 32,
                          "wild_regions": ["Johto", "Kanto", "Swarm"], "wild_grass_row": 47, "wild_water_row": 9}
    assert native(reader(explicit, crystal).scan_all()) == native(reader(plain, crystal).scan_all())
    with pytest.raises(lupa.LuaError, match="ContestMons"):
        reader(plain, crystal).contest()
