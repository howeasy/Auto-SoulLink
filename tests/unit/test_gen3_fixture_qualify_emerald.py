"""Falsifiers for the Emerald additions to tools/gen3_fixtures.py (card E1-FIX, EF-10).

(a) the committed emerald_{town,battle,trainer}[_b].sav are the game's own re-save of the SYNTH
    seed, standing where each kind says, with a distinct OT on the _b side;
(b) the SYNTH seed itself (built from pret at test time) is a one-slot Emerald save that asks
    for the continue-game warp -- and emerald_fixture_problems refuses it for exactly that;
(c) every tile, map id, layout id and starter fact the tool hardcodes is re-derived from the
    pret pokeemerald checkout (skipped when the cache is absent);
(d) card E1-FIX-2: the seed and the six fixtures are pinned by sha256, the ball pocket holds
    the SYNTH Poke Balls through the game's re-key, and boot-check --title emerald refuses --rr
    and runs emerald_fixture_problems on the flushed save.
"""

import hashlib
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

# build_emerald_seed(kind, emerald_new_game_flags(pret)) at pokeemerald c65e93f2 (card E1-FIX-2,
# with the ball pocket); make-emerald prints the same digest as "SYNTH seed <kind>: ... sha256=".
# the one-Mudkip kinds; pc/lowhp (E2-FIX-VARIANTS) have their own tests in
# test_gen3_emerald_fixture_qualify.py
ONE_MUDKIP = ("battle", "town", "trainer")

SEED_SHA256 = {
    "battle": "6ad42abbfd481978b237a4f2d3bc92eb4fb1dfdf97eba74572e7b4b0dfcc35a9",
    "town": "816d33b8e856ccb8fcf84b45f799495a6cfb00d77677ce7ce152cfbe21e7aca5",
    "trainer": "f6f301bc99c778e35aebef796093465d178397893430ae99063e4c07326f596e",
}
# The committed fixtures, as tests/fixtures/gen3/README.md publishes them.
FIXTURE_SHA256 = {
    "emerald_town.sav": "f447ce7aaf87cf81e1cdd0bf13bd81cad615214abaf335fc9d91a4dede38f80a",
    "emerald_town_b.sav": "17a34da61d32eb9c9e4fb5f8b6bd881245b5afa3213b369ebb71ac808f1043ec",
    "emerald_battle.sav": "4080d499a0ca51a6c593be5062f5a8aa74014acffadee33541985bfa617c1b5f",
    "emerald_battle_b.sav": "61cefb43740759b677d886752a0ab46c67e25798f2666f5dde5c615fc4fc4b50",
    "emerald_trainer.sav": "1fe754336ddba75b2a1cb77b7864d2eae7137e8d7412bf55724f7db4cb1593e6",
    "emerald_trainer_b.sav": "ca108972081f3c01000d34822adccdbb02cec9e436a8fc31091ab8c450b40fb6",
    "emerald_pc.sav": "c76e4438a66fd19168ccff5fa3e9eb05e9267d5a11ca0fb8e12ae19e1a0169ab",
    "emerald_lowhp.sav": "c57422d3fbb8732f5fea8d2bd3275a5bc2edf58563edab669550afbff7cea07b",
    "emerald_badges.sav": "04d4c5dddd8f8aeef14982a34a654936fe5fb8f1a517d529c483991de803ca4f",
    "emerald_evolve.sav": "244763cb77a8b230ff863daed4bd63a2a8e80103f419a04f13a7ba372b390dbd",
    "emerald_poison.sav": "c20c6edd9ca888ab5cd7eaa57b5a8b3b441255e4315ca1cd200c52e222baa9f0",
    "emerald_gift.sav": "7a6a712d87e339794a2a29735e1f320a3e55e6d06961180a3d41d687aa86d552",
    "emerald_catch.sav": "592d9986b28e24f9c4ad01873969a4e3ec0fb2f36f336f9e824f40ec78277fb0",
}


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
    assert r["ok"] and r["counter"] == 2 and len(r["party"]) == (2 if kind in ("pc", "poison") else 1)


@pytest.mark.parametrize("kind", sorted(fx.EMERALD_KINDS))
def test_emerald_b_side_has_a_distinct_trainer_at_the_same_place(kind):
    a, b = _read(f"emerald_{kind}.sav"), _read(f"emerald_{kind}_b.sav")
    ra, rb = (fx.qualify_one(x, rr=False, title=EM) for x in (a, b))
    assert (ra["trainer_name"], rb["trainer_name"]) == ("EMER", "EMERB")
    assert rb["trainer_id"] == ra["trainer_id"] ^ 0xFFFFFFFF
    ma, mb = (codec.party_from_save(x, title=EM)[0] for x in (a, b))   # lead; pc/poison hold two
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

