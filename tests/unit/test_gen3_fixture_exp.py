"""X3 fixtures for the pokeemerald-expansion reference build (ROM 28877d73).

tools/gen3_fixtures.py make-exp transplants the committed Emerald SYNTH seed (same maps, same
story flags at the pin) into the build's own save layout and record lanes; the game's own
CONTINUE -> in-game SAVE then writes the fixture. Every claim here is re-derived from the
build's data pack/facts or the expansion source at the pin (SLINK_EXPANSION_SRC), never from
the Emerald values it replaces.
"""
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen3_fixtures as fx  # noqa: E402

from server.adapters import gen3_codec as C  # noqa: E402
from server.adapters.gen3_expansion import EXPANSION_PARTY_LAYOUT  # noqa: E402

T = C.TITLE_EXPANSION
DATA = json.loads((ROOT / "data/games/gen3_exp/28877d73/data.json").read_text(encoding="utf-8"))
SPECIES = {row["id"]: row for row in DATA["species"]}
FIXTURES = ROOT / "tests/fixtures/gen3"


def _src():
    """The expansion checkout at the pin, or skip (absent skips; a wrong checkout fails)."""
    src = Path(os.environ.get("SLINK_EXPANSION_SRC", ROOT / ".cache/expansion-src"))
    if not src.exists():
        pytest.skip("expansion source absent")
    assert (src / "include/global.h").is_file(), "present expansion source lacks include/global.h"
    lock = json.loads((ROOT / "data/gen3_exp_sources.lock.json").read_text(encoding="utf-8"))
    head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    assert head == lock["source"]["commit"], "SLINK_EXPANSION_SRC is not the pinned commit"
    return Path(src)


@pytest.fixture(scope="module")
def context():
    from tools import gen_gen3_profile as profile

    artifacts = Path(os.environ.get("SLINK_EXPANSION_ARTIFACTS", ROOT / ".cache/expansion-output/reference"))
    for name in ("pokeemerald.gba", "pokeemerald.sym", "pokeemerald.map"):
        if not (artifacts / name).is_file():
            pytest.skip(f"local copyrighted ROMs absent: {artifacts / name}")
    src = _src()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SLINK_EXPANSION_SRC", str(src))
        patch.setenv("SLINK_EXPANSION_ARTIFACTS", str(artifacts))
        patch.setattr(fx, "EXP_ARTIFACTS", artifacts)
        yield profile.expansion_inputs(artifacts=artifacts)


def _seed(kind):
    return fx.build_exp_seed(kind, fx.emerald_new_game_flags(_src()))


@pytest.mark.parametrize("kind", sorted(fx.EXP_KINDS))
def test_exp_kind_map_ids_come_from_the_expansion_source(kind):
    src = _src()
    map_dir, group, num, layout_id, _x, _y = fx.EXP_KINDS[kind]
    groups = json.loads((src / "data/maps/map_groups.json").read_text())
    assert groups[groups["group_order"][group]][num] == map_dir
    layouts = json.loads((src / "data/layouts/layouts.json").read_text())["layouts"]
    assert layouts[layout_id - 1]["id"] == json.loads((src / f"data/maps/{map_dir}/map.json").read_text())["layout"]


def test_new_game_flags_at_the_pin_equal_the_emerald_seeds():
    assert fx.emerald_new_game_flags(_src()) == fx.emerald_new_game_flags(fx.pret_emerald())


def test_rock_fixture_native_layout_tracks_the_source_mirage_tower_switch():
    import re

    src = _src()
    flags = (src / "include/constants/flags.h").read_text()
    match = re.search(r"^#define\s+FLAG_MIRAGE_TOWER_VISIBLE\s+(0x[0-9A-Fa-f]+|\d+)", flags, re.M)
    assert int(match[1], 0) == fx.EXP_MIRAGE_TOWER_VISIBLE_FLAG
    layouts = json.loads((src / "data/layouts/layouts.json").read_text())["layouts"]
    assert layouts[fx.EXP_ROUTE111_NO_TOWER_LAYOUT - 1]["id"] == "LAYOUT_ROUTE111_NO_MIRAGE_TOWER"
    script = (src / "data/maps/Route111/scripts.inc").read_text()
    assert "call_if_unset FLAG_MIRAGE_TOWER_VISIBLE, Route111_EventScript_SetLayoutNoMirageTower" in script
    assert "setmaplayoutindex LAYOUT_ROUTE111_NO_MIRAGE_TOWER" in script


