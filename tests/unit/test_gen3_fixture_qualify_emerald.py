"""Falsifiers for the Emerald additions to tools/gen3_fixtures.py (card E1-FIX, EF-10).

(a) the committed emerald_{town,battle,trainer}[_b].sav are the game's own re-save of the SYNTH
    seed, standing where each kind says, with a distinct OT on the _b side;
(b) the SYNTH seed itself (built from pret at test time) is a one-slot Emerald save that asks
    for the continue-game warp -- and emerald_fixture_problems refuses it for exactly that;
(c) every tile, map id, layout id and starter fact the tool hardcodes is re-derived from the
    pret pokeemerald checkout (skipped when the cache is absent).
"""

import json
import os
import re
import struct
import sys

import pytest

from server.adapters import gen3_codec as codec

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen3_fixtures as fx  # noqa: E402  (tools/ is not a package)

FIXTURES_DIR = os.path.join(REPO, "tests", "fixtures", "gen3")
EM = codec.TITLE_EMERALD


def _pret():
    try:
        return fx.pret_emerald()
    except FileNotFoundError:
        pytest.skip("pret pokeemerald checkout absent")


def _read(name):
    path = os.path.join(FIXTURES_DIR, name)
    if not os.path.exists(path):
        pytest.skip(f"{name} not built")
    with open(path, "rb") as f:
        return f.read()


# --- (a) committed fixtures ---------------------------------------------------

@pytest.mark.parametrize("kind", sorted(fx.EMERALD_KINDS))
@pytest.mark.parametrize("suffix", ["", "_b"])
def test_committed_emerald_fixture_is_a_game_resave_on_its_tile(kind, suffix):
    body = _read(f"emerald_{kind}{suffix}.sav")
    assert len(body) == codec.FLASH_SIZE
    assert fx.emerald_fixture_problems(body, kind) == []
    r = fx.qualify_one(body, rr=False, title=EM)
    assert r["ok"] and r["counter"] == 2 and len(r["party"]) == 1


@pytest.mark.parametrize("kind", sorted(fx.EMERALD_KINDS))
def test_emerald_b_side_has_a_distinct_trainer_at_the_same_place(kind):
    a, b = _read(f"emerald_{kind}.sav"), _read(f"emerald_{kind}_b.sav")
    ra, rb = (fx.qualify_one(x, rr=False, title=EM) for x in (a, b))
    assert (ra["trainer_name"], rb["trainer_name"]) == ("EMER", "EMERB")
    assert rb["trainer_id"] == ra["trainer_id"] ^ 0xFFFFFFFF
    (ma,), (mb,) = (codec.party_from_save(x, title=EM) for x in (a, b))
    assert (ma["ot_id"], mb["ot_id"]) == (ra["trainer_id"], rb["trainer_id"])
    assert {k: ma[k] for k in ("species", "level", "hp", "personality")} == \
        {k: mb[k] for k in ("species", "level", "hp", "personality")}
    sb1a, sb1b = (codec.parse_flash(x, title=EM)["sb1"] for x in (a, b))
    assert sb1a[:0x34] == sb1b[:0x34]          # pos, warps, map layout: untouched by derive-b


def test_emerald_party_is_invisible_to_the_frlg_layout():
    """The title switch is load-bearing: at FR/LG's +0x34/+0x38 the Emerald save holds
    mapView, not the party."""
    body = _read("emerald_town.sav")
    frlg = [m["species"] for m in codec.party_from_save(body)]
    assert frlg != [fx.MUDKIP["species"]]
    assert [m["species"] for m in codec.party_from_save(body, title=EM)] == [fx.MUDKIP["species"]]


def test_derive_b_emerald_rekeys_the_party_at_the_emerald_offset():
    b_body, manifest = fx.derive_b(_read("emerald_town.sav"), title=EM)
    assert any(line.startswith("sb1+0x0238") and "party[0]" in line for line in manifest)
    assert codec.qualify_flash(b_body, title=EM) == (True, "ok")


# --- (b) the SYNTH seed -------------------------------------------------------