@pytest.mark.parametrize("kind", ONE_MUDKIP)
def test_seed_is_one_slot_asking_for_the_continue_warp(kind):
    seed = fx.build_emerald_seed(kind, fx.emerald_new_game_flags(_pret()))
    r = fx.qualify_one(seed, rr=False, title=EM)
    assert fx.EMERALD_SEED_COUNTER == 1
    assert r["ok"] and (r["slot"], r["counter"]) == (1, 1)
    assert seed[:codec.NUM_SECTORS_PER_SLOT * codec.SECTOR_SIZE] == \
        b"\xFF" * (codec.NUM_SECTORS_PER_SLOT * codec.SECTOR_SIZE)     # slot 0 erased
    # the one thing that separates the seed from a game re-save
    assert fx.emerald_fixture_problems(seed, kind) == [
        "specialSaveWarpFlags still has CONTINUE_GAME_WARP: not a game re-save"]
    sb1 = codec.parse_flash(seed, title=EM)["sb1"]
    _m, group, num, _l, x, y = fx.EMERALD_KINDS[kind]       # pret-checked by section (c)
    warp_id_none = _define(_pret(), "include/constants/maps.h", "WARP_ID_NONE")
    assert struct.unpack_from("<hh", sb1, 0x00) == (x, y)                              # pos
    for at in (0x04, 0x0C):                                  # location, continueGameWarp
        assert struct.unpack_from("<bbbxhh", sb1, at) == (group, num, warp_id_none, x, y)
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


# --- (d) card E1-FIX-2 ------------------------------------------------------------

def _define(pret, rel, name):
    """The integer a `#define NAME value` line in pret `rel` gives (parenthesised or not)."""
    text = (pret / rel).read_text(encoding="utf-8")
    return int(re.search(rf"^#define {name}\s+\(?(-?\w+)\)?", text, re.M).group(1), 0)


@pytest.mark.parametrize("kind", ONE_MUDKIP)
def test_seed_reproduces_its_recorded_sha256(kind):
    seed = fx.build_emerald_seed(kind, fx.emerald_new_game_flags(_pret()))
    assert hashlib.sha256(seed).hexdigest() == SEED_SHA256[kind]


