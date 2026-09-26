"""Falsifiers for card E2-FIX-VARIANTS: the new Emerald `pc` and `lowhp` SYNTH fixture kinds.

(a) build_emerald_seed for each new kind, decoded via the independent codec, carries exactly the
    party/box contents the card specifies (species, level, checksum, HP, box slot);
(b) card E2-FIX-VARIANTS is additive-only: the pre-existing town/battle/trainer seeds stay
    byte-identical to the source cut (c78db7bc) that shipped card E1-FIX-2's SEED_SHA256 values;
(c) emerald_fixture_problems flags a "pc" re-save missing its box mons and a "lowhp" re-save
    still at full HP -- the two mistakes a bad native re-save could plausibly make.
"""

import hashlib
import os
import sys

import pytest

from server.adapters import gen3_codec as codec

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen3_fixtures as fx  # noqa: E402  (tools/ is not a package)

EM = codec.TITLE_EMERALD

# Recorded by tests/unit/test_gen3_fixture_qualify_emerald.py (card E1-FIX-2) at the source cut
# c78db7bc. Card E2-FIX-VARIANTS is additive-only: these three must reproduce bit for bit.
UNCHANGED_SEED_SHA256 = {
    "battle": "6ad42abbfd481978b237a4f2d3bc92eb4fb1dfdf97eba74572e7b4b0dfcc35a9",
    "town": "816d33b8e856ccb8fcf84b45f799495a6cfb00d77677ce7ce152cfbe21e7aca5",
    "trainer": "f6f301bc99c778e35aebef796093465d178397893430ae99063e4c07326f596e",
}


def _pret():
    try:
        return fx.pret_emerald()
    except FileNotFoundError:
        pytest.skip("pret pokeemerald checkout absent")


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
