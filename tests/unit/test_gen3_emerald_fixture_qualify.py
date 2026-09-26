"""Falsifiers for card E2-FIX-VARIANTS, rounds 1 and 3: the `pc`/`lowhp` (round 1) and
`evolve`/`poison`/`gift`/`catch` (round 3) SYNTH Emerald fixture kinds.

(a) build_emerald_seed for each new kind, decoded via the independent codec, carries exactly the
    party/box/ball contents the card specifies (species, level, checksum, HP, status, box slot);
(b) additive-only across both rounds: the pre-existing town/battle/trainer seeds stay
    byte-identical to the source cut (c78db7bc) that shipped card E1-FIX-2's SEED_SHA256 values;
(c) emerald_fixture_problems flags the mistakes a bad native re-save could plausibly make: a
    "pc" re-save missing its box mons, a "lowhp"/"poison" re-save still at full HP, and an
    "evolve" re-save at the wrong EXP.
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

EM = codec.TITLE_EMERALD

# Recorded by tests/unit/test_gen3_fixture_qualify_emerald.py (card E1-FIX-2) at the source cut
# c78db7bc, and (badges) by this file at round 3's cut d5208074 (card E2-BADGES). Card
# E2-FIX-VARIANTS is additive-only across every round: these four must reproduce bit for bit.
UNCHANGED_SEED_SHA256 = {
    "battle": "6ad42abbfd481978b237a4f2d3bc92eb4fb1dfdf97eba74572e7b4b0dfcc35a9",
    "town": "816d33b8e856ccb8fcf84b45f799495a6cfb00d77677ce7ce152cfbe21e7aca5",
    "trainer": "f6f301bc99c778e35aebef796093465d178397893430ae99063e4c07326f596e",
    "badges": "3aa798fd311cd63d6299d615c81bda63649738216eefcb9dda78aa1aab0d7196",
}


def _pret():
    try:
        return fx.pret_emerald()
    except FileNotFoundError as e:
        pytest.skip(f"pokeemerald not cloned: {e}")


def _seed(kind):
    return fx.build_emerald_seed(kind, fx.emerald_new_game_flags(_pret()))


def _rewrite_slot1(seed: bytearray, layout: list[dict], obj: str, blob: bytes) -> None:
    """Re-encode every chunk of `obj` (sb2/sb1/storage) in the seed's slot 1 (the SYNTH seed's
    own slot, EMERALD_SEED_COUNTER=1) from `blob`, recomputing each chunk's checksum -- the same
    pattern test_gen3_fixture_qualify_emerald.py uses to hand-edit a seed."""
    for entry in (e for e in layout if e["object"] == obj):
        at = (codec.NUM_SECTORS_PER_SLOT + entry["id"]) * codec.SECTOR_SIZE
        seed[at:at + codec.SECTOR_SIZE] = codec.write_sector(
            blob[entry["offset"]:entry["offset"] + entry["size"]], entry["id"], 1, layout)


# --- (b) additive-only: unchanged kinds are byte-identical to the source cut -------------------

@pytest.mark.parametrize("kind", sorted(UNCHANGED_SEED_SHA256))
def test_preexisting_kind_seeds_are_byte_identical_to_the_source_cut(kind):
    assert hashlib.sha256(_seed(kind)).hexdigest() == UNCHANGED_SEED_SHA256[kind]


# --- (a) the new kinds carry exactly the party/box contents the card specifies ------------------

def test_pc_seed_party_and_box_contents():
    seed = _seed("pc")
    party = codec.party_from_save(seed, title=EM)
    assert [(m["species"], m["level"], m["checksum_ok"]) for m in party] == [
        (fx.MUDKIP["species"], fx.STARTER_LEVEL, True),
        (fx.POOCHYENA["species"], fx.BOX1_LEVEL, True),
    ]
    assert party[0]["hp"] == party[0]["max_hp"] > 0   # starter: full HP, unmodified
    assert party[1]["hp"] == party[1]["max_hp"] > 0   # second slot: also full HP

    boxes = codec.boxes_from_save(seed, title=EM)
    box0 = boxes[0]
    assert (box0[0]["species"], box0[0]["checksum_ok"]) == (fx.ZIGZAGOON["species"], True)
    assert (box0[1]["species"], box0[1]["checksum_ok"]) == (fx.WURMPLE["species"], True)
    assert fx._box_mon_level(box0[0]) == fx.BOX1_LEVEL
    assert fx._box_mon_level(box0[1]) == fx.BOX1_LEVEL
    occupied = [(b, s) for b in range(codec.BOXES_PER_STORE) for s in range(codec.MONS_PER_BOX)
                if not (b == 0 and s in (0, 1)) and boxes[b][s]["species"]]
    assert occupied == []          # every other box slot (including box[0][2]) is empty

    sb1 = codec.parse_flash(seed, title=EM)["sb1"]
    assert sb1[codec.SB1_PARTY_COUNT_OFFSET_EMERALD] == 2
    assert fx.emerald_fixture_problems(seed, "pc") == [
        "specialSaveWarpFlags still has CONTINUE_GAME_WARP: not a game re-save"]


def test_lowhp_seed_party_is_the_starter_at_1_hp():
    seed = _seed("lowhp")
    (mon,) = codec.party_from_save(seed, title=EM)
    assert (mon["species"], mon["level"], mon["checksum_ok"]) == \
        (fx.MUDKIP["species"], fx.STARTER_LEVEL, True)
    assert mon["hp"] == 1
    assert mon["max_hp"] > 1
    assert mon["moves"][0] == 33 and mon["pp"][0] == 35   # TACKLE, full PP, untouched by the hp edit

    sb1 = codec.parse_flash(seed, title=EM)["sb1"]
    assert sb1[codec.SB1_PARTY_COUNT_OFFSET_EMERALD] == 1
    assert fx.emerald_fixture_problems(seed, "lowhp") == [
        "specialSaveWarpFlags still has CONTINUE_GAME_WARP: not a game re-save"]


def test_pc_and_lowhp_reuse_town_and_battle_tiles():
    assert fx.EMERALD_KINDS["pc"] == fx.EMERALD_KINDS["town"]
    assert fx.EMERALD_KINDS["lowhp"] == fx.EMERALD_KINDS["battle"]


# --- (c) emerald_fixture_problems catches a mis-built "re-save" --------------------------------

def test_pc_problems_flags_missing_box_mons():
    seed = bytearray(_seed("pc"))
    layout = codec.slot_layout(title=EM)
    parsed = codec.parse_flash(bytes(seed), title=EM)

    storage = bytearray(parsed["storage"])
    storage[codec.BOX_DATA_OFFSET:codec.BOX_DATA_OFFSET + 2 * codec.BOX_MON_SIZE] = \
        bytes(2 * codec.BOX_MON_SIZE)           # wipe box[0] slots 0/1 back to empty
    _rewrite_slot1(seed, layout, "storage", bytes(storage))

    sb2 = bytearray(parsed["sb2"])
    sb2[0x09] &= ~1                             # clear CONTINUE_GAME_WARP: isolate the box problem
    _rewrite_slot1(seed, layout, "sb2", bytes(sb2))

    problems = fx.emerald_fixture_problems(bytes(seed), "pc")
    assert any("box[0][0:2]" in p for p in problems), problems


def test_lowhp_problems_flags_full_hp():
    # A "battle"-kind build has the identical starter at FULL hp on the identical tile lowhp uses
    # (EMERALD_KINDS["lowhp"] == EMERALD_KINDS["battle"]): exactly the mistake a re-save that
    # forgot to check out at 1 HP would produce.
    seed = bytearray(_seed("battle"))
    layout = codec.slot_layout(title=EM)
    sb2 = bytearray(codec.parse_flash(bytes(seed), title=EM)["sb2"])
    sb2[0x09] &= ~1
    _rewrite_slot1(seed, layout, "sb2", bytes(sb2))

    problems = fx.emerald_fixture_problems(bytes(seed), "lowhp")
    assert any(p.startswith("party[0] hp=") and p.endswith("!= 1 (lowhp fixture)")
               for p in problems), problems


def test_box_mon_level_matches_get_level_from_mon_exp():
    """_box_mon_level mirrors pret's GetLevelFromMonExp (src/pokemon.c:2910-2920) specialised to
    GROWTH_MEDIUM_FAST (EXP_MEDIUM_FAST(n) = n**3)."""
    for level in (1, 2, 3, 4, 50, 100):
        assert fx._box_mon_level({"experience": level ** 3}) == level
        if level < 100:
            assert fx._box_mon_level({"experience": level ** 3 + 1}) == level


# --- round 3: evolve / poison / gift / catch ----------------------------------------------------

def test_evolve_seed_is_one_exp_short_of_the_lv16_threshold():
    seed = _seed("evolve")
    (mon,) = codec.party_from_save(seed, title=EM)
    assert (mon["species"], mon["level"], mon["checksum_ok"]) == \
        (fx.MUDKIP["species"], fx.EVOLVE_LEVEL, True)
    assert mon["experience"] == fx.EVOLVE_EXP == fx._exp_medium_slow(fx.EVOLVE_LEVEL + 1) - 1
    assert mon["hp"] == mon["max_hp"] > 0
    assert mon["moves"] == [33, 45, 55, 0] and 0 in mon["moves"]   # a free slot for MUD_SHOT
    assert fx.emerald_fixture_problems(seed, "evolve") == [
        "specialSaveWarpFlags still has CONTINUE_GAME_WARP: not a game re-save"]


def test_evolve_problems_flags_wrong_exp():
    # a plain "battle"-kind starter (Lv5, exp 135) standing on evolve's own tile is exactly the
    # mistake a re-save that didn't carry the Lv15 EXP-short mon would produce
    seed = bytearray(_seed("battle"))
    layout = codec.slot_layout(title=EM)
    sb2 = bytearray(codec.parse_flash(bytes(seed), title=EM)["sb2"])
    sb2[0x09] &= ~1
    _rewrite_slot1(seed, layout, "sb2", bytes(sb2))
    problems = fx.emerald_fixture_problems(bytes(seed), "evolve")
    assert any("Lv15 Mudkip" in p or "experience=" in p for p in problems), problems


def test_poison_seed_party_status_and_hp():
    seed = _seed("poison")
    party = codec.party_from_save(seed, title=EM)
    assert [(m["species"], m["level"], m["checksum_ok"]) for m in party] == [
        (fx.MUDKIP["species"], fx.STARTER_LEVEL, True),
        (fx.POOCHYENA["species"], fx.BOX1_LEVEL, True),
    ]
    assert party[0]["status"] == fx.STATUS1_POISON == 0x08
    assert party[0]["hp"] == 1 and party[0]["max_hp"] > 1
    assert party[1]["status"] == 0 and party[1]["hp"] == party[1]["max_hp"] > 0
    assert fx.EMERALD_KINDS["poison"] == fx.EMERALD_KINDS["town"]
    assert fx.emerald_fixture_problems(seed, "poison") == [
        "specialSaveWarpFlags still has CONTINUE_GAME_WARP: not a game re-save"]


def test_poison_problems_flags_full_hp():
    seed = bytearray(_seed("pc"))          # already has [Mudkip, Poochyena]; neither is poisoned
    layout = codec.slot_layout(title=EM)
    sb2 = bytearray(codec.parse_flash(bytes(seed), title=EM)["sb2"])
    sb2[0x09] &= ~1
    _rewrite_slot1(seed, layout, "sb2", bytes(sb2))
    problems = fx.emerald_fixture_problems(bytes(seed), "poison")
    assert any("STATUS1_POISON" in p for p in problems), problems


def test_gift_seed_is_lavaridge_next_to_the_egg_woman_with_room_in_the_party():
    seed = _seed("gift")
    (mon,) = codec.party_from_save(seed, title=EM)
    assert (mon["species"], mon["level"]) == (fx.MUDKIP["species"], fx.STARTER_LEVEL)
    assert fx.EMERALD_KINDS["gift"][0] == "LavaridgeTown"
    sb1 = codec.parse_flash(seed, title=EM)["sb1"]
    assert struct.unpack_from("<hh", sb1, 0x00) == (4, 8)
    assert fx.emerald_fixture_problems(seed, "gift") == [
        "specialSaveWarpFlags still has CONTINUE_GAME_WARP: not a game re-save"]


def test_gift_site_is_the_egg_woman_giving_wynaut_unconditionally():
    pret = _pret()
    m = json.loads((pret / "data/maps/LavaridgeTown/map.json").read_text())
    egg_woman = next(o for o in m["object_events"]
                     if o["script"] == "LavaridgeTown_EventScript_EggWoman")
    assert (egg_woman["x"], egg_woman["y"]) == (4, 7)
    assert egg_woman["movement_type"] == "MOVEMENT_TYPE_FACE_DOWN"
    assert egg_woman["flag"] == "0"        # always present: no hide-flag gate
    script = (pret / "data/maps/LavaridgeTown/scripts.inc").read_text(encoding="utf-8")
    body = script.split("LavaridgeTown_EventScript_EggWoman::", 1)[1].split("\nLavaridgeTown_", 1)[0]
    assert "giveegg SPECIES_WYNAUT" in body
    # the only prior-state check in the whole body is the already-given flag, which the seed
    # leaves clear -- confirming zero extra SYNTH flags are needed to reach the gift branch
    assert re.findall(r"goto_if_set (FLAG_\w+)", body) == ["FLAG_RECEIVED_LAVARIDGE_EGG"]
    groups = json.loads((pret / "data/maps/map_groups.json").read_text())
    group_name = groups["group_order"][fx.EMERALD_KINDS["gift"][1]]
    assert groups[group_name][fx.EMERALD_KINDS["gift"][2]] == "LavaridgeTown"
    species = (pret / "include/constants/species.h").read_text()
    assert re.search(r"#define SPECIES_WYNAUT (\d+)", species).group(1) == "360"


def test_catch_seed_is_battles_tile_with_twenty_balls():
    seed = _seed("catch")
    assert fx.EMERALD_KINDS["catch"] == fx.EMERALD_KINDS["battle"]
    (mon,) = codec.party_from_save(seed, title=EM)
    assert (mon["species"], mon["level"], mon["checksum_ok"]) == \
        (fx.MUDKIP["species"], fx.STARTER_LEVEL, True)
    assert fx.emerald_ball_pocket(seed) == [(fx.ITEM_POKE_BALL, 20)]
    assert fx.emerald_fixture_problems(seed, "catch") == [
        "specialSaveWarpFlags still has CONTINUE_GAME_WARP: not a game re-save"]


# --- round 3, OMP finding cx-fd70ac8f: single-ability species never randomize ability_num ------

def test_single_ability_synth_mons_have_ability_num_zero():
    """src/pokemon.c:2296-2300: CreateBoxMon only sets MON_DATA_ABILITY_NUM from
    `personality & 1` when the species has a second ability. POOCHYENA (RUN_AWAY/NONE),
    ZIGZAGOON (PICKUP/NONE), WURMPLE (SHIELD_DUST/NONE) and MUDKIP (TORRENT/NONE) are all
    single-ability, so a real CreateBoxMon leaves ability_num at its zero-init value."""
    poochyena = fx._synth_mon(fx.POOCHYENA, fx.BOX1_LEVEL, 0x504F4F43, "EMER", 1, party=True)
    zigzagoon = fx._synth_mon(fx.ZIGZAGOON, fx.BOX1_LEVEL, 0x5A49475A, "EMER", 1, party=False)
    wurmple = fx._synth_mon(fx.WURMPLE, fx.BOX1_LEVEL, 0x5755524D, "EMER", 1, party=False)
    evolve_mon = fx._evolve_mon("EMER", 1)
    assert (poochyena["ability_num"], zigzagoon["ability_num"], wurmple["ability_num"],
            evolve_mon["ability_num"]) == (0, 0, 0, 0)


def test_catch_problems_flags_five_balls():
    seed = bytearray(_seed("battle"))       # battle == catch's own tile, but only 5 balls
    layout = codec.slot_layout(title=EM)
    sb2 = bytearray(codec.parse_flash(bytes(seed), title=EM)["sb2"])
    sb2[0x09] &= ~1
    _rewrite_slot1(seed, layout, "sb2", bytes(sb2))
    problems = fx.emerald_fixture_problems(bytes(seed), "catch")
    assert any("ball pocket" in p for p in problems), problems