def test_committed_fixture_sha256s_are_the_ones_the_readme_publishes():
    with open(os.path.join(FIXTURES_DIR, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    published = dict(re.findall(r"^\| `(emerald_\w+\.sav)` \|.*`([0-9a-f]{64})` \|$", readme, re.M))
    assert published == FIXTURE_SHA256
    for name, digest in FIXTURE_SHA256.items():
        assert hashlib.sha256(_read(name)).hexdigest() == digest, name


def test_starter_and_seed_constants_come_from_pret():
    pret = _pret()
    moves = [_define(pret, "include/constants/moves.h", m) for m in ("MOVE_TACKLE", "MOVE_GROWL")]
    assert fx.MUDKIP["moves"] == [*moves, 0, 0]
    table = (pret / "src/data/battle_moves.h").read_text(encoding="utf-8")
    pp = [int(re.search(r"\.pp = (\d+),", table.split(f"[{m}] =", 1)[1]).group(1))
          for m in ("MOVE_TACKLE", "MOVE_GROWL")]
    assert fx.MUDKIP["pp"] == [*pp, 0, 0]
    assert fx.MUDKIP["friendship"] == _define(pret, "include/constants/pokemon.h",
                                               "STANDARD_FRIENDSHIP")
    # species_info.h:3 PERCENT_FEMALE(percent) min(254, ((percent * 255) / 100)), stored in a u8
    assert fx.MUDKIP["gender_ratio"] == min(254, int(12.5 * 255 / 100))
    sections = json.loads((pret / "src/data/region_map/region_map_sections.json").read_text())
    assert [m["id"] for m in sections["map_sections"]].index("MAPSEC_ROUTE_101") == \
        fx.MAPSEC_ROUTE_101
    assert _define(pret, "include/constants/global.h", "VERSION_EMERALD") == fx.VERSION_EMERALD
    assert _define(pret, "include/constants/global.h", "LANGUAGE_ENGLISH") == fx.LANGUAGE_ENGLISH
    assert _define(pret, "include/constants/items.h", "ITEM_POKE_BALL") == fx.ITEM_POKE_BALL
    name, tid = fx.EMERALD_OT          # SYNTH identity: only its shape is pret's
    assert len(name) <= _define(pret, "include/constants/global.h", "PLAYER_NAME_LENGTH")
    assert 0 <= tid <= 0xFFFFFFFF
    new_game = (pret / "src/new_game.c").read_text(encoding="utf-8")
    assert int(re.search(r"SetMoney\(&gSaveBlock1Ptr->money, (\d+)\)", new_game).group(1)) == \
        fx.EMERALD_MONEY
    global_h = (pret / "include/global.h").read_text(encoding="utf-8")
    assert re.search(r"/\*0x(\w+)\*/ struct ItemSlot bagPocket_PokeBalls\[BAG_POKEBALLS_COUNT\];",
                     global_h).group(1) == f"{fx.SB1_BALL_POCKET_EMERALD:X}"
    assert re.search(r"/\*0x(\w+)\*/ u32 encryptionKey;", global_h).group(1) == \
        f"{fx.SB2_ENCRYPTION_KEY:X}"
    assert _define(pret, "include/constants/global.h",
                                           "BAG_POKEBALLS_COUNT") == fx.BALL_POCKET_SLOTS
    # the quantity rule emerald_ball_pocket applies (src/item.c:26-29)
    assert "return gSaveBlock2Ptr->encryptionKey ^ *quantity;" in \
        (pret / "src/item.c").read_text(encoding="utf-8")


def test_the_seed_carries_the_pret_facts():
    pret = _pret()
    seed = fx.build_emerald_seed("town", fx.emerald_new_game_flags(pret))
    (mon,) = codec.party_from_save(seed, title=EM)
    assert (mon["moves"], mon["pp"], mon["friendship"], mon["met_location"], mon["met_game"],
            mon["language"], mon["pokeball"]) == \
        ([33, 45, 0, 0], [35, 40, 0, 0], 70, 16, 3, 2, 4)
    sb1 = codec.parse_flash(seed, title=EM)["sb1"]
    assert struct.unpack_from("<I", sb1, 0x490)[0] == 3000
    assert fx.emerald_ball_pocket(seed) == [(4, 5)]          # ITEM_POKE_BALL x EMERALD_BALLS


def test_story_flag_ids_come_from_pret_and_are_set_in_the_seed():
    pret = _pret()
    flags_h = (pret / "include/constants/flags.h").read_text(encoding="utf-8")
    for name in fx.EMERALD_STORY_FLAGS:
        assert re.search(rf"^#define {name}\s", flags_h, re.M), name
    ids = fx.pret_flag_ids(pret, fx.EMERALD_STORY_FLAGS)
    # flags.h:1350 (0x860), :136, :154, :1371 (SYSTEM_FLAGS + 0x10), :1030, :772
    assert ids == [0x860, 0x74, 0x84, 0x870, 0x3D3, 0x2D3]
    sb1 = codec.parse_flash(fx.build_emerald_seed("town", fx.emerald_new_game_flags(pret)),
                            title=EM)["sb1"]
    assert all(sb1[0x1270 + f // 8] >> (f % 8) & 1 for f in ids)


@pytest.mark.parametrize("kind", sorted(fx.EMERALD_KINDS))
def test_committed_fixture_ball_pocket_survives_the_games_rekey(kind):
    body = _read(f"emerald_{kind}.sav")
    key = struct.unpack_from("<I", codec.parse_flash(body, title=EM)["sb2"], 0xAC)[0]
    assert key & 0xFFFF   # the re-save carries the key CONTINUE rolled (load_save.c:127-131)
    want = fx.EMERALD_CATCH_BALLS if kind == "catch" else fx.EMERALD_BALLS
    assert fx.emerald_ball_pocket(body) == [(fx.ITEM_POKE_BALL, want)]


def test_emerald_fixture_problems_refuses_an_empty_ball_pocket():
    seed = bytearray(fx.build_emerald_seed("town", fx.emerald_new_game_flags(_pret())))
    layout = codec.slot_layout(title=EM)
    sb1 = bytearray(codec.parse_flash(bytes(seed), title=EM)["sb1"])
    sb1[fx.SB1_BALL_POCKET_EMERALD:fx.SB1_BALL_POCKET_EMERALD + 4] = bytes(4)
    for entry in (e for e in layout if e["object"] == "sb1"):
        at = (codec.NUM_SECTORS_PER_SLOT + entry["id"]) * codec.SECTOR_SIZE
        seed[at:at + codec.SECTOR_SIZE] = codec.write_sector(
            bytes(sb1[entry["offset"]:entry["offset"] + entry["size"]]), entry["id"], 1, layout)
    problems = fx.emerald_fixture_problems(bytes(seed), "town")
    assert "ball pocket [] != [(ITEM_POKE_BALL, 5)]" in problems


def test_boot_check_title_choices_and_emerald_refuses_rr(capsys):
    parse = fx.build_parser().parse_args
    base = ["boot-check", "--rom", "r.gba", "--fixture", "does/not/exist.sav"]
    for title in ("firered", "leafgreen", "radical_red", "emerald"):
        assert parse([*base, "--title", title]).title == title
    with pytest.raises(SystemExit):
        parse([*base, "--title", "sapphire"])
    args = parse([*base, "--title", "emerald", "--rr"])
    assert args.func(args) == 2          # refused before the fixture is even read
    assert "--title emerald with --rr" in capsys.readouterr().err


def test_emerald_kind_of_names():
    kind_of = fx.emerald_kind_of
    assert [kind_of(fx.Path(f"x/emerald_{n}.sav")) for n in ("town", "battle_b", "trainer")] == \
        ["town", "battle", "trainer"]
    assert kind_of(fx.Path("emerald_route.sav")) is None
    assert kind_of(fx.Path("firered_town.sav")) is None


def _boot_check_on(monkeypatch, tmp_path, fixture_name, flushed_body):
    """cmd_boot_check with the emulator stubbed: the run 'flushes' `flushed_body`."""
    fixture = tmp_path / fixture_name
    fixture.write_bytes(_read("emerald_town.sav"))
    flushed = tmp_path / "flushed.SaveRAM"
    flushed.write_bytes(flushed_body)
    monkeypatch.setattr(fx, "_prepare_run", lambda *a, **k: ("r.gba", tmp_path, flushed.name))
    monkeypatch.setattr(fx, "_launch", lambda *a, **k: (True, "stub"))
    monkeypatch.setattr(fx, "boot_check_verdict", lambda before, after: (True, []))
    args = fx.build_parser().parse_args(["boot-check", "--rom", "r.gba", "--fixture",
                                         str(fixture), "--title", "emerald"])
    return args.func(args)


def test_boot_check_emerald_runs_the_fixture_problems(monkeypatch, tmp_path, capsys):
    seed = fx.build_emerald_seed("town", fx.emerald_new_game_flags(_pret()))
    assert _boot_check_on(monkeypatch, tmp_path, "emerald_town.sav", seed) == 1
    out = capsys.readouterr()
    assert "emerald_fixture_problems(town): 1 problem(s)" in out.out
    assert "CONTINUE_GAME_WARP" in out.err


def test_boot_check_emerald_says_when_it_could_not_run_them(monkeypatch, tmp_path, capsys):
    seed = fx.build_emerald_seed("town", fx.emerald_new_game_flags(_pret()))
    assert _boot_check_on(monkeypatch, tmp_path, "mystery.sav", seed) == 0
    assert "emerald_fixture_problems NOT run" in capsys.readouterr().out

# --- (d) E2-BADGES (OMP cx-b47da8b1 F2-F4) ------------------------------------

def _badge_window(sb1: bytes) -> int:
    """Badges 1-8 as bits 0-7, read the way reads.lua does (one flag id per badge)."""
    return sum(((sb1[0x1270 + f // 8] >> (f % 8)) & 1) << i for i, f in enumerate(range(0x867, 0x86F)))


def test_badges_seed_sets_exactly_badges_1_to_4():
    seed = fx.build_emerald_seed("badges", fx.emerald_new_game_flags(_pret()))
    sb1 = codec.parse_flash(seed, title=EM)["sb1"]
    assert _badge_window(sb1) == 0b1111
    assert fx.emerald_fixture_problems(seed, "badges") == [
        "specialSaveWarpFlags still has CONTINUE_GAME_WARP: not a game re-save"]
    town = codec.parse_flash(fx.build_emerald_seed("town", fx.emerald_new_game_flags(_pret())),
                             title=EM)["sb1"]
    assert _badge_window(town) == 0          # the badge window is the seed's only difference
    assert town[:0x1270 + 0x10C] == sb1[:0x1270 + 0x10C]


def test_badges_fixture_carries_badges_1_to_4_and_5_to_8_clear():
    sb1 = codec.parse_flash(_read("emerald_badges.sav"), title=EM)["sb1"]
    assert _badge_window(sb1) == 0b1111


def test_tool_badge_constants_are_the_profile_fields_the_client_reads():
    with open(os.path.join(REPO, "data/games/gen3_emerald/profile.json"), encoding="utf-8") as f:
        derived = json.load(f)["titles"]["emerald"]["derived"]
    first = derived["BADGE_FIRST_FLAG"]
    assert tuple(range(first, first + 4)) == fx.EMERALD_BADGE_FLAGS
    assert derived["SB1_FLAGS_OFFSET"] == 0x1270   # the tool writes flags at SB1 + 0x1270