@pytest.mark.parametrize("kind", sorted(fx.EMERALD_KINDS))
def test_seed_is_one_slot_asking_for_the_continue_warp(kind):
    seed = fx.build_emerald_seed(kind, fx.emerald_new_game_flags(_pret()))
    r = fx.qualify_one(seed, rr=False, title=EM)
    assert r["ok"] and (r["slot"], r["counter"]) == (1, fx.EMERALD_SEED_COUNTER)
    assert seed[:codec.NUM_SECTORS_PER_SLOT * codec.SECTOR_SIZE] == \
        b"\xFF" * (codec.NUM_SECTORS_PER_SLOT * codec.SECTOR_SIZE)     # slot 0 erased
    # the one thing that separates the seed from a game re-save
    assert fx.emerald_fixture_problems(seed, kind) == [
        "specialSaveWarpFlags still has CONTINUE_GAME_WARP: not a game re-save"]
    sb1 = codec.parse_flash(seed, title=EM)["sb1"]
    assert struct.unpack_from("<bbbxhh", sb1, 0x0C) == struct.unpack_from("<bbbxhh", sb1, 0x04)
    (mon,) = codec.party_from_save(seed, title=EM)
    assert (mon["hp"], mon["max_hp"], mon["attack"], mon["defense"], mon["speed"],
            mon["sp_attack"], mon["sp_defense"], mon["experience"]) == (20, 20, 12, 10, 9, 10, 10, 135)
    assert mon["personality"] % 25 == 0 and (mon["personality"] & 0xFF) >= 31   # Hardy, male


def test_seed_flags_include_the_story_flags_and_the_new_game_map_flags():
    pret = _pret()
    flags = set(fx.emerald_new_game_flags(pret))
    # flags.h:136 FLAG_ADVENTURE_STARTED 0x74; :1348-1350 SYSTEM_FLAGS 0x860 = FLAG_SYS_POKEMON_GET
    assert {0x74, 0x860, 0x870} <= flags
    assert fx.pret_flag_ids(pret, ["FLAG_HIDE_ROUTE_103_RIVAL"]) == [0x2D3]
    assert len(flags) > 100


# --- (c) pret re-derivation of the hardcoded facts -----------------------------

def _behaviour_names(pret):
    text = (pret / "include/constants/metatile_behaviors.h").read_text(encoding="utf-8")
    return re.findall(r"^\s+(MB_\w+)", text, re.M)


def _tile(pret, map_dir, x, y):
    """(collision, behaviour name) of one map tile, from map.bin + both tilesets' attributes."""
    layout_id = json.loads((pret / f"data/maps/{map_dir}/map.json").read_text())["layout"]
    layout = next(entry for entry in json.loads((pret / "data/layouts/layouts.json").read_text())
                  ["layouts"] if entry.get("id") == layout_id)
    block = (pret / layout["blockdata_filepath"]).read_bytes()
    v = int.from_bytes(block[(y * layout["width"] + x) * 2:][:2], "little")
    metatile, collision = v & 0x3FF, (v >> 10) & 3
    kind, tileset = ("primary", layout["primary_tileset"]) if metatile < 512 else \
        ("secondary", layout["secondary_tileset"])
    attrs = (pret / f"data/tilesets/{kind}/{tileset[len('gTileset_'):].lower()}"
             / "metatile_attributes.bin").read_bytes()
    at = (metatile % 512) * 2
    return collision, _behaviour_names(pret)[int.from_bytes(attrs[at:at + 2], "little") & 0xFF]


@pytest.mark.parametrize("kind", sorted(fx.EMERALD_KINDS))
def test_kind_map_ids_come_from_pret(kind):
    pret = _pret()
    map_dir, group, num, layout_id, _x, _y = fx.EMERALD_KINDS[kind]
    groups = json.loads((pret / "data/maps/map_groups.json").read_text())
    name = groups[groups["group_order"][group]][num]
    assert name == map_dir
    layouts = json.loads((pret / "data/layouts/layouts.json").read_text())["layouts"]
    assert layouts[layout_id - 1]["id"] == \
        json.loads((pret / f"data/maps/{map_dir}/map.json").read_text())["layout"]