def test_species_translation_is_the_builds_own_table():
    names = {283: "Mudkip", 286: "Poochyena", 288: "Zigzagoon", 290: "Wurmple"}
    for vanilla, exp in fx.EXP_SPECIES.items():
        assert SPECIES[exp]["name"] == names[vanilla]
    mudkip = SPECIES[fx.EXP_SPECIES[283]]
    assert [mudkip[k] for k in ("baseHP", "baseAttack", "baseDefense", "baseSpeed",
                                "baseSpAttack", "baseSpDefense")] == list(fx.MUDKIP["base"].values())
    items = {row["id"]: row["name"] for row in DATA["items"]}
    assert items[fx.EXP_ITEM_POKE_BALL] == "Poké Ball"


@pytest.mark.parametrize("kind", sorted(fx.EXP_TRANSPLANT_KINDS))
def test_exp_seed_is_one_expansion_slot_with_expansion_records(kind):
    seed = _seed(kind)
    assert C.qualify_flash(seed, title=T) == (True, "ok")
    parsed = C.parse_flash(seed, title=T)
    assert parsed["sb2"][0x09] & 1                     # CONTINUE_GAME_WARP asked for
    map_dir, group, num, layout_id, x, y = fx.EXP_KINDS[kind]
    assert struct.unpack_from("<hhbb", parsed["sb1"], 0) == (x, y, group, num)
    party = C.party_from_save(seed, title=T, layout=EXPANSION_PARTY_LAYOUT)
    assert party[0]["species"] == 258 and party[0]["level"] == fx.STARTER_LEVEL
    for mon in party:
        assert mon["checksum_ok"] and mon["pokeball"] == 1        # BALL_POKE in the Growth lane
    # teraType (Growth word0 bits 11-15) = the species' type[pid & 1], as CreateBoxMon sets it
    raw = parsed["sb1"][0x238:0x238 + C.PARTY_MON_SIZE]
    assert fx.exp_tera_type(raw) == SPECIES[258]["types"][party[0]["personality"] & 1]
    if kind == "pc":
        boxes = C.boxes_from_save(seed, title=T, layout=EXPANSION_PARTY_LAYOUT)
        assert [boxes[0][i]["species"] for i in (0, 1)] == [263, 265]
        assert [m["species"] for m in party] == [258, 261]
    balls = fx.exp_ball_pocket(seed)
    assert balls == [(fx.EXP_ITEM_POKE_BALL, fx.EMERALD_CATCH_BALLS if kind == "catch" else fx.EMERALD_BALLS)]


def test_a_seed_is_not_a_resave_and_a_cleared_warp_is():
    seed = _seed("town")
    assert any("CONTINUE_GAME_WARP" in p for p in fx.exp_fixture_problems(seed, "town"))
    parsed = C.parse_flash(seed, title=T)
    sb2 = bytearray(parsed["sb2"])
    sb2[0x09] = 0
    resaved = fx.exp_write_slot({"sb2": bytes(sb2), "sb1": parsed["sb1"], "storage": parsed["storage"]},
                                counter=parsed["counter"] + 1)
    assert fx.exp_fixture_problems(resaved, "town") == []


def test_derive_b_rekeys_expansion_records_and_keeps_the_saveblock3_chunk():
    seed = bytearray(_seed("pc"))
    parsed = C.parse_flash(bytes(seed), title=T)
    base = parsed["slot"] * C.NUM_SECTORS_PER_SLOT * C.SECTOR_SIZE
    seed[base + 0xF80:base + 0xF84] = b"SB3!"          # a SaveBlock3 chunk byte run (unchecksummed)
    b, manifest = fx.derive_b(bytes(seed), title=T)
    assert C.qualify_flash(b, title=T) == (True, "ok")
    assert b[base + 0xF80:base + 0xF84] == b"SB3!"
    a_party = C.party_from_save(bytes(seed), title=T, layout=EXPANSION_PARTY_LAYOUT)
    b_party = C.party_from_save(b, title=T, layout=EXPANSION_PARTY_LAYOUT)
    assert [m["species"] for m in b_party] == [m["species"] for m in a_party]
    assert all(m["ot_id"] != a["ot_id"] and m["checksum_ok"] and m["pokeball"] == 1
               for m, a in zip(b_party, a_party, strict=True))


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("exp_*.sav")))
def test_committed_exp_fixtures_are_game_resaves(name, request):
    body = (FIXTURES / name).read_bytes()
    kind = fx.exp_kind_of(Path(name))
    assert kind in fx.EXP_KINDS
    if kind not in fx.EXP_TRANSPLANT_KINDS:
        request.getfixturevalue("context")
    assert fx.exp_fixture_problems(body, kind) == []


