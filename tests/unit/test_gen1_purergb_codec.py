"""gen1_codec's per-foundation Gen1Layout, checked against the pureRGB pack and the
literals docs/purergb/research/p3/server_literals_bbcd037.md pinned by hand.

Vanilla's own module-level codec functions/constants are untouched by this port (verified
by tests/unit/test_gen1_codec_vs_profile.py and the rest of the existing gen1_codec suite,
which stays green); this file only exercises the NEW per-foundation view.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.adapters import gen1_codec as codec

DATA = Path(__file__).resolve().parents[2] / "data" / "games" / "gen1_purergb"


@pytest.fixture(autouse=True)
def isolate_data_dir():
    yield


@pytest.fixture
def layout() -> codec.Gen1Layout:
    return codec.for_foundation("gen1_purergb")


def test_unknown_foundation_raises():
    with pytest.raises(ValueError):
        codec.for_foundation("gen1_not_a_real_foundation")


def test_for_foundation_is_cached():
    assert codec.for_foundation("gen1_purergb") is codec.for_foundation("gen1_purergb")


def test_current_box_and_bag_count_match_the_hand_derivation(layout):
    # docs/purergb/research/p3/server_literals_bbcd037.md's own worked derivation:
    # sMainData(flat 0x25A3) + (wCurrentBoxNum 0xD5A8 - wMainDataStart 0xD2FF) == 0x284C
    # (same value as vanilla, by coincidence); sMainData + (wNumBagItems 0xD542 -
    # wMainDataStart) == 0x27E6 (DIFFERENT from vanilla's 0x25C9 by 0x21D).
    assert layout.current_box == 0x284C
    assert layout.bag_count == 0x27E6
    assert layout.bag_count != codec._BAG_COUNT


def test_bag_capacity_and_ball_items_come_from_derived(layout):
    profile = json.loads((DATA / "profile.json").read_text(encoding="utf-8"))
    derived = profile["titles"]["purered"]["derived"]
    assert layout.bag_capacity == derived["bag_capacity"] == 30
    assert layout.ball_items == frozenset(derived["ball_items"]) == frozenset({1, 2, 3, 4, 5, 8})


def test_wram_bases_are_wpartycount_wboxcount(layout):
    profile = json.loads((DATA / "profile.json").read_text(encoding="utf-8"))
    ram = profile["titles"]["purered"]["ram"]
    assert layout.wram_bases == {"party": ram["wPartyCount"], "box": ram["wBoxCount"]}


def test_sram_layout_is_identical_to_vanillas_flat_offsets(layout):
    # docs/purergb/PLAN.md §11.2's "confirmed no-change" list: every SRAM symbol flattens
    # to the SAME offset as vanilla, once read through the pure profile's own ram/bank.
    for sym in ("sPlayerName", "sMainData", "sSpriteData", "sPartyData", "sCurBoxData",
                "sTileAnimations", "sMainDataCheckSum"):
        assert layout.sram_layout[sym] == codec.SRAM_LAYOUT[sym], sym
    assert layout.sram_layout["box_banks"] == codec.SRAM_LAYOUT["box_banks"]
    assert layout.sram_layout["all_boxes_checksums"] == codec.SRAM_LAYOUT["all_boxes_checksums"]


def test_decode_bag_on_a_synthetic_pure_sram_image(layout):
    """decode_bag at the PURE $27E6 address, with the vanilla derived BAG_CAPACITY value,
    equals the current literal-based reading — i.e. reading the pure address with pure
    derived values reproduces exactly what the vanilla adapter's own decode_bag/BAG_CAPACITY
    literal would report for a vanilla save at ITS OWN (different) address."""
    sram = bytearray(codec.SRAM_SIZE)
    sram[layout.bag_count] = 3
    items = [(4, 10), (1, 99), (30, 1)]  # Poke Ball(4)/Master Ball(1)/an arbitrary item
    for i, (item_id, qty) in enumerate(items):
        off = layout.bag_count + 1 + i * 2
        sram[off], sram[off + 1] = item_id, qty
    assert layout.decode_bag(bytes(sram)) == items
    assert layout.bag_quantity(bytes(sram), 4) == 10
    assert layout.bag_quantity(bytes(sram), 99) == 0
    # A vanilla decode at the SAME bytes but the WRONG (vanilla) address must NOT see this
    # bag — proving the two addresses genuinely differ and a literal-based read would miss it.
    assert codec.decode_bag(bytes(sram)) != items


def test_bag_capacity_is_30_not_vanillas_20(layout):
    sram = bytearray(codec.SRAM_SIZE)
    sram[layout.bag_count] = 30
    for i in range(30):
        off = layout.bag_count + 1 + i * 2
        sram[off], sram[off + 1] = 10, 1  # Bicycle-ish filler, quantity 1
    decoded = layout.decode_bag(bytes(sram))
    assert len(decoded) == 30


def test_internal_to_natdex_floating_magneton_and_missingno(layout):
    assert layout.internal_to_natdex(56) != 0     # Floating Magneton has a base dex
    assert layout.internal_to_natdex(181) == 0    # MISSINGNO is dex 0 (a real value, not a hole)
    with pytest.raises(ValueError):
        layout.internal_to_natdex(0)
    with pytest.raises(ValueError):
        layout.internal_to_natdex(191)


def test_natdex_to_internal_round_trips_for_an_ordinary_species(layout):
    dex = 1  # Bulbasaur
    internal = layout.natdex_to_internal(dex)
    assert layout.internal_to_natdex(internal) == dex


def test_decode_name_uses_the_pure_charmap(layout):
    # The pure charmap's byte->glyph table covers the full 0-255 range (unlike vanilla's
    # sparse dict); plain uppercase ASCII letters ($80-$99) are unchanged from vanilla.
    encoded = layout.encode_name("RED")
    assert layout.decode_name(encoded) == "RED"


def test_encode_name_round_trips_through_terminator(layout):
    name = layout.encode_name("AB")
    assert len(name) == codec.NAME_SIZE
    assert name[2] == layout.name_end
    assert layout.decode_name(name) == "AB"


def test_live5_bulbasaur_decode_still_holds():
    """Live 5 pin (docs/purergb/research; the P3b brief repeats it verbatim): a pure
    SaveRAM decoded with the UNCHANGED vanilla codec gave Bulbasaur L5 DVs 0x7693 OT
    0xC131 — decode_party_mon is pure struct-geometry math with no foundation-specific
    address lookup inside it, so this must keep holding no matter what this port changes
    elsewhere in gen1_codec.py."""
    blob = bytearray(codec.PARTY_MON_SIZE)
    blob[0] = 153          # species (internal id, irrelevant to this geometry check)
    blob[12:14] = (0xC131).to_bytes(2, "big")   # ot_id
    blob[27:29] = (0x7693).to_bytes(2, "big")   # dvs.raw
    blob[33] = 5           # level
    mon = codec.decode_party_mon(bytes(blob))
    assert mon["ot_id"] == 0xC131
    assert mon["dvs"]["raw"] == 0x7693
    assert mon["level"] == 5