def test_town_tile_is_oldales_heal_location_below_the_center_door():
    pret = _pret()
    _m, group, num, _l, x, y = fx.EMERALD_KINDS["town"]
    heal = next(h for h in json.loads((pret / "src/data/heal_locations.json").read_text())
                ["heal_locations"] if h["id"] == "HEAL_LOCATION_OLDALE_TOWN")
    assert (heal["map"], heal["x"], heal["y"]) == ("MAP_OLDALE_TOWN", x, y)
    assert (group, num, x, y) == fx.EMERALD_HEAL
    oldale = json.loads((pret / "data/maps/OldaleTown/map.json").read_text())
    assert {"x": x, "y": y - 1, "dest_map": "MAP_OLDALE_TOWN_POKEMON_CENTER_1F"}.items() <= \
        next(w for w in oldale["warp_events"] if w["dest_map"].endswith("POKEMON_CENTER_1F")).items()
    assert _tile(pret, "OldaleTown", x, y) == (0, "MB_NORMAL")
    assert "MAP_OLDALE_TOWN" not in (pret / "src/data/wild_encounters.json").read_text()


def test_battle_tile_is_tall_grass():
    pret = _pret()
    map_dir, *_ids, x, y = fx.EMERALD_KINDS["battle"]
    assert _tile(pret, map_dir, x, y) == (0, "MB_TALL_GRASS")


def test_trainer_tile_is_one_right_step_from_calvins_sight_line():
    pret = _pret()
    map_dir, *_ids, x, y = fx.EMERALD_KINDS["trainer"]
    route = json.loads((pret / f"data/maps/{map_dir}/map.json").read_text())
    calvin = next(o for o in route["object_events"] if o["script"] == "Route102_EventScript_Calvin")
    assert calvin["movement_type"] == "MOVEMENT_TYPE_FACE_DOWN"
    sight = int(calvin["trainer_sight_or_berry_tree_id"])
    assert calvin["x"] == x + 1 and calvin["y"] < y <= calvin["y"] + sight
    assert _tile(pret, map_dir, x, y) == (0, "MB_NORMAL")
    for yy in range(calvin["y"] + 1, y + 1):          # the path Calvin walks to the player
        assert _tile(pret, map_dir, x + 1, yy)[0] == 0


def test_mudkip_facts_come_from_pret():
    pret = _pret()
    species = (pret / "include/constants/species.h").read_text()
    assert re.search(r"#define SPECIES_MUDKIP (\d+)", species).group(1) == str(fx.MUDKIP["species"])
    info = (pret / "src/data/pokemon/species_info.h").read_text()
    block = info.split("[SPECIES_MUDKIP] =", 1)[1].split("\n    },", 1)[0]
    base = {k: int(re.search(rf"\.base{k}\s*=\s*(\d+)", block).group(1))
            for k in ("HP", "Attack", "Defense", "Speed", "SpAttack", "SpDefense")}
    assert list(base.values()) == list(fx.MUDKIP["base"].values())
    assert "PERCENT_FEMALE(12.5)" in block and "STANDARD_FRIENDSHIP" in block
    assert "GROWTH_MEDIUM_SLOW" in block
    learn = (pret / "src/data/pokemon/level_up_learnsets.h").read_text()
    lv1 = re.findall(r"LEVEL_UP_MOVE\( 1, (MOVE_\w+)\)",
                     learn.split("sMudkipLevelUpLearnset[] = {", 1)[1].split("}", 1)[0])
    assert lv1 == ["MOVE_TACKLE", "MOVE_GROWL"]
    moves = (pret / "src/data/battle_moves.h").read_text()
    for move, pp in (("MOVE_TACKLE", 35), ("MOVE_GROWL", 40)):
        assert f".pp = {pp}," in moves.split(f"[{move}] =", 1)[1].split("},", 1)[0]