def test_committed_exp_fixture_sha256s_are_the_ones_the_readme_publishes():
    import hashlib
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    names = sorted(p.name for p in FIXTURES.glob("exp_*.sav"))
    singletons = {"center", fx.EXP_FULL_BOX_KIND, fx.EXP_BOX0_FULL_KIND, fx.EXP_PC_CHAIN_KIND}
    expected = {f"exp_{kind}{suffix}.sav" for kind in fx.EXP_KINDS
                for suffix in (("",) if kind in singletons else ("", "_b"))}
    assert set(names) == expected
    for name in names:
        digest = hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
        rows = [line for line in readme.splitlines() if line.startswith(f"| `{name}` |")]
        assert len(rows) == 1 and f"`{digest}`" in rows[0], name


@pytest.mark.parametrize("kind,side,manifest_name,case", [
    *[(kind, side, "exp_acquisition_synth_manifest.json", kind.removesuffix("_synth"))
      for kind in fx.EXP_ACQUISITION_KINDS for side in ("a", "b")],
    *[(kind, side, "exp_static_wild_synth_manifest.json", kind.removeprefix("static_").removesuffix("_synth"))
      for kind in fx.EXP_STATIC_WILD_KINDS for side in ("a", "b")],
    (fx.EXP_FULL_BOX_KIND, "a", "exp_pc_full_box_synth_manifest.json", None),
    (fx.EXP_BOX0_FULL_KIND, "a", "exp_pc_box0_full_synth_manifest.json", None),
    (fx.EXP_PC_CHAIN_KIND, "a", "exp_pc_negative_chain_synth_manifest.json", None),
])
def test_registered_synth_generator_replays_the_published_raw_hash(kind, side, manifest_name, case, context):
    import hashlib

    manifest = json.loads((FIXTURES / manifest_name).read_text())
    if case is None:
        expected = manifest["raw_sha256"]
    else:
        entry = next(row for row in manifest["fixtures"] if row["case"] == case and row["side"] == side)
        expected = entry["synth_seed_sha256"] if kind in fx.EXP_ACQUISITION_KINDS else entry["generator_raw_sha256"]
    raw = fx.build_exp_seed(kind, [], side=side)
    assert hashlib.sha256(raw).hexdigest() == expected


# --- the offsets the seed and the harness read, bound to the build's own compiler -------------
HARNESS = json.loads((ROOT / "data/games/gen3_exp/28877d73/harness_facts.json").read_text(encoding="utf-8"))


def test_harness_facts_are_compiled_from_the_current_probe():
    from tools import gen_expansion_harness_facts as hf
    assert hf.check() == []


def test_seed_offsets_are_the_builds_compiler_facts():
    sb1, sb2 = HARNESS["structs"]["SaveBlock1"]["fields"], HARNESS["structs"]["SaveBlock2"]["fields"]
    assert [sb1[f]["offset"] for f in ("pos", "location", "continueGameWarp", "lastHealLocation",
                                       "mapLayoutId", "money", "bag", "flags")] == \
        [0x00, 0x04, 0x0C, 0x1C, 0x32, 0x490, 0x560, 0x1270]
    assert [sb2[f]["offset"] for f in ("playerGender", "specialSaveWarpFlags", "playerTrainerId",
                                       "encryptionKey")] == [0x08, 0x09, 0x0A, fx.SB2_ENCRYPTION_KEY]
    assert (HARNESS["structs"]["SaveBlock1"]["size"], HARNESS["structs"]["SaveBlock2"]["size"]) == \
        C._TITLE_SAVE_SIZES[T][::-1]
    facts = json.loads((ROOT / "data/games/gen3_exp/28877d73/facts.json").read_text(encoding="utf-8"))
    assert sb1["bag"]["offset"] + facts["structs"]["Bag"]["fields"]["pokeBalls"]["offset"] == fx.SB1_BALL_POCKET_EMERALD
    assert HARNESS["constants"]["ITEM_POKE_BALL"] == HARNESS["constants"]["BALL_POKE"] == fx.EXP_ITEM_POKE_BALL


def test_scripted_play_bag_offsets_are_the_builds_compiler_facts():
    """gen3_scripted_play.lua's Emerald ball throw serves both engine titles with one set of
    literals: they must equal the expansion build's compiled BagPosition/BagMenu offsets too."""
    import re
    lua = (ROOT / "lua/tests/gen3_scripted_play.lua").read_text(encoding="utf-8")
    pos = re.search(r"EM_BAG_POS_POCKET_OFF, EM_BAG_POS_CURSOR_OFF, EM_BAG_POS_SCROLL_OFF = "
                    r"(0x\w+), (0x\w+), (0x\w+)", lua)
    ctx = re.search(r"EM_BAG_MENU_CTX_NUM_ITEMS_OFF = (0x\w+)", lua)
    bag_pos, bag_menu = HARNESS["structs"]["BagPosition"]["fields"], HARNESS["structs"]["BagMenu"]["fields"]
    assert [int(v, 16) for v in pos.groups()] == [bag_pos["pocket"]["offset"],
                                                   bag_pos["cursorPosition"]["offset"],
                                                   bag_pos["scrollPosition"]["offset"]]
    assert int(ctx.group(1), 16) == bag_menu["contextMenuNumItems"]["offset"]
    assert re.search(r"local BALLS_POCKET = (\d+)", lua).group(1) == str(HARNESS["constants"]["POCKET_POKE_BALLS"])
    assert "local ITEM_POKE_BALL = TITLE == Syms.EXP_TITLE and 1 or 4" in lua


def test_pc_main_menu_rows_come_from_the_builds_compiled_enum():
    """The PC main-menu order is a private enum gated on OW_PC_MOVE_ORDER: the reference build
    compiles MOVE_MONS 0 / DEPOSIT 1 / WITHDRAW 2 (vanilla: WITHDRAW 0 / DEPOSIT 1 / MOVE_MONS 2).
    Live boxsync_gen3 on 28877d73 first opened MOVE POKEMON for a withdraw (a six-row popup)."""
    k = HARNESS["constants"]
    assert (k["OPTION_MOVE_MONS"], k["OPTION_DEPOSIT"], k["OPTION_WITHDRAW"]) == (0, 1, 2)
    assert "OW_PC_MOVE_ORDER" in HARNESS["provenance"]["pc_options_enum"]["text"]
    lua = (ROOT / "lua/tests/gen3_scripted_play.lua").read_text(encoding="utf-8")
    assert "withdraw = k.OPTION_WITHDRAW, deposit = k.OPTION_DEPOSIT, move_mons = k.OPTION_MOVE_MONS" in lua
    duo = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text(encoding="utf-8")
    assert "PC.mode(label, 0)" not in duo and "PC.mode(label, 1)" not in duo


def test_whiteout_respawns_are_the_roms_own_tables():
    """The expansion build whites out INTO a heal location's respawn map (OW_WHITEOUT_CUTSCENE
    >= GEN_4, src/overworld.c:744-756): the generator's source-derived table must equal the ROM's
    sHealLocations / sWhiteoutRespawnHealCenterMapIdxs (read through the build's own .sym)."""
    k, rows = HARNESS["constants"], HARNESS["whiteout_respawns"]
    assert k["OW_WHITEOUT_CUTSCENE"] >= k["GEN_4"] and len(rows) == k["NUM_HEAL_LOCATIONS"] - 1
    oldale = next(r for r in rows if r["id"] == "HEAL_LOCATION_OLDALE_TOWN")
    assert oldale["heal"] == [0, 10, 6, 17] and oldale["respawn"] == [2, 2, 7, 4]
    art = Path(os.environ.get("SLINK_EXPANSION_ARTIFACTS", ROOT / ".cache/expansion-output/reference"))
    if not (art / "pokeemerald.gba").is_file():
        pytest.skip("reference ROM absent")
    rom, syms = (art / "pokeemerald.gba").read_bytes(), {}
    for line in (art / "pokeemerald.sym").read_text().splitlines():
        parts = line.split()
        if len(parts) == 4:
            syms.setdefault(parts[3], int(parts[0], 16) - 0x08000000)
    heal = HARNESS["structs"]["HealLocation"]
    for i, row in enumerate(rows):
        at = syms["sHealLocations"] + i * heal["size"]
        g, n = struct.unpack_from("<bb", rom, at + heal["fields"]["mapGroup"]["offset"])
        x = struct.unpack_from("<H", rom, at + heal["fields"]["x"]["offset"])[0]
        y = struct.unpack_from("<H", rom, at + heal["fields"]["y"]["offset"])[0]
        assert [g, n, x, y] == row["heal"], row["id"]
        assert list(struct.unpack_from("<4H", rom, syms["sWhiteoutRespawnHealCenterMapIdxs"] + i * 8)) \
            == row["respawn"], row["id"]


def test_the_center_kind_stands_on_the_oldale_respawn_tile():
    src = _src()
    map_dir, group, num, layout_id, x, y = fx.EXP_KINDS["center"]
    oldale = next(r for r in HARNESS["whiteout_respawns"] if r["id"] == "HEAL_LOCATION_OLDALE_TOWN")
    assert [group, num, x, y] == oldale["respawn"]
    layouts = json.loads((src / "data/layouts/layouts.json").read_text())["layouts"]
    layout = layouts[layout_id - 1]
    assert layout["id"] == json.loads((src / f"data/maps/{map_dir}/map.json").read_text())["layout"]
    block = (src / layout["blockdata_filepath"]).read_bytes()
    v = int.from_bytes(block[(y * layout["width"] + x) * 2:][:2], "little")
    assert (v >> 10) & 3 == 0                             # collision 0: walkable
